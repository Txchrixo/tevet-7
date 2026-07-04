"""JWT utilities for Tevet-7 (Phase 6a).

Token shape
-----------

``create_access_token`` accepts a dict with the following keys (all
optional except ``sub`` — the user id as a string) and produces a signed
JWT::

    {
        "sub": "<user_id>",          # str(user.id) — required
        "email": "<user email>",      # for display only
        "tenant_id": "<tenant id>",   # active tenant (e.g. "dp")
        "role": "producer|admin|customer",
        "producer_id": 42 | None,    # row-level scope value (NULL for admin)
        "is_demo": True | False,     # demo accounts (marie/pierre/admin)
    }

``verify_token`` returns the decoded claims dict on success and raises
``jose.JWTError`` (or ``JWTClaimsError``) on any failure (bad signature,
expired, malformed). Callers MUST catch ``jose.JWTError`` and surface a
401 to the client.

The token is signed with HS256 + ``JWT_SECRET`` from settings. The
default expiry is 7 days (long enough for the demo, short enough to be
rotated on a real deployment — production should use 1-2 hours + a
refresh-token flow, which we'll add in Phase 6b).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt
from passlib.context import CryptContext

from app.config import get_settings

# bcrypt context — bcrypt is the recommended password hash for production
# (Argon2 would be even better but bcrypt is universally available).
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Default JWT expiry — 7 days. Tuned for the demo (the frontend stores the
# token in localStorage and we don't want users to be logged out mid-demo).
# Production should drop this to 1-2h and add a refresh-token endpoint.
_DEFAULT_EXPIRY = timedelta(days=7)


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of ``plain``.

    The hash includes the salt + cost factor so ``verify_password`` doesn't
    need any extra parameters. The default cost factor (12) gives ~250ms
    per hash on a modern CPU — acceptable for signup/login but don't call
    this in a hot loop.
    """
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if ``plain`` matches ``hashed`` (bcrypt).

    Constant-time comparison is handled by bcrypt internally — no need for
    ``hmac.compare_digest`` here. Returns False on any mismatch (wrong
    password, malformed hash, unknown scheme) rather than raising.
    """
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:  # noqa: BLE001 — passlib raises on malformed hash
        return False


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Return a signed JWT encoding ``data``.

    ``data`` is copied then augmented with ``exp`` (UTC expiry). The
    caller's ``data`` MUST include ``sub`` (the user id as a string); all
    other claims (``email``, ``tenant_id``, ``role``, ``producer_id``,
    ``is_demo``) are optional but the HTTP layer expects them on every
    token issued via ``/api/auth/login`` or ``/api/auth/signup``.
    """
    settings = get_settings()
    to_encode = dict(data)
    expire = datetime.now(timezone.utc) + (expires_delta or _DEFAULT_EXPIRY)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> dict[str, Any]:
    """Return the decoded claims dict, or raise ``jose.JWTError``.

    Callers should catch ``jose.JWTError`` (the base class — covers
    signature errors, expiry, malformed tokens) and surface a 401. We
    deliberately don't swallow the exception here so the dependency
    layer (``get_current_user``) can log the specific failure mode.
    """
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
