"""Tenant business logic for Tevet-7 (Phase 6a).

Tables (defined in ``app.db_seed``)
-----------------------------------

* ``users`` - id, email, name, password_hash, created_at.
* ``tenants`` - id (str, e.g. ``"dp"``), name, slug (unique), is_demo,
  created_at, owner_user_id (FK→users.id).
* ``tenant_memberships`` - id, user_id, tenant_id, role, producer_id,
  is_active, created_at. UNIQUE(user_id, tenant_id). A user has at most
  one ``is_active=True`` row at a time (enforced by
  ``set_active_membership`` which flips the others to False first).

Public functions
----------------

* :func:`create_tenant` - create a tenant + make the owner an admin
  member. Returns the tenant row.
* :func:`list_user_tenants` - the tenants the user belongs to (with role
  + producer_id + is_active flags).
* :func:`get_tenant` - single tenant lookup by id.
* :func:`add_tenant_member` - add a user to a tenant with a given role.
* :func:`set_active_membership` - flip the user's active membership,
  return a NEW JWT with the updated tenant context (the frontend stores
  this JWT in place of the old one).
* :func:`seed_demo_tenant` - idempotent: create the ``dp`` demo tenant +
  3 demo users (marie/pierre/admin) + their memberships. Called from
  ``init_db()`` on every startup.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Row

from app.auth.jwt import create_access_token
from app.auth.service import _row_to_user  # internal reuse (same team)
from app.db_seed import get_engine, tenants, tenant_memberships, users

logger = logging.getLogger("tevet7.tenants.service")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _row_to_tenant(row: Row) -> dict[str, Any]:
    """Project a SQLAlchemy Row from ``tenants`` into a JSON-safe dict."""
    ca = row.created_at
    return {
        "id": row.id,
        "name": row.name,
        "slug": row.slug,
        "is_demo": bool(row.is_demo),
        "created_at": ca.isoformat() if ca is not None else None,
        "owner_user_id": row.owner_user_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


async def create_tenant(
    name: str, slug: str, owner_user_id: int,
) -> dict[str, Any]:
    """Create a tenant + make the owner an admin member.

    The slug must be unique - raises ``ValueError`` if it's already
    taken. The owner gets a membership with ``role="admin"`` and
    ``producer_id=None`` (admins see all rows in the tenant). The new
    membership is marked ``is_active=True`` (and any other membership the
    owner had is flipped to ``is_active=False`` - see
    :func:`set_active_membership`).
    """
    name = (name or "").strip()
    slug = (slug or "").strip().lower()
    if not name or not slug:
        raise ValueError("name and slug are both required")
    engine = get_engine()

    # Check slug uniqueness first (clean error vs IntegrityError).
    async with engine.connect() as conn:
        r = await conn.execute(select(tenants.c.id).where(tenants.c.slug == slug))
        if r.fetchone() is not None:
            raise ValueError(f"slug {slug!r} is already taken")

    async with engine.begin() as conn:
        result = await conn.execute(
            tenants.insert()
            .values(
                id=slug,  # use slug as the tenant id (stable, human-readable)
                name=name,
                slug=slug,
                is_demo=False,
                created_at=datetime.utcnow(),
                owner_user_id=int(owner_user_id),
            )
            .returning(tenants.c.id, tenants.c.name, tenants.c.slug,
                       tenants.c.is_demo, tenants.c.created_at, tenants.c.owner_user_id)
        )
        row = result.fetchone()
        # Owner is automatically an admin of their new tenant.
        await conn.execute(
            tenant_memberships.insert().values(
                user_id=int(owner_user_id),
                tenant_id=slug,
                role="admin",
                producer_id=None,
                is_active=True,
                created_at=datetime.utcnow(),
            )
        )
    # Flip any OTHER memberships the owner has to is_active=False (a user
    # has at most one active membership at a time).
    await _deactivate_other_memberships(owner_user_id, except_tenant_id=slug)
    logger.info(
        "create_tenant - tenant=%s name=%s owner_user_id=%d (admin)",
        slug, name, owner_user_id,
    )
    return _row_to_tenant(row)


async def list_user_tenants(user_id: int) -> list[dict[str, Any]]:
    """Return all tenants the user belongs to, with role/producer/active."""
    engine = get_engine()
    async with engine.connect() as conn:
        r = await conn.execute(
            select(
                tenants.c.id,
                tenants.c.name,
                tenants.c.slug,
                tenants.c.is_demo,
                tenants.c.created_at,
                tenants.c.owner_user_id,
                tenant_memberships.c.role,
                tenant_memberships.c.producer_id,
                tenant_memberships.c.is_active,
            )
            .select_from(
                tenant_memberships.join(
                    tenants, tenants.c.id == tenant_memberships.c.tenant_id
                )
            )
            .where(tenant_memberships.c.user_id == int(user_id))
            .order_by(tenant_memberships.c.created_at.asc())
        )
        items = []
        for row in r.fetchall():
            items.append({
                "tenant_id": row.id,
                "name": row.name,
                "slug": row.slug,
                "is_demo": bool(row.is_demo),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "role": row.role,
                "producer_id": row.producer_id,
                "is_active": bool(row.is_active),
            })
    return items


async def get_tenant(tenant_id: str) -> dict[str, Any] | None:
    """Return a single tenant dict, or None."""
    engine = get_engine()
    async with engine.connect() as conn:
        r = await conn.execute(
            select(tenants).where(tenants.c.id == tenant_id)
        )
        row = r.fetchone()
    if row is None:
        return None
    return _row_to_tenant(row)


async def get_tenant_members(tenant_id: str) -> list[dict[str, Any]]:
    """Return all members of ``tenant_id`` (with their user info)."""
    engine = get_engine()
    async with engine.connect() as conn:
        r = await conn.execute(
            select(
                tenant_memberships.c.id,
                tenant_memberships.c.user_id,
                tenant_memberships.c.role,
                tenant_memberships.c.producer_id,
                tenant_memberships.c.is_active,
                tenant_memberships.c.created_at,
                users.c.email,
                users.c.name,
            )
            .select_from(
                tenant_memberships.join(users, users.c.id == tenant_memberships.c.user_id)
            )
            .where(tenant_memberships.c.tenant_id == tenant_id)
            .order_by(tenant_memberships.c.created_at.asc())
        )
        items = []
        for row in r.fetchall():
            ca = row.created_at
            items.append({
                "user_id": row.user_id,
                "email": row.email,
                "name": row.name,
                "role": row.role,
                "producer_id": row.producer_id,
                "is_active": bool(row.is_active),
                "created_at": ca.isoformat() if ca else None,
            })
    return items


async def add_tenant_member(
    tenant_id: str, user_id: int, role: str,
    producer_id: int | None = None,
) -> dict[str, Any]:
    """Add a user to a tenant with the given role/producer_id.

    Raises ``ValueError`` if the tenant doesn't exist or the (user,
    tenant) pair is already a member. The new membership is
    ``is_active=False`` by default (the user must explicitly activate it
    via ``set_active_membership`` to switch their context).

    Role validation: tenants that completed the onboarding wizard define
    their own roles in ``tenant_configs.roles_config`` (the "define roles"
    step) - those are the source of truth here. Tenants without a
    roles_config (demo tenant, legacy rows) fall back to the built-in trio.
    """
    from app.tenants.onboarding import get_tenant_config_row  # local: avoids import cycle

    valid_roles = {"producer", "admin", "customer"}
    config = await get_tenant_config_row(tenant_id)
    if config and config.get("roles_config"):
        # "admin" is always valid - the wizard doesn't require re-declaring it.
        valid_roles = set(config["roles_config"].keys()) | {"admin"}
    if role not in valid_roles:
        raise ValueError(
            f"role must be one of {sorted(valid_roles)}, got {role!r}"
        )
    engine = get_engine()
    # Verify tenant exists.
    async with engine.connect() as conn:
        r = await conn.execute(select(tenants.c.id).where(tenants.c.id == tenant_id))
        if r.fetchone() is None:
            raise ValueError(f"tenant {tenant_id!r} does not exist")
        r = await conn.execute(
            select(tenant_memberships.c.id).where(
                (tenant_memberships.c.user_id == int(user_id))
                & (tenant_memberships.c.tenant_id == tenant_id)
            )
        )
        if r.fetchone() is not None:
            raise ValueError(
                f"user {user_id} is already a member of tenant {tenant_id!r}"
            )
    async with engine.begin() as conn:
        result = await conn.execute(
            tenant_memberships.insert()
            .values(
                user_id=int(user_id),
                tenant_id=tenant_id,
                role=role,
                producer_id=producer_id,
                is_active=False,
                created_at=datetime.utcnow(),
            )
            .returning(tenant_memberships.c.id)
        )
        membership_id = int(result.scalar_one())
    logger.info(
        "add_tenant_member - tenant=%s user_id=%d role=%s producer_id=%s",
        tenant_id, user_id, role, producer_id,
    )
    return {
        "id": membership_id,
        "tenant_id": tenant_id,
        "user_id": int(user_id),
        "role": role,
        "producer_id": producer_id,
        "is_active": False,
    }


async def _deactivate_other_memberships(
    user_id: int, except_tenant_id: str | None,
) -> None:
    """Flip all of the user's memberships to ``is_active=False`` except
    the one for ``except_tenant_id``.

    Called by :func:`set_active_membership` and :func:`create_tenant` to
    enforce the "one active membership per user" invariant.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        stmt = (
            update(tenant_memberships)
            .where(tenant_memberships.c.user_id == int(user_id))
            .values(is_active=False)
        )
        if except_tenant_id is not None:
            stmt = stmt.where(tenant_memberships.c.tenant_id != except_tenant_id)
        await conn.execute(stmt)


