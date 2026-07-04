"""FastAPI dependencies for auth (Phase 6a).

Two dependencies
----------------

* :func:`get_current_user` — returns the user dict. Used by endpoints that
  need to know WHO is calling but don't need the tenant context (e.g.
  ``GET /api/auth/me``, ``POST /api/tenants``).

* :func:`get_tenant_context` — returns a :class:`TenantContext` carrying
  the FULL identity (user_id + email + tenant_id + role + producer_id).
  Used by endpoints that scope data per tenant (``POST /api/chat`` with a
  JWT, ``GET /api/tenants/mine``, …).

Both read the ``Authorization: Bearer <jwt>`` header. Missing/invalid →
HTTP 401.

Why a separate ``TenantContext`` rather than reusing the user dict?
------------------------------------------------------------------

Because the tenant context is the contract the HTTP layer passes to the
orchestrator. The orchestrator doesn't care about the user — it only
needs ``role``, ``producer_id``, ``tenant_id``. Keeping these in a
dedicated dataclass makes the boundary explicit: ``user`` = identity
for the auth/admin surface, ``TenantContext`` = identity for the agentic
core.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status
from jose import JWTError

from app.auth.jwt import verify_token
from app.auth.service import get_user_by_id

logger = logging.getLogger("tevet7.auth.deps")


@dataclass
class TenantContext:
    """The identity contract the HTTP layer passes to the agentic core.

    Fields
    ------
    user_id : int
        The authenticated user's id (from the JWT ``sub`` claim).
    email : str
        For audit / display only.
    tenant_id : str | None
        The active tenant (e.g. ``"dp"``). ``None`` if the user has no
        memberships yet (a fresh signup) — in that case the chat endpoint
        should refuse with 403 "no active tenant".
    role : str | None
        ``"producer"`` | ``"admin"`` | ``"customer"``. ``None`` for fresh
        signups.
    producer_id : int | None
        The row-level scope value. ``None`` for admins (no scoping) and
        for fresh signups.
    is_demo : bool
        True for marie/pierre/admin demo accounts — lets the frontend
        show a "demo account" badge.
    """

    user_id: int
    email: str
    tenant_id: str | None
    role: str | None
    producer_id: int | None
    is_demo: bool = False


def _extract_bearer_token(request: Request) -> str | None:
    """Return the JWT from the Authorization header, or None.

    Accepts ``Authorization: Bearer <jwt>`` (case-insensitive scheme).
    Returns None if the header is missing, malformed, or uses a
    non-Bearer scheme — the caller decides whether to raise 401 or fall
    back to a legacy auth path.
    """
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


async def get_current_user(request: Request) -> dict[str, Any]:
    """FastAPI dependency: return the current user dict (or 401).

    Verifies the JWT, looks up the user in the DB, returns the dict
    (``{id, email, name, created_at}``). Raises 401 if the token is
    missing, malformed, expired, or if the user no longer exists.
    """
    token = _extract_bearer_token(request)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing or not Bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = verify_token(token)
    except JWTError as exc:
        logger.warning("JWT verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    sub = claims.get("sub")
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token missing 'sub' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = int(sub)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"token 'sub' claim is not an int: {sub!r}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user = await get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"user {user_id} no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_tenant_context(request: Request) -> TenantContext:
    """FastAPI dependency: return the :class:`TenantContext` (or 401).

    Same as :func:`get_current_user` but returns the full identity
    (tenant_id + role + producer_id) extracted from the JWT — no DB
    lookup needed. Use this for endpoints that scope data per tenant.
    """
    token = _extract_bearer_token(request)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing or not Bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = verify_token(token)
    except JWTError as exc:
        logger.warning("JWT verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    sub = claims.get("sub")
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token missing 'sub' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = int(sub)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"token 'sub' claim is not an int: {sub!r}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    email = claims.get("email") or ""
    tenant_id = claims.get("tenant_id")
    role = claims.get("role")
    # producer_id may come through as None or as a JSON number — coerce.
    raw_pid = claims.get("producer_id")
    producer_id = int(raw_pid) if raw_pid is not None else None
    is_demo = bool(claims.get("is_demo", False))
    return TenantContext(
        user_id=user_id,
        email=email,
        tenant_id=tenant_id,
        role=role,
        producer_id=producer_id,
        is_demo=is_demo,
    )


def try_get_tenant_context(request: Request) -> TenantContext | None:
    """Non-async variant: return the TenantContext if a valid JWT is
    present, else ``None`` (no raise).

    Used by the dual-mode endpoints (chat / documents / approvals) that
    fall back to body identity when no JWT is supplied. This is the
    bridge between the new auth path and the legacy eval path.

    IMPORTANT: this does NOT verify the user still exists in the DB —
    it only verifies the JWT signature + expiry. That's intentional: the
    dual-mode endpoints are read-mostly and the orchestrator doesn't
    need a DB lookup per request.
    """
    token = _extract_bearer_token(request)
    if token is None:
        return None
    try:
        claims = verify_token(token)
    except JWTError as exc:
        logger.debug("try_get_tenant_context: invalid JWT (%s) — ignoring", exc)
        return None
    sub = claims.get("sub")
    if sub is None:
        return None
    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        return None
    raw_pid = claims.get("producer_id")
    return TenantContext(
        user_id=user_id,
        email=claims.get("email") or "",
        tenant_id=claims.get("tenant_id"),
        role=claims.get("role"),
        producer_id=int(raw_pid) if raw_pid is not None else None,
        is_demo=bool(claims.get("is_demo", False)),
    )
