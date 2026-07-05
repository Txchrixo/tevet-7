"""Auth business logic for Tevet-7 (Phase 6a).

This module owns the user-management CRUD that backs the auth HTTP routes
(``POST /api/auth/signup``, ``POST /api/auth/login``, ``GET /api/auth/me``).
It uses the SAME async engine as the rest of the service
(``app.db_seed.get_engine()``) — there is no separate "auth DB". The
``users`` table is created by ``init_db()`` alongside the business tables
(see ``app/db_seed.py``).

Why a separate module (not inline in ``routes.py``)?
----------------------------------------------------

So the tenant module (``app/tenants/service.py``) can call
``get_user_by_email`` / ``get_user_by_id`` without going through the HTTP
layer. This keeps the dependency direction clean: ``tenants`` → ``auth``
→ ``db_seed``, with no circular imports.

Token issuance
--------------

``login`` returns ``(user_row, jwt_token)``. The token's claims include
the user's ACTIVE membership (tenant_id + role + producer_id) — set by
``app.tenants.service.set_active_membership``. A fresh signup has no
memberships yet, so ``signup`` returns a token with ``tenant_id=None``,
``role=None``, ``producer_id=None`` — the client must create or activate
a tenant before calling ``/api/chat`` with the JWT.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Row

from app.auth.jwt import create_access_token, hash_password, verify_password
from app.db_seed import get_engine, tenant_memberships, users

logger = logging.getLogger("tevet7.auth.service")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _row_to_user(row: Row) -> dict[str, Any]:
    """Project a SQLAlchemy Row into a JSON-safe user dict.

    Used by every public function so the HTTP layer never has to deal
    with SQLAlchemy Row objects directly.
    """
    ca = row.created_at
    return {
        "id": int(row.id),
        "email": row.email,
        "name": row.name,
        "is_platform_owner": bool(getattr(row, "is_platform_owner", False)),
        "created_at": ca.isoformat() if ca is not None else None,
    }


async def _get_active_membership(user_id: int) -> dict[str, Any] | None:
    """Return the user's active membership, or None.

    A user has at most one ``is_active=True`` membership at a time
    (enforced by ``set_active_membership``). If they have none, we look
    for any membership (demo users are pre-seeded with one). If still
    none, returns None — the caller issues a token with null tenant
    context and the client must create/activate a tenant.
    """
    engine = get_engine()
    async with engine.connect() as conn:
        r = await conn.execute(
            select(tenant_memberships).where(
                (tenant_memberships.c.user_id == user_id)
                & (tenant_memberships.c.is_active.is_(True))
            )
        )
        row = r.fetchone()
        if row is None:
            # Fall back to the first membership (any tenant, any status).
            r = await conn.execute(
                select(tenant_memberships).where(
                    tenant_memberships.c.user_id == user_id
                )
            )
            row = r.fetchone()
        if row is None:
            return None
        return {
            "tenant_id": row.tenant_id,
            "role": row.role,
            "producer_id": row.producer_id,
            "is_demo": False,  # filled by caller from the tenant row if needed
        }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


async def signup(email: str, password: str, name: str) -> dict[str, Any]:
    """Create a new user. Raises ``ValueError`` if email is already taken.

    Returns the user dict (without password_hash). The caller (the HTTP
    route) wraps this in a try/except and surfaces 409 on duplicate email.
    """
    email = (email or "").strip().lower()
    if not email or not password or not name:
        raise ValueError("email, password, and name are all required")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")

    engine = get_engine()
    # Check email uniqueness first so we can raise a clean ValueError
    # rather than relying on the UNIQUE constraint (which would surface
    # as a generic IntegrityError).
    async with engine.connect() as conn:
        r = await conn.execute(select(users.c.id).where(users.c.email == email))
        if r.fetchone() is not None:
            raise ValueError(f"email {email!r} is already registered")

    password_hash = hash_password(password)
    async with engine.begin() as conn:
        result = await conn.execute(
            users.insert()
            .values(
                email=email,
                name=name,
                password_hash=password_hash,
                created_at=datetime.utcnow(),
            )
            .returning(users.c.id, users.c.email, users.c.name, users.c.created_at)
        )
        row = result.fetchone()
    logger.info("signup — user created id=%d email=%s name=%s", row.id, row.email, row.name)
    return _row_to_user(row)


async def login(email: str, password: str) -> tuple[dict[str, Any], str]:
    """Verify credentials and return ``(user_dict, jwt_token)``.

    Raises ``ValueError`` on wrong email/password. The token's claims
    include the user's active membership (tenant_id, role, producer_id)
    so the HTTP layer (chat, documents, approvals) can extract identity
    from the JWT without a DB lookup.
    """
    email = (email or "").strip().lower()
    user = await get_user_by_email(email)
    if user is None:
        # Same error message for "user not found" and "wrong password" so
        # we don't leak which emails are registered (user enumeration).
        raise ValueError("invalid email or password")
    # Fetch the raw row (with password_hash) for verification.
    engine = get_engine()
    async with engine.connect() as conn:
        r = await conn.execute(select(users).where(users.c.id == user["id"]))
        full_row = r.fetchone()
    if full_row is None or not verify_password(password, full_row.password_hash):
        raise ValueError("invalid email or password")

    membership = await _get_active_membership(user["id"])
    # Look up is_demo on the tenant (so demo users get is_demo=true in
    # the JWT — the frontend uses this to display a "demo account" badge).
    is_demo = False
    if membership is not None:
        from app.db_seed import tenants as tenants_table
        async with engine.connect() as conn:
            r = await conn.execute(
                select(tenants_table.c.is_demo).where(
                    tenants_table.c.id == membership["tenant_id"]
                )
            )
            trow = r.fetchone()
            if trow is not None:
                is_demo = bool(trow.is_demo)

    token = create_access_token({
        "sub": str(user["id"]),
        "email": user["email"],
        "tenant_id": membership["tenant_id"] if membership else None,
        "role": membership["role"] if membership else None,
        "producer_id": membership["producer_id"] if membership else None,
        "is_demo": is_demo,
    })
    # Phase B2: also create a refresh token (30d) so the frontend can
    # auto-refresh when the access token expires (2h).
    from app.auth.jwt import create_refresh_token
    refresh_token = create_refresh_token({
        "sub": str(user["id"]),
        "email": user["email"],
        "tenant_id": membership["tenant_id"] if membership else None,
        "role": membership["role"] if membership else None,
        "producer_id": membership["producer_id"] if membership else None,
        "is_demo": is_demo,
    })
    logger.info("login — user id=%d email=%s tenant=%s role=%s",
                user["id"], user["email"],
                membership["tenant_id"] if membership else None,
                membership["role"] if membership else None)
    return user, token, refresh_token


async def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Return the user dict for ``email`` (case-insensitive), or None."""
    email = (email or "").strip().lower()
    engine = get_engine()
    async with engine.connect() as conn:
        r = await conn.execute(select(users).where(users.c.email == email))
        row = r.fetchone()
    if row is None:
        return None
    return _row_to_user(row)


