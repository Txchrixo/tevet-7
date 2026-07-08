"""Tests for the production hardening layer.

Covers:
- ``Settings.validate_production_settings`` - fail-fast boot guards.
- ``require_flag`` - feature-flag kill switches (503 when off).
- ``SlidingWindowRateLimiter`` - the shared auth/chat rate limiter.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.rate_limit import SlidingWindowRateLimiter
from app.config import Settings, get_settings
from app.feature_flags import require_flag


# ─────────────────────────────────────────────────────────────────────────────
# 1. Production boot guards
# ─────────────────────────────────────────────────────────────────────────────

_PROD_SAFE = dict(
    env="production",
    jwt_secret="x" * 44,  # openssl rand -base64 32 output length
    cors_origins="https://app.example.com",
    enable_demo_seed=False,
)


def test_guards_pass_on_safe_production_config() -> None:
    assert Settings(**_PROD_SAFE).validate_production_settings() == []


def test_guards_ignore_development() -> None:
    """Dev keeps the permissive defaults - guards only bite in production."""
    assert Settings(env="development").validate_production_settings() == []


def test_guards_reject_default_jwt_secret() -> None:
    cfg = {**_PROD_SAFE, "jwt_secret": "replace-me-with-openssl-rand-base64-32"}
    errors = Settings(**cfg).validate_production_settings()
    assert any("JWT_SECRET" in e for e in errors)


def test_guards_reject_short_jwt_secret() -> None:
    cfg = {**_PROD_SAFE, "jwt_secret": "short"}
    errors = Settings(**cfg).validate_production_settings()
    assert any("32 characters" in e for e in errors)


def test_guards_reject_wildcard_cors() -> None:
    cfg = {**_PROD_SAFE, "cors_origins": "*"}
    errors = Settings(**cfg).validate_production_settings()
    assert any("CORS_ORIGINS" in e for e in errors)


def test_guards_reject_demo_seed_in_production() -> None:
    cfg = {**_PROD_SAFE, "enable_demo_seed": True}
    errors = Settings(**cfg).validate_production_settings()
    assert any("ENABLE_DEMO_SEED" in e for e in errors)


def test_guards_report_every_error_at_once() -> None:
    """The operator gets the full list in one boot attempt, not one by one."""
    errors = Settings(env="production").validate_production_settings()
    assert len(errors) >= 3


# ─────────────────────────────────────────────────────────────────────────────
# 2. Feature-flag kill switches
# ─────────────────────────────────────────────────────────────────────────────


def _flag_app(**settings_overrides) -> TestClient:
    """Tiny app with one endpoint gated by enable_rag."""
    app = FastAPI()

    @app.get("/gated", dependencies=[require_flag("enable_rag")])
    async def gated() -> dict:
        return {"ok": True}

    app.dependency_overrides[get_settings] = lambda: Settings(**settings_overrides)
    return TestClient(app)


def test_flag_on_lets_request_through() -> None:
    client = _flag_app(enable_rag=True)
    assert client.get("/gated").status_code == 200


def test_flag_off_returns_503() -> None:
    client = _flag_app(enable_rag=False)
    resp = client.get("/gated")
    assert resp.status_code == 503
    assert "enable_rag" in resp.json()["detail"]


def test_unknown_flag_raises_at_wiring_time() -> None:
    """A typo in the flag name must fail at import/wiring, not silently
    gate nothing."""
    with pytest.raises(ValueError, match="unknown feature flag"):
        require_flag("enable_typo")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Sliding-window rate limiter
# ─────────────────────────────────────────────────────────────────────────────


def test_limiter_allows_up_to_max_events() -> None:
    limiter = SlidingWindowRateLimiter(max_events=3, window_seconds=60)
    assert all(limiter.check("t1")[0] for _ in range(3))


def test_limiter_denies_after_max_and_reports_retry_after() -> None:
    limiter = SlidingWindowRateLimiter(max_events=2, window_seconds=60)
    limiter.check("t1")
    limiter.check("t1")
    allowed, retry_after = limiter.check("t1")
    assert allowed is False
    assert 0 < retry_after <= 60


def test_limiter_keys_are_independent() -> None:
    limiter = SlidingWindowRateLimiter(max_events=1, window_seconds=60)
    assert limiter.check("tenant-a")[0] is True
    assert limiter.check("tenant-b")[0] is True
    assert limiter.check("tenant-a")[0] is False


def test_limiter_window_slides(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = SlidingWindowRateLimiter(max_events=1, window_seconds=10)
    clock = {"now": 1000.0}
    monkeypatch.setattr("app.auth.rate_limit.time.monotonic", lambda: clock["now"])
    assert limiter.check("t1")[0] is True
    assert limiter.check("t1")[0] is False
    clock["now"] += 10.1  # past the window - the old event expired
    assert limiter.check("t1")[0] is True


def test_limiter_rejects_nonsense_construction() -> None:
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_events=0, window_seconds=60)
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_events=5, window_seconds=0)
