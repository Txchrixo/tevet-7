"""ModelRouter - multi-provider fallback chain with circuit breaker + caching.

Holds ``list[LLMProvider]``. Calls ``provider.chat(...)`` and gets a
normalized ``ChatResult``. Tries providers in order on failure. Circuit
breaker per provider (3 failures → OPEN 60s → HALF-OPEN → CLOSED).

LLM response cache (SQLite ``llm_cache`` table): same prompt hash → same
answer, instantly, 0 tokens. TTL 1h.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from app.agents.llm_provider import ChatResult, LLMProvider, StreamDelta
from app.db_seed import get_engine, llm_cache

logger = logging.getLogger("tevet7.model_router")

_CIRCUIT_FAILURE_THRESHOLD = 3
_CIRCUIT_COOLDOWN_S = 60.0
_CACHE_TTL_S = 3600.0


class _CircuitState:
    """Per-provider circuit breaker state."""

    def __init__(self) -> None:
        self.consecutive_failures: int = 0
        self.open_until: float = 0.0

    def is_open(self, now: float) -> bool:
        return self.open_until > now

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.open_until = 0.0

    def record_failure(self, now: float) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= _CIRCUIT_FAILURE_THRESHOLD:
            self.open_until = now + _CIRCUIT_COOLDOWN_S
            logger.warning(
                "Circuit OPEN for provider after %d failures - cooldown %.0fs",
                self.consecutive_failures, _CIRCUIT_COOLDOWN_S,
            )


class ModelRouter:
    """Multi-provider fallback chain with circuit breaker + LLM cache."""

    class AllProvidersFailedError(RuntimeError):
        """All providers failed or had open circuits."""

    def __init__(
        self,
        providers: list[LLMProvider],
        cache_enabled: bool = True,
    ) -> None:
        if not providers:
            raise ValueError("ModelRouter requires at least one provider")
        self._providers = providers
        self._cache_enabled = cache_enabled
        self._circuits: dict[str, _CircuitState] = {
            p.name: _CircuitState() for p in providers
        }
        logger.info(
            "ModelRouter initialized - %d providers: %s (cache=%s)",
            len(providers), ", ".join(p.name for p in providers), cache_enabled,
        )

    @staticmethod
    def _compute_hash(
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: Any,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> str:
        payload = {
            "messages": messages,
            "tools": tools or [],
            "tool_choice": tool_choice,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _cache_get(self, prompt_hash: str) -> tuple[ChatResult, str] | None:
        if not self._cache_enabled:
            return None
        try:
            engine = get_engine()
            cutoff = datetime.utcnow() - timedelta(seconds=_CACHE_TTL_S)
            async with engine.begin() as conn:
                row = await conn.execute(
                    select(
                        llm_cache.c.response_json,
                        llm_cache.c.model,
                        llm_cache.c.created_at,
                    ).where(llm_cache.c.prompt_hash == prompt_hash)
                ).first()
                if row is None:
                    return None
                if row.created_at < cutoff:
                    await conn.execute(
                        delete(llm_cache).where(llm_cache.c.prompt_hash == prompt_hash)
                    )
                    return None
                data = json.loads(row.response_json)
                from app.agents.llm_provider import Usage, ToolCall
                result = ChatResult(
                    content=data.get("content", ""),
                    tool_calls=[
                        ToolCall(id=tc.get("id", ""), name=tc.get("name", ""),
                                 arguments=tc.get("arguments", {}))
                        for tc in data.get("tool_calls", [])
                    ],
                    usage=Usage(
                        prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                        completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                        cache_hit_tokens=data.get("usage", {}).get("cache_hit_tokens", 0),
                        cache_miss_tokens=data.get("usage", {}).get("cache_miss_tokens", 0),
                    ),
                    model=f"cache({row.model})",
                )
                return result, f"cache({row.model})"
        except Exception as exc:  # noqa: BLE001
            logger.debug("Cache get failed: %s", exc)
            return None

    async def _cache_set(self, prompt_hash: str, result: ChatResult) -> None:
        if not self._cache_enabled or result.raw is None:
            return
        try:
            data = {
                "content": result.content,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in result.tool_calls
                ],
                "usage": {
                    "prompt_tokens": result.usage.prompt_tokens,
                    "completion_tokens": result.usage.completion_tokens,
                    "cache_hit_tokens": result.usage.cache_hit_tokens,
                    "cache_miss_tokens": result.usage.cache_miss_tokens,
                },
            }
            engine = get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    delete(llm_cache).where(llm_cache.c.prompt_hash == prompt_hash)
                )
                await conn.execute(
                    llm_cache.insert().values(
                        prompt_hash=prompt_hash,
                        response_json=json.dumps(data, ensure_ascii=False, default=str),
                        model=result.model,
                        created_at=datetime.utcnow(),
                    )
                )
            logger.debug("Cache SET - hash=%s… model=%s", prompt_hash[:12], result.model)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Cache set failed: %s", exc)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict | None = None,
        temperature: float = 0.0,
        max_tokens: int = 800,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResult:
        prompt_hash = self._compute_hash(
            messages, tools, tool_choice, temperature, max_tokens, stream
        )

        # [1] Check cache
        cached = await self._cache_get(prompt_hash)
        if cached is not None:
            result, label = cached
            logger.info("Cache HIT - hash=%s… model=%s", prompt_hash[:12], label)
            if stream and result.stream is None:
                result.stream = self._fake_stream(result)
            return result

        # [2] Try each provider in order
        now = time.monotonic()
        last_error: Exception | None = None

        for provider in self._providers:
            circuit = self._circuits[provider.name]
            if circuit.is_open(now):
                logger.debug("Skipping %s - circuit open", provider.name)
                continue

            try:
                result = await provider.chat(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=stream,
                    **kwargs,
                )
                circuit.record_success()
                if not stream:
                    await self._cache_set(prompt_hash, result)
                if provider != self._providers[0]:
                    logger.info("Request served by FALLBACK: %s", provider.name)
                return result

            except Exception as exc:
                circuit.record_failure(now)
                last_error = exc
                status = _extract_status(exc)
                logger.warning(
                    "Provider %s failed (%s) - trying next fallback",
                    provider.name, status or type(exc).__name__,
                )
                now = time.monotonic()
                continue

        raise self.AllProvidersFailedError(
            f"All {len(self._providers)} providers failed. Last error: {last_error}"
        )

    @staticmethod
    def _fake_stream(result: ChatResult) -> Any:
        async def _gen():
            yield StreamDelta(content=result.content, usage=result.usage)
        return _gen()


def _extract_status(exc: Exception) -> str | None:
    for attr in ("status_code", "code", "statusCode"):
        v = getattr(exc, attr, None)
        if v is not None:
            return str(v)
    msg = str(exc)
    for code in ("400", "402", "403", "404", "429", "500", "502", "503", "504"):
        if code in msg:
            return code
    return None
