"""LangfuseTracer — ships trace events to a Langfuse instance *on top of*
local persistence.

Design
------

This tracer wraps a :class:`LocalTracer` (which always persists to SQLite)
and ALSO forwards events to a Langfuse client. The wrapping is additive:

* ``start_trace`` → opens a Langfuse root observation (``as_type='chain'``)
  and stores the handle on the ``TraceContext.backend_handle``.
* ``start_span`` / ``end_span`` → opens / updates a Langfuse child
  observation under the root.
* ``end_trace`` → updates the root observation with the final output, then
  delegates to ``LocalTracer.end_trace`` for local persistence.
* ``flush`` → ``langfuse.flush()`` (best-effort).

Graceful degradation
--------------------

Langfuse SDK errors (auth failure, network down, version mismatch) are
caught and logged at WARNING. The user request MUST NEVER crash because of
tracing — the LocalTracer still writes the row to SQLite.

The Langfuse client is constructed lazily on first ``start_trace`` so the
factory can return a LangfuseTracer even before the package is importable
(tests construct it directly with ``_skip_init=True``).
"""

from __future__ import annotations

import logging
from typing import Any

from app.tracing.base import Span, TraceContext
from app.tracing.local import LocalTracer

logger = logging.getLogger("tevet7.tracing.langfuse")


def _import_langfuse():
    """Import the langfuse package lazily; return None if not installed."""
    try:
        from langfuse import Langfuse  # type: ignore

        return Langfuse
    except Exception as exc:  # noqa: BLE001
        logger.warning("langfuse package not importable: %s", exc)
        return None


class LangfuseTracer:
    """Tracer that ships to Langfuse in addition to local SQLite."""

    def __init__(
        self,
        public_key: str | None = None,
        secret_key: str | None = None,
        host: str | None = None,
    ) -> None:
        from app.config import get_settings

        self._local = LocalTracer()
        self._settings = get_settings()
        self._public_key = public_key or self._settings.langfuse_public_key
        self._secret_key = secret_key or self._settings.langfuse_secret_key
        self._host = host or self._settings.langfuse_host
        self._client: Any = None  # lazily constructed

    # ── Lazy client ─────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        """Return the Langfuse client, building it on first use.

        Returns None if the package is missing or construction fails — every
        subsequent trace call then degrades to LocalTracer-only behaviour.
        """
        if self._client is not None:
            return self._client
        Langfuse = _import_langfuse()
        if Langfuse is None:
            return None
        try:
            self._client = Langfuse(
                public_key=self._public_key,
                secret_key=self._secret_key,
                host=self._host,
            )
            logger.info(
                "LangfuseTracer client ready (host=%s)", self._host
            )
        except Exception:  # noqa: BLE001
            logger.warning("Langfuse client construction failed", exc_info=True)
            self._client = None
        return self._client

    # ── Tracer surface ──────────────────────────────────────────────────────

    def start_trace(
        self, user_message: str, identity: dict[str, Any]
    ) -> TraceContext:
        ctx = self._local.start_trace(user_message, identity)
        client = self._get_client()
        if client is None:
            return ctx
        try:
            # In Langfuse v4 the root observation creates a new trace
            # automatically when trace_context is omitted. We store the
            # returned handle on ctx.backend_handle so subsequent spans can
            # nest under it.
            handle = client.start_observation(
                name="producer_copilot",
                as_type="chain",
                input={"user_message": user_message, "identity": identity},
                metadata={
                    "tenant_id": identity.get("tenant_id", "dp"),
                    "identity_id": identity.get("identity_id"),
                    "producer_id": identity.get("producer_id"),
                    "role": identity.get("role"),
                },
            )
            ctx.backend_handle = handle
        except Exception:  # noqa: BLE001
            logger.warning("Langfuse start_observation failed", exc_info=True)
        return ctx

    def start_span(
        self, ctx: TraceContext, name: str, **metadata: Any
    ) -> Span:
        span = self._local.start_span(ctx, name, **metadata)
        # Try to open a Langfuse child observation under the root.
        root = ctx.backend_handle
        if root is None:
            return span
        try:
            child = root.start_observation(
                name=name,
                as_type="span",
                input=metadata or None,
            )
            span.backend_handle = child
        except Exception:  # noqa: BLE001
            logger.debug("Langfuse start_span(%s) failed", name, exc_info=True)
        return span

    def end_span(
        self,
        ctx: TraceContext,
        span: Span,
        status: str = "ok",
        **metadata: Any,
    ) -> None:
        self._local.end_span(ctx, span, status, **metadata)
        child = span.backend_handle
        if child is None:
            return
        try:
            level = {
                "ok": "DEFAULT",
                "error": "ERROR",
                "blocked": "WARNING",
            }.get(status, "DEFAULT")
            child.update(
                output=metadata or None,
                level=level,
                status_message=metadata.get("detail") if metadata else None,
            )
            child.end()
        except Exception:  # noqa: BLE001
            logger.debug("Langfuse end_span(%s) failed", span.name, exc_info=True)

    async def end_trace(self, ctx: TraceContext, result: dict[str, Any]) -> str:
        # Update the Langfuse root observation with the final output, then
        # delegate to LocalTracer for SQLite persistence.
        root = ctx.backend_handle
        if root is not None:
            try:
                root.update(
                    output={
                        "answer": (result.get("answer") or "")[:500],
                        "sql": result.get("sql"),
                        "refused": result.get("refused"),
                        "tokens_in": result.get("tokens_in"),
                        "tokens_out": result.get("tokens_out"),
                        "latency_ms": result.get("latency_ms"),
                    },
                    level="ERROR" if result.get("error") else "DEFAULT",
                )
                root.end()
            except Exception:  # noqa: BLE001
                logger.warning("Langfuse end_trace update failed", exc_info=True)
        trace_id = await self._local.end_trace(ctx, result)
        # Best-effort flush.
        self.flush()
        return trace_id

    def flush(self) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            client.flush()
        except Exception:  # noqa: BLE001
            logger.debug("Langfuse flush failed", exc_info=True)

    # ── Pass-through query surface (so /api/traces works the same) ──────────

    async def list_recent(self, limit: int = 50):
        return await self._local.list_recent(limit=limit)

    async def get(self, trace_id: str):
        return await self._local.get(trace_id)
