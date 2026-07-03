"""LocalTracer — default tracer that persists every trace to the SQLite
``traces`` table.

Design
------

* One in-process ring buffer of the last 100 finalised traces powers the
  ``GET /api/traces`` listing endpoint without touching the DB on every call.
* ``end_trace`` is async — it awaits an ``INSERT`` into ``traces`` via the
  shared SQLAlchemy async engine (``app.db_seed.get_engine``).
* ``start_trace`` / ``start_span`` / ``end_span`` are sync — they only
  mutate in-memory state, so they don't block the event loop.
* Failures (DB locked, schema drift) are logged at WARNING and swallowed:
  tracing must never crash a user request. The in-memory copy is still
  served from the ring buffer even if the DB write fails.

The ``traces`` table schema lives in :mod:`app.db_seed` (alongside the
business tables) so ``init_db()`` creates it in the same transaction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db_seed import get_engine, traces_table
from app.tracing.base import Span, TraceContext
from app.tracing.pricing import compute_cost

logger = logging.getLogger("tevet7.tracing.local")

# Ring-buffer size for the in-memory recent-traces cache.
_RING_BUFFER_SIZE = 100


class LocalTracer:
    """Default tracer — persists traces to SQLite + keeps an in-memory cache."""

    def __init__(self) -> None:
        # Most-recent-first ring buffer (we append on the right, popleft when
        # over capacity). The list endpoint reverses before returning so the
        # newest trace is first.
        self._buffer: deque[dict[str, Any]] = deque(maxlen=_RING_BUFFER_SIZE)
        # Lock for buffer mutation (end_trace may be called concurrently).
        self._lock = asyncio.Lock()

    # ── Tracer protocol (sync surface) ──────────────────────────────────────

    def start_trace(
        self, user_message: str, identity: dict[str, Any]
    ) -> TraceContext:
        ctx = TraceContext(
            trace_id=TraceContext.new_trace_id(),
            user_message=user_message,
            identity=dict(identity),
        )
        logger.debug("start_trace id=%s", ctx.trace_id)
        return ctx

    def start_span(
        self, ctx: TraceContext, name: str, **metadata: Any
    ) -> Span:
        span = Span(name=name, started_at=time.monotonic(), metadata=dict(metadata))
        ctx.spans.append(span)
        return span

    def end_span(
        self,
        ctx: TraceContext,
        span: Span,
        status: str = "ok",
        **metadata: Any,
    ) -> None:
        span.ended_at = time.monotonic()
        span.status = status
        if metadata:
            span.metadata.update(metadata)

    async def end_trace(self, ctx: TraceContext, result: dict[str, Any]) -> str:
        """Finalise the trace, persist to SQLite, push into the ring buffer."""
        latency_ms = int(
            (time.monotonic() - ctx.started_at) * 1000
        )
        tokens_in = int(result.get("tokens_in", 0) or 0)
        tokens_out = int(result.get("tokens_out", 0) or 0)
        cost_usd = compute_cost(tokens_in, tokens_out)

        # Serialise tool_calls + steps to JSON columns (list of dicts).
        tool_calls = result.get("tool_calls") or []
        steps = result.get("steps") or []

        # The orchestrator already populated steps with {index, title, detail,
        # status, duration_ms}. We keep them verbatim; the API layer reads
        # them back as-is.
        row = {
            "id": ctx.trace_id,
            "created_at": datetime.now(timezone.utc),
            "tenant_id": ctx.identity.get("tenant_id", "dp"),
            "user_message": ctx.user_message,
            "identity_id": ctx.identity.get("identity_id"),
            "producer_id": ctx.identity.get("producer_id"),
            "role": ctx.identity.get("role"),
            "intent": result.get("intent"),
            "sql_generated": result.get("sql"),
            "sql_valid": bool(result.get("sql_valid", result.get("sql") is not None)),
            "scope_applied": bool(result.get("scope_applied", False)),
            "security_incident": bool(result.get("security_incident", False)),
            "refused": bool(result.get("refused", False)),
            "tool_calls": json.dumps(tool_calls, ensure_ascii=False),
            "steps": json.dumps(steps, ensure_ascii=False),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "error": result.get("error"),
            "response_answer": (result.get("answer") or "")[:500],
        }

        # 1) Persist to SQLite (best-effort).
        await self._persist(row)

        # 2) Push into the in-memory ring buffer.
        async with self._lock:
            self._buffer.append(dict(row))

        return ctx.trace_id

    def flush(self) -> None:
        """No-op for LocalTracer — writes are synchronous on end_trace."""
        return None

    # ── Query surface used by the /api/traces endpoints ─────────────────────

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent ``limit`` traces, newest first.

        Falls back to a DB query when the in-memory buffer is smaller than
        the requested limit (e.g. right after a process restart).
        """
        async with self._lock:
            buf = list(self._buffer)
        buf.reverse()  # newest first
        if len(buf) >= limit:
            return [_summary(r) for r in buf[:limit]]

        # Buffer too small — query the DB.
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                stmt = (
                    select(traces_table)
                    .order_by(traces_table.c.created_at.desc())
                    .limit(limit)
                )
                res = await conn.execute(stmt)
                rows = [dict(r._mapping) for r in res.fetchall()]
        except Exception:  # noqa: BLE001
            logger.warning("list_recent DB query failed", exc_info=True)
            rows = []
        # Merge with whatever we had in memory (memory may have fresher rows
        # not yet flushed — though for LocalTracer that's not the case).
        seen_ids = {r["id"] for r in rows}
        for r in buf:
            if r["id"] not in seen_ids:
                rows.insert(0, r)
                seen_ids.add(r["id"])
        return [_summary(r) for r in rows[:limit]]

    async def get(self, trace_id: str) -> dict[str, Any] | None:
        """Return the full detail row for one trace, or None if not found."""
        # Check the ring buffer first (fast path).
        async with self._lock:
            for r in self._buffer:
                if r["id"] == trace_id:
                    return _detail(r)
        # Fallback to the DB.
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                stmt = select(traces_table).where(traces_table.c.id == trace_id)
                res = await conn.execute(stmt)
                row = res.fetchone()
                if row is None:
                    return None
                return _detail(dict(row._mapping))
        except Exception:  # noqa: BLE001
            logger.warning("get DB query failed", exc_info=True)
            return None

    # ── Internals ───────────────────────────────────────────────────────────

    async def _persist(self, row: dict[str, Any]) -> None:
        """INSERT the trace row into the ``traces`` table (best-effort)."""
        try:
            engine = get_engine()
            async with engine.begin() as conn:
                await conn.execute(traces_table.insert().values(**row))
        except Exception:  # noqa: BLE001
            logger.warning(
                "traces INSERT failed for id=%s — trace still in memory ring buffer",
                row.get("id"),
                exc_info=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Row -> API shaping helpers
# ─────────────────────────────────────────────────────────────────────────────


_SUMMARY_FIELDS = (
    "id",
    "created_at",
    "user_message",
    "intent",
    "sql_valid",
    "scope_applied",
    "refused",
    "latency_ms",
    "tokens_in",
    "tokens_out",
    "cost_usd",
)


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    """Project a stored row down to the list-endpoint fields."""
    return {k: row.get(k) for k in _SUMMARY_FIELDS}


def _detail(row: dict[str, Any]) -> dict[str, Any]:
    """Return the full row, parsing the JSON columns back to lists."""
    out = dict(row)
    for k in ("tool_calls", "steps"):
        v = out.get(k)
        if isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except Exception:  # noqa: BLE001
                out[k] = []
        elif v is None:
            out[k] = []
    return out
