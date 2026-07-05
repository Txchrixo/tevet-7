"""Tests for Phase B6 — Monitoring."""
from __future__ import annotations
import json, sys
from pathlib import Path
_AGENTIC = Path(__file__).resolve().parent.parent
if str(_AGENTIC) not in sys.path: sys.path.insert(0, str(_AGENTIC))
import pytest
from app.monitoring import capture_exception, capture_message, _init_sentry

def test_capture_exception_logs_json(capsys):
    capture_exception(ValueError("test"), context={"user_id": 42})
    captured = capsys.readouterr()
    entry = json.loads(captured.err.strip().split("\n")[-1])
    assert entry["error_type"] == "ValueError"
    assert entry["context"]["user_id"] == 42

def test_capture_message_logs_info(capsys):
    capture_message("test msg", level="info")
    entry = json.loads(capsys.readouterr().err.strip().split("\n")[-1])
    assert entry["level"] == "info"

def test_init_sentry_no_dsn(monkeypatch):
    import app.monitoring as mod
    mod._sentry_initialized = False
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    _init_sentry()
    assert mod._sentry_initialized is False

def test_never_crashes(capsys):
    capture_exception(Exception("test"), context={"obj": object()})
    assert capsys.readouterr().err