async def set_active_membership(
    user_id: int, tenant_id: str,
) -> tuple[dict[str, Any], str]:
    """Set the user's active membership to ``tenant_id`` and return
    ``(membership_dict, new_jwt)``.

    The new JWT has the membership's role + producer_id baked in so the
    HTTP layer can extract identity from the token without a DB lookup
    on every request.

    Raises ``ValueError`` if the user is not a member of ``tenant_id``.
    """
    engine = get_engine()
    async with engine.connect() as conn:
        r = await conn.execute(
            select(tenant_memberships).where(
                (tenant_memberships.c.user_id == int(user_id))
                & (tenant_memberships.c.tenant_id == tenant_id)
            )
        )
        row = r.fetchone()
    if row is None:
        raise ValueError(
            f"user {user_id} is not a member of tenant {tenant_id!r}"
        )
    # Flip the chosen membership to is_active=True and the rest to False.
    async with engine.begin() as conn:
        await conn.execute(
            update(tenant_memberships)
            .where(
                (tenant_memberships.c.user_id == int(user_id))
                & (tenant_memberships.c.tenant_id == tenant_id)
            )
            .values(is_active=True)
        )
    await _deactivate_other_memberships(user_id, except_tenant_id=tenant_id)
    # Look up is_demo for the tenant (so the JWT carries the demo flag).
    async with engine.connect() as conn:
        r = await conn.execute(
            select(tenants.c.is_demo).where(tenants.c.id == tenant_id)
        )
        trow = r.fetchone()
    is_demo = bool(trow.is_demo) if trow is not None else False
    # Look up the user email (for the JWT claim).
    async with engine.connect() as conn:
        r = await conn.execute(select(users).where(users.c.id == int(user_id)))
        urow = r.fetchone()
    user_dict = _row_to_user(urow) if urow is not None else {"id": int(user_id), "email": "", "name": "", "created_at": None}

    membership = {
        "tenant_id": tenant_id,
        "role": row.role,
        "producer_id": row.producer_id,
        "is_active": True,
    }
    token = create_access_token({
        "sub": str(user_id),
        "email": user_dict["email"],
        "tenant_id": tenant_id,
        "role": row.role,
        "producer_id": row.producer_id,
        "is_demo": is_demo,
    })
    logger.info(
        "set_active_membership - user_id=%d tenant=%s role=%s producer_id=%s",
        user_id, tenant_id, row.role, row.producer_id,
    )
    return membership, token


