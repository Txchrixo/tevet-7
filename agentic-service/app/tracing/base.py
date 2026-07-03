"""Tracer abstraction primitives.

A **Tracer** captures the full execution of one ``/api/chat`` request:

- the user prompt,
- the SQL generated (post-sqlglot rewriting),
- the tool calls (with per-call latency),
- the sqlglot validation result,
- the token counts + cost estimate,
- the total request latency.

Concrete tracers live in :mod:`app.tracing.local` (writes to the SQLite
``traces`` table) and :mod:`app.tracing.langfuse_tracer` (also ships to a
Langfuse instance, on top of local persistence).

The Protocol below is intentionally synchronous-by-convention even though
``end_trace`` may hit a DB — the caller may ``await`` the returned coroutine
or call it eagerly. We keep the API synchronous so the orchestrator (which
runs a sync ``run()`` loop with awaited tool calls) can call it without
``await`` ceremony; LocalTracer's persistence is fire-and-forget into a
background task queue.

NOTE: ``end_trace`` IS async because it writes to SQLite. The orchestrator
awaits it.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


# ─────────────────────────────────────────────────────────────────────────────
# Span + TraceContext dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Span:
    """One named segment of a trace (e.g. ``sqlglot_validation``).

    Spans are started by ``Tracer.start_span`` and ended by
    ``Tracer.end_span``. The orchestrator wraps every step (comprehension,
    SQL generation, validation, execution, synthesis) in a span.
    """

    name: str
    started_at: float
    ended_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # "ok" | "error" | "blocked"
    # Optional backend-specific handle (e.g. a LangfuseSpan object). The
    # LangfuseTracer stores the Langfuse observation here so end_span can
    # update it without a lookup.
    backend_handle: Any = None

    @property
    def duration_ms(self) -> int:
        """Duration in milliseconds, or 0 if the span is still open."""
        if self.ended_at is None:
            return 0
        return int((self.ended_at - self.started_at) * 1000)


@dataclass
class TraceContext:
    """Per-request trace handle.

    Created by ``Tracer.start_trace`` and passed to every subsequent
    ``start_span`` / ``end_span`` / ``end_trace`` call so the tracer can
    correlate them.
    """

    trace_id: str
    user_message: str
    identity: dict[str, Any]
    spans: list[Span] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
    # Backend-specific handle (e.g. the Langfuse root observation).
    backend_handle: Any = None
    # Free-form metadata bag the orchestrator can populate between spans
    # (e.g. intent classification result, generated SQL). The end_trace
    # call serialises this into the persisted row.
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def new_trace_id() -> str:
        """Return a fresh uuid4 hex string."""
        return uuid.uuid4().hex


# ─────────────────────────────────────────────────────────────────────────────
# Tracer Protocol
# ─────────────────────────────────────────────────────────────────────────────


class Tracer(Protocol):
    """Tracer-agnostic observability contract.

    Why a Protocol (structural type) rather than an ABC?

    So a third-party tracer (e.g. OpenTelemetry, LangSmith) can satisfy the
    contract without inheriting from our base class — same shape, zero
    coupling. ``isinstance(x, Tracer)`` checks are NOT used; the factory
    just returns "something that quacks like a Tracer".
    """

    def start_trace(
        self, user_message: str, identity: dict[str, Any]
    ) -> TraceContext:
        """Open a new trace for one chat request. Returns the context handle."""
        ...

    def start_span(
        self, ctx: TraceContext, name: str, **metadata: Any
    ) -> Span:
        """Open a named span within the trace. End it via ``end_span``."""
        ...

    def end_span(
        self,
        ctx: TraceContext,
        span: Span,
        status: str = "ok",
        **metadata: Any,
    ) -> None:
        """Close a span. ``status`` is one of ok|error|blocked."""
        ...

    async def end_trace(self, ctx: TraceContext, result: dict[str, Any]) -> str:
        """Finalise the trace with the full result dict.

        ``result`` carries the orchestrator's structured output (answer, sql,
        tool_calls, tokens, latency, refused, security_incident, ...). The
        tracer persists what it can — see ``LocalTracer._ROW_FIELDS`` for the
        canonical list. Returns the trace_id.
        """
        ...

    def flush(self) -> None:
        """Flush any buffered events to the backend (best-effort)."""
        ...