async def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Return the user dict for ``user_id``, or None."""
    engine = get_engine()
    async with engine.connect() as conn:
        r = await conn.execute(select(users).where(users.c.id == int(user_id)))
        row = r.fetchone()
    if row is None:
        return None
    return _row_to_user(row)


async def list_user_memberships(user_id: int) -> list[dict[str, Any]]:
    """Return all memberships for ``user_id``, joined with tenant info + onboarded flag.

    Used by ``GET /api/auth/me`` so the frontend can render the tenant
    switcher AND gate on onboarding. Each item carries ``{tenant_id, name,
    slug, role, producer_id, is_demo, is_active, onboarded}``.

    The ``onboarded`` flag comes from the ``tenant_configs`` table (LEFT JOIN
    — a freshly created tenant may not have a config row yet, in which case
    ``onboarded`` defaults to ``False``).
    """
    from app.db_seed import tenants as tenants_table, tenant_configs
    engine = get_engine()
    async with engine.connect() as conn:
        r = await conn.execute(
            select(
                tenant_memberships.c.id,
                tenant_memberships.c.tenant_id,
                tenant_memberships.c.role,
                tenant_memberships.c.producer_id,
                tenant_memberships.c.is_active,
                tenants_table.c.name.label("tenant_name"),
                tenants_table.c.slug.label("tenant_slug"),
                tenants_table.c.is_demo.label("tenant_is_demo"),
                tenant_configs.c.onboarded.label("tenant_onboarded"),
            )
            .select_from(
                tenant_memberships.join(
                    tenants_table,
                    tenants_table.c.id == tenant_memberships.c.tenant_id,
                ).outerjoin(
                    tenant_configs,
                    tenant_configs.c.tenant_id == tenants_table.c.id,
                )
            )
            .where(tenant_memberships.c.user_id == int(user_id))
            .order_by(tenant_memberships.c.created_at.asc())
        )
        items = []
        for row in r.fetchall():
            items.append({
                "tenant_id": row.tenant_id,
                "name": row.tenant_name,
                "slug": row.tenant_slug,
                "role": row.role,
                "producer_id": row.producer_id,
                "is_demo": bool(row.tenant_is_demo),
                "is_active": bool(row.is_active),
                # onboarded: False if no config row (fresh tenant), else the stored value.
                "onboarded": bool(row.tenant_onboarded) if row.tenant_onboarded is not None else False,
            })
    return items
