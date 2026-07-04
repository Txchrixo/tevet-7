"""Auth HTTP routes for Tevet-7 (Phase 6a).

Endpoints
=========

- ``POST /api/auth/signup`` — body ``{email, password, name}`` →
  ``{user: {id, email, name}, token}``.
- ``POST /api/auth/login`` — body ``{email, password}`` →
  ``{user: {id, email, name}, token}``. The token's claims include the
  user's active membership (tenant_id, role, producer_id) — set by the
  tenant module's ``set_active_membership``.
- ``GET  /api/auth/me`` — ``Authorization: Bearer <jwt>`` → returns the
  current user + their memberships (so the frontend can render the
  tenant switcher).

Tracing
=======

Both ``signup`` and ``login`` open a trace + a span so the operator can
see auth activity in Langfuse alongside the chat traces. The span name
is ``auth_signup`` / ``auth_login`` respectively.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.auth.service import list_user_memberships, login, signup
from app.tracing import get_tracer

logger = logging.getLogger("tevet7.auth.routes")

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────────────────────


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=200, description="User email (unique).")
    password: str = Field(..., min_length=8, max_length=200, description="Plaintext password (≥ 8 chars).")
    name: str = Field(..., min_length=1, max_length=200, description="Display name.")


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=200, description="User email.")
    password: str = Field(..., min_length=1, max_length=200, description="Plaintext password.")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _start_auth_span(span_name: str, **metadata: Any) -> tuple[Any, Any, Any]:
    """Open a trace + span for an auth event. Returns ``(tracer, ctx, span)``.

    The first parameter is named ``span_name`` (not ``name``) so callers
    can pass ``name="Marie Dubois"`` as metadata without colliding.
    """
    tracer = get_tracer()
    ctx = tracer.start_trace(span_name, dict(metadata))
    span = tracer.start_span(ctx, span_name, **metadata)
    return tracer, ctx, span


async def _end_auth_trace(
    tracer: Any, ctx: Any, span: Any, t0: float, *,
    status_: str = "ok", error: str | None = None, extra: dict[str, Any] | None = None,
) -> None:
    """Finalise the trace opened by ``_start_auth_span``."""
    latency_ms = int((time.monotonic() - t0) * 1000)
    metadata = {"latency_ms": latency_ms}
    if extra:
        metadata.update(extra)
    if error:
        metadata["error"] = error
    tracer.end_span(ctx, span, status=status_, **metadata)
    await tracer.end_trace(
        ctx,
        {
            "answer": "" if error else f"auth: {span.name}",
            "sql": None,
            "intent": span.name,
            "refused": bool(error),
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": latency_ms,
            "tool_calls": [{"name": span.name, "latency_ms": latency_ms, "success": not error}],
            "steps": [],
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/auth/signup
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/auth/signup")
async def signup_endpoint(body: SignupRequest) -> dict[str, Any]:
    """Create a new user and return a JWT.

    Returns 409 if the email is already registered. The JWT issued here
    has ``tenant_id=None``, ``role=None``, ``producer_id=None`` because a
    fresh signup has no memberships yet — the client must create or
    activate a tenant (``POST /api/tenants`` or
    ``POST /api/tenants/{id}/activate``) to obtain a token with a real
    tenant context.
    """
    tracer, ctx, span = _start_auth_span("auth_signup", email=body.email, name=body.name)
    t0 = time.monotonic()
    try:
        from app.auth.jwt import create_access_token
        user = await signup(body.email, body.password, body.name)
        # Fresh signup has no membership — issue a token with null tenant
        # context. The client must create/activate a tenant to get a
        # token with real scope.
        token = create_access_token({
            "sub": str(user["id"]),
            "email": user["email"],
            "tenant_id": None,
            "role": None,
            "producer_id": None,
            "is_demo": False,
        })
        await _end_auth_trace(
            tracer, ctx, span, t0, status_="ok",
            extra={"user_id": user["id"], "issued_token": True},
        )
        return {"user": user, "token": token}
    except ValueError as exc:
        # Email already registered OR weak password OR missing fields.
        await _end_auth_trace(
            tracer, ctx, span, t0, status_="error", error=str(exc),
        )
        # Distinguish "already registered" (409) from validation (400).
        detail = str(exc)
        if "already registered" in detail:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=detail
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=detail
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("signup_endpoint failed")
        await _end_auth_trace(
            tracer, ctx, span, t0, status_="error", error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"signup failed: {exc}",
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/auth/login
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/auth/login")
async def login_endpoint(body: LoginRequest) -> dict[str, Any]:
    """Verify credentials and return a JWT with the user's active tenant.

    Returns 401 on wrong email/password. The JWT's claims include
    ``tenant_id``, ``role``, ``producer_id`` from the user's active
    membership — set by ``POST /api/tenants/{id}/activate``.
    """
    tracer, ctx, span = _start_auth_span("auth_login", email=body.email)
    t0 = time.monotonic()
    try:
        user, token = await login(body.email, body.password)
        await _end_auth_trace(
            tracer, ctx, span, t0, status_="ok",
            extra={"user_id": user["id"], "issued_token": True},
        )
        return {"user": user, "token": token}
    except ValueError as exc:
        # Wrong email or wrong password — same message to avoid
        # user-enumeration leak.
        await _end_auth_trace(
            tracer, ctx, span, t0, status_="error", error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("login_endpoint failed")
        await _end_auth_trace(
            tracer, ctx, span, t0, status_="error", error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"login failed: {exc}",
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/auth/me
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/auth/me")
async def me_endpoint(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the current user + their memberships.

    Used by the frontend on app load to:
      1. Validate the stored JWT (401 → redirect to /login).
      2. Render the tenant switcher (memberships list).
      3. Pre-fill the chat identity (active membership).
    """
    memberships = await list_user_memberships(current_user["id"])
    return {"user": current_user, "memberships": memberships}
