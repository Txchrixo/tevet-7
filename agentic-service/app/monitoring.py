"""Monitoring — structured error logging + Sentry-ready integration."""
from __future__ import annotations
import json, logging, os, sys, traceback
from datetime import datetime, timezone
from typing import Any
logger = logging.getLogger("tevet7.monitoring")
_sentry_initialized = False

def _init_sentry() -> None:
    global _sentry_initialized
    if _sentry_initialized: return
    dsn = os.environ.get("SENTRY_DSN", "")
    if not dsn: return
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=dsn, environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
                         traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
                         send_default_pii=False)
        _sentry_initialized = True
    except Exception: pass

def capture_exception(exc: Exception, context: dict[str, Any] | None = None, level: str = "error") -> None:
    _init_sentry()
    context = context or {}
    log_entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": level,
                 "error_type": type(exc).__name__, "error_message": str(exc),
                 "stacktrace": traceback.format_exc(), "context": context}
    print(json.dumps(log_entry, ensure_ascii=False, default=str), file=sys.stderr, flush=True)
    if _sentry_initialized:
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                for k, v in context.items(): scope.set_extra(k, v)
                sentry_sdk.capture_exception(exc, level=level)
        except Exception: pass

def capture_message(message: str, level: str = "info", context: dict[str, Any] | None = None) -> None:
    _init_sentry()
    context = context or {}
    log_entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": level,
                 "message": message, "context": context}
    print(json.dumps(log_entry, ensure_ascii=False, default=str), file=sys.stderr, flush=True)
    if _sentry_initialized:
        try:
            import sentry_sdk
            sentry_sdk.capture_message(message, level=level)
        except Exception: pass
