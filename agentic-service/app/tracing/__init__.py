"""Tracing layer for Tevet-7.

Public surface
--------------

    from app.tracing import Tracer, TraceContext, get_tracer

* :class:`Tracer` - Protocol every tracer satisfies (Local, Langfuse, …).
* :class:`TraceContext` - per-request handle.
* :func:`get_tracer` - factory returning the process-wide singleton.

The concrete tracers live in:

* :mod:`app.tracing.local` - writes to SQLite ``traces`` table (default).
* :mod:`app.tracing.langfuse_tracer` - also ships to Langfuse (when keys set).
"""

from __future__ import annotations

from app.tracing.base import Span, TraceContext, Tracer
from app.tracing.factory import get_tracer

__all__ = ["Tracer", "TraceContext", "Span", "get_tracer"]
