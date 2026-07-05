"""Base class + shared helpers for OpenAI-compatible LLM adapters.

SOLID: each provider adapter extends ``BaseOpenAIAdapter`` and owns ONLY
its provider-specific config (base_url, default model, timeout). The shared
protocol logic (chat, streaming, tool-call parsing, cache-metric extraction)
lives here.

Performance: ``AsyncOpenAI`` clients are expensive to create (connection
pool, TLS handshake). ``_get_client`` caches one client per
``(api_key, base_url, timeout)`` pair so repeated factory builds reuse the
same client across requests.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from app.agents.llm_provider import ChatResult, StreamDelta, ToolCall, Usage

logger = logging.getLogger("tevet7.llm_adapters")


# ─────────────────────────────────────────────────────────────────────────────
# Shared parsing helpers (pure functions)
# ─────────────────────────────────────────────────────────────────────────────


def extract_cache_metrics(usage_obj: Any) -> tuple[int, int]:
    """Extract (cache_hit_tokens, cache_miss_tokens) from an OpenAI usage obj.

    Handles DeepSeek native (``prompt_cache_hit_tokens``) + OpenRouter
    normalised (``prompt_tokens_details.cached_tokens``). Returns (0, 0) for
    providers without caching (Groq, Gemini).
    """
    if usage_obj is None:
        return 0, 0
    hit = 0
    miss = 0
    try:
        hit = int(getattr(usage_obj, "prompt_cache_hit_tokens", 0) or 0)
        miss = int(getattr(usage_obj, "prompt_cache_miss_tokens", 0) or 0)
    except Exception:  # noqa: BLE001
        pass
    if hit == 0 and miss == 0:
        try:
            ptd = getattr(usage_obj, "prompt_tokens_details", None)
            if ptd is not None:
                cached = (
                    getattr(ptd, "cached_tokens", None)
                    if not isinstance(ptd, dict)
                    else ptd.get("cached_tokens")
                )
                if cached:
                    hit = int(cached)
        except Exception:  # noqa: BLE001
            pass
    if miss == 0:
        try:
            prompt_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
            if prompt_tokens and hit:
                miss = max(0, prompt_tokens - hit)
            elif prompt_tokens and not hit:
                miss = prompt_tokens
        except Exception:  # noqa: BLE001
            pass
    return hit, miss


def parse_tool_calls(message: Any) -> list[ToolCall]:
    """Extract normalized ToolCalls from an OpenAI assistant message."""
    tcs = getattr(message, "tool_calls", None) or []
    result: list[ToolCall] = []
    for tc in tcs:
        tc_id = getattr(tc, "id", "") or ""
        fn = getattr(tc, "function", None)
        if fn is None:
            continue
        name = getattr(fn, "name", "") or ""
        args_raw = getattr(fn, "arguments", "") or "{}"
        try:
            args = json.loads(args_raw) if args_raw else {}
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        result.append(ToolCall(id=tc_id, name=name, arguments=args))
    return result


def tool_calls_to_openai_dict(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
    """Serialize normalized ToolCalls back to the OpenAI dict shape.

    Used when appending an assistant message (with tool_calls) back into the
    ``messages`` list for the next LLM call.
    """
    return [
        {
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.name,
                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
            },
        }
        for tc in tool_calls
    ]


def build_usage(usage_obj: Any) -> Usage:
    """Build a normalized ``Usage`` from an OpenAI usage object."""
    if usage_obj is None:
        return Usage()
    hit, miss = extract_cache_metrics(usage_obj)
    return Usage(
        prompt_tokens=int(getattr(usage_obj, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage_obj, "completion_tokens", 0) or 0),
        cache_hit_tokens=hit,
        cache_miss_tokens=miss,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Client cache (perf: reuse AsyncOpenAI clients across requests)
# ─────────────────────────────────────────────────────────────────────────────

_client_cache: dict[tuple[str, str, float], Any] = {}


def _get_client(api_key: str, base_url: str, timeout: float = 20.0) -> Any:
    """Return a cached ``AsyncOpenAI`` client for the (key, url, timeout) tuple."""
    cache_key = (api_key, base_url, timeout)
    client = _client_cache.get(cache_key)
    if client is None:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,  # the ModelRouter handles retries via fallback
        )
        _client_cache[cache_key] = client
        logger.debug("Created AsyncOpenAI client for %s (timeout=%.0fs)", base_url, timeout)
    return client


# ─────────────────────────────────────────────────────────────────────────────
# Base adapter
# ─────────────────────────────────────────────────────────────────────────────


class BaseOpenAIAdapter:
    """Base class for OpenAI-compatible LLM providers.

    Subclasses set provider-specific defaults (base_url, model, timeout).
    The shared ``chat()`` logic lives here.
    """

    DEFAULT_BASE_URL: str = "https://api.openai.com/v1"
    DEFAULT_MODEL: str = "gpt-4o-mini"
    DEFAULT_TIMEOUT: float = 20.0

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str | None = None,
        name: str = "",
        timeout: float | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url or self.DEFAULT_BASE_URL
        self._model = model or self.DEFAULT_MODEL
        self._timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self.name = name or self._model
        self._client = _get_client(self._api_key, self._base_url, self._timeout)

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
        create_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            create_kwargs["tools"] = tools
            create_kwargs["tool_choice"] = tool_choice if tool_choice is not None else "auto"
        if stream:
            create_kwargs["stream"] = True
            create_kwargs["stream_options"] = {"include_usage": True}
        create_kwargs.update(kwargs)

        if stream:
            return await self._chat_stream(create_kwargs)
        return await self._chat_nonstream(create_kwargs)

    async def _chat_nonstream(self, create_kwargs: dict[str, Any]) -> ChatResult:
        response = await self._client.chat.completions.create(**create_kwargs)
        msg = response.choices[0].message
        content = getattr(msg, "content", "") or ""
        tool_calls = parse_tool_calls(msg)
        usage = build_usage(getattr(response, "usage", None))
        return ChatResult(
            content=content, tool_calls=tool_calls, usage=usage,
            model=self.name, raw=response,
        )

    async def _chat_stream(self, create_kwargs: dict[str, Any]) -> ChatResult:
        stream_obj = await self._client.chat.completions.create(**create_kwargs)
        model_name = self.name

        async def _iterate() -> AsyncIterator[StreamDelta]:
            final_usage: Usage | None = None
            async for chunk in stream_obj:
                if getattr(chunk, "usage", None) is not None:
                    final_usage = build_usage(chunk.usage)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None) or ""
                if piece:
                    yield StreamDelta(content=piece)
            if final_usage is not None:
                yield StreamDelta(usage=final_usage)

        return ChatResult(model=model_name, stream=_iterate(), raw=None)
