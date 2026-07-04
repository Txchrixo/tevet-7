"""Optional Langfuse adapter.

Only imported lazily by ``factory.py`` when the ``langfuse`` package is
installed AND the env keys are configured. Phase 6c keeps the demo
self-contained — this module is here for production deployments.

The adapter delegates persistence to Langfuse Cloud AND ALSO writes to the
local ``traces`` table (via composition with ``LocalTracer``) so the admin
console's "recent conversations" view keeps working even if Langfuse is
briefly unreachable.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from app.tracing.local import LocalTracer, TraceContext

logger = logging.getLogger("opspilot.tracing.langfuse")


class LangfuseTracer:
    """Layered tracer: Langfuse Cloud + local SQLite (best-effort)."""

    def __init__(self) -> None:
        from app.config import get_settings
        from langfuse import Langfuse  # type: ignore[import-not-found]

        s = get_settings()
        self._client = Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            host=s.langfuse_host,
        )
        self._local = LocalTracer()

    @asynccontextmanager
    async def trace(self, metadata: dict[str, Any]) -> AsyncIterator[TraceContext]:
        """Open a Langfuse trace + a local trace in parallel."""
        trace_id = metadata.get("trace_id") or uuid.uuid4().hex
        lf_trace = self._client.trace(
            id=trace_id,
            name=metadata.get("name", "chat"),
            metadata={
                "tenant_id": metadata.get("tenant_id"),
                "user_id": metadata.get("user_id"),
            },
        )
        # Use the local tracer for the durable row.
        async with self._local.trace({**metadata, "trace_id": trace_id,
                                       "trace_url": lf_trace.get_trace_url()}) as ctx:
            try:
                yield ctx
            finally:
                # Flush the Langfuse client (best-effort).
                try:
                    self._client.flush()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Langfuse flush failed: %s", exc)