# ─────────────────────────────────────────────────────────────────────────────
# Demo seed
# ─────────────────────────────────────────────────────────────────────────────


# Demo accounts created by seed_demo_tenant. The producer_id matches the
# seed data in app.db_seed._PRODUCERS (Marie=42, Pierre=99, admin=null).
_DEMO_USERS: list[dict[str, Any]] = [
    {
        "email": "marie@tevet7.dev",
        "name": "Marie Dubois",
        "password": "tevet7demo",
        "role": "producer",
        "producer_id": 42,
    },
    {
        "email": "pierre@tevet7.dev",
        "name": "Pierre Martin",
        "password": "tevet7demo",
        "role": "producer",
        "producer_id": 99,
    },
    {
        "email": "admin@tevet7.dev",
        "name": "Admin Tevet-7",
        "password": "tevet7demo",
        "role": "admin",
        "producer_id": None,
    },
]


async def seed_demo_tenant() -> None:
    """Create the ``dp`` demo tenant + 3 demo users (idempotent).

    Called by ``init_db()`` on every startup. Safe to call multiple
    times - checks for existence before each insert.

    Demo accounts (password ``tevet7demo`` for all three):
      - marie@tevet7.dev  → role=producer,  producer_id=42
      - pierre@tevet7.dev → role=producer,  producer_id=99
      - admin@tevet7.dev  → role=admin,     producer_id=None

    The first demo user (marie) gets ``is_active=True`` so logging in as
    marie yields a JWT with the right tenant context out of the box.
    """
    from app.auth.jwt import hash_password  # local import to avoid cycle at module load

    engine = get_engine()
    now = datetime.utcnow()

    # 1) Create the demo tenant (idempotent).
    async with engine.connect() as conn:
        r = await conn.execute(select(tenants.c.id).where(tenants.c.id == "dp"))
        if r.fetchone() is None:
            # Use engine.begin() to wrap the INSERT in a transaction so
            # it actually commits (engine.connect() does NOT autocommit).
            async with engine.begin() as txn:
                await txn.execute(
                    tenants.insert().values(
                        id="dp",
                        name="Drive Producteur",
                        slug="dp",
                        is_demo=True,
                        created_at=now,
                        owner_user_id=None,  # filled below once the admin user exists
                    )
                )
            logger.info("seed_demo_tenant - created tenant 'dp' (is_demo=True)")

    # 2) Create the 3 demo users (idempotent).
    user_ids: dict[str, int] = {}
    for u in _DEMO_USERS:
        email = u["email"]
        async with engine.connect() as conn:
            r = await conn.execute(select(users.c.id).where(users.c.email == email))
            row = r.fetchone()
        if row is not None:
            user_ids[email] = int(row.id)
            continue
        # Insert with a fresh bcrypt hash.
        password_hash = hash_password(u["password"])
        async with engine.begin() as txn:
            result = await txn.execute(
                users.insert()
                .values(
                    email=email,
                    name=u["name"],
                    password_hash=password_hash,
                    created_at=now,
                )
                .returning(users.c.id)
            )
            user_ids[email] = int(result.scalar_one())
        logger.info("seed_demo_tenant - created user %s (id=%d)", email, user_ids[email])

    # 3) Set the tenant's owner_user_id (to the admin demo user) if it's
    #    still NULL.
    admin_id = user_ids.get("admin@tevet7.dev")
    if admin_id is not None:
        async with engine.begin() as txn:
            await txn.execute(
                update(tenants).where(
                    (tenants.c.id == "dp") & (tenants.c.owner_user_id.is_(None))
                ).values(owner_user_id=admin_id)
            )
        # Mark the admin demo user as platform owner (Phase 6c).
        async with engine.begin() as txn:
            await txn.execute(
                update(users).where(users.c.id == admin_id).values(is_platform_owner=True)
            )
        logger.info("seed_demo_tenant - admin@tevet7.dev marked as platform_owner")

    # 4) Create the memberships (idempotent). Marie gets is_active=True
    #    so the first demo login yields a fully-contextualised JWT.
    for u in _DEMO_USERS:
        email = u["email"]
        uid = user_ids.get(email)
        if uid is None:
            continue
        async with engine.connect() as conn:
            r = await conn.execute(
                select(tenant_memberships.c.id).where(
                    (tenant_memberships.c.user_id == uid)
                    & (tenant_memberships.c.tenant_id == "dp")
                )
            )
            if r.fetchone() is not None:
                continue
        is_first_demo_user = (email == "marie@tevet7.dev")
        async with engine.begin() as txn:
            await txn.execute(
                tenant_memberships.insert().values(
                    user_id=uid,
                    tenant_id="dp",
                    role=u["role"],
                    producer_id=u["producer_id"],
                    is_active=is_first_demo_user,
                    created_at=now,
                )
            )
        logger.info(
            "seed_demo_tenant - membership user=%s tenant=dp role=%s producer_id=%s is_active=%s",
            email, u["role"], u["producer_id"], is_first_demo_user,
        )

    logger.info(
        "seed_demo_tenant - done (3 demo users: marie/pierre/admin, password 'tevet7demo')"
    )
