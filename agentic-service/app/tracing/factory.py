"""Tracer factory — returns the right tracer based on environment.

Selection rule
--------------

* If ``LANGFUSE_PUBLIC_KEY`` **and** ``LANGFUSE_SECRET_KEY`` are both set to
  non-default values AND the ``langfuse`` package is importable, return a
  :class:`LangfuseTracer`.
* Otherwise return a :class:`LocalTracer` (default, dev mode).

The result is cached as a process-wide singleton — every ``/api/chat``
request gets the same tracer instance, so the in-memory ring buffer is
shared. Reset with ``get_tracer.cache_clear()`` in tests.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import get_settings
from app.tracing.base import Span, TraceContext, Tracer
from app.tracing.local import LocalTracer

logger = logging.getLogger("tevet7.tracing.factory")

# Placeholder values that mean "not configured" (matches .env.example).
_PLACEHOLDER_KEYS = {"pk-lf-replace-me", "sk-lf-replace-me", "", None}


@lru_cache
def get_tracer() -> Tracer:
    """Return the process-wide tracer singleton.

    Cached so the in-memory ring buffer is shared across requests. Tests
    can reset via ``get_tracer.cache_clear()``.
    """
    settings = get_settings()
    pub = settings.langfuse_public_key
    sec = settings.langfuse_secret_key
    if pub in _PLACEHOLDER_KEYS or sec in _PLACEHOLDER_KEYS:
        logger.info("Tracer=LocalTracer (langfuse keys not configured)")
        return LocalTracer()

    # Try to import langfuse — if it's missing, fall back to LocalTracer.
    try:
        from langfuse import Langfuse  # noqa: F401  — import-probe
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "langfuse keys set but langfuse package not importable (%s) "
            "— falling back to LocalTracer",
            exc,
        )
        return LocalTracer()

    from app.tracing.langfuse_tracer import LangfuseTracer

    logger.info(
        "Tracer=LangfuseTracer (host=%s, public_key=%s...)",
        settings.langfuse_host,
        (pub or "")[:8],
    )
    return LangfuseTracer(
        public_key=pub,
        secret_key=sec,
        host=settings.langfuse_host,
    )


__all__ = [
    "Tracer",
    "TraceContext",
    "Span",
    "get_tracer",
]
