"""Admin service — business logic for the admin console.

Two surfaces:
  - **Tenant admin** (a member with role "admin" on a tenant): list users,
    config, conversations (traces), usage stats for THEIR tenant.
  - **Platform owner** (a user with ``is_platform_owner=True``): list ALL
    tenants, global stats, reset the demo tenant.

All functions are pure-async + take a session — no FastAPI deps. Routes
in ``app/admin/routes.py`` handle auth + tracing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.demo_reset import reset_demo_data
from app.db_seed import (
    orders,
    tenant_configs,
    tenant_memberships,
    tenants,
    traces_table as traces,
    users,
)

logger = logging.getLogger("opspilot.admin.service")


# ─────────────────────────────────────────────────────────────────────────────
# Tenant admin functions
# ─────────────────────────────────────────────────────────────────────────────


async def get_tenant_users(
    db: AsyncSession, tenant_id: str
) -> list[dict[str, Any]]:
    """List members of a tenant with their user row joined."""
    rows = (await db.execute(
        select(
            tenant_memberships.c.user_id,
            tenant_memberships.c.role,
            tenant_memberships.c.producer_id,
            tenant_memberships.c.created_at,
            users.c.email,
            users.c.name,
            users.c.is_platform_owner,
        )
        .join(users, users.c.id == tenant_memberships.c.user_id)
        .where(tenant_memberships.c.tenant_id == tenant_id)
        .order_by(tenant_memberships.c.created_at)
    )).all()
    return [
        {
            "user_id": r.user_id,
            "email": r.email,
            "name": r.name,
            "role": r.role,
            "producer_id": r.producer_id,
            "is_platform_owner": bool(r.is_platform_owner),
            "joined_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def get_tenant_config(
    db: AsyncSession, tenant_id: str
) -> dict[str, Any] | None:
    """Return the tenant_configs row with JSON fields parsed."""
    r = (await db.execute(
        select(tenant_configs).where(tenant_configs.c.tenant_id == tenant_id)
    )).first()
    if r is None:
        return None
    try:
        schema_config = json.loads(r.schema_config) if r.schema_config else {}
    except json.JSONDecodeError:
        schema_config = {}
    try:
        roles_config = json.loads(r.roles_config) if r.roles_config else {}
    except json.JSONDecodeError:
        roles_config = {}
    return {
        "tenant_id": r.tenant_id,
        "connector_type": r.connector_type,
        "schema_config": schema_config,
        "roles_config": roles_config,
        "onboarded": bool(r.onboarded),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


async def get_tenant_conversations(
    db: AsyncSession, tenant_id: str, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    """List recent traces for a tenant (newest first, paginated)."""
    rows = (await db.execute(
        select(traces)
        .where(traces.c.tenant_id == tenant_id)
        .order_by(traces.c.created_at.desc())
        .limit(min(max(limit, 1), 500))
        .offset(max(offset, 0))
    )).all()
    return [
        {
            "id": str(r.id),
            "identity_id": r.identity_id,
            "user_message": r.user_message,
            "intent": r.intent,
            "sql_generated": r.sql_generated,
            "latency_ms": r.latency_ms,
            "tokens": r.tokens_in + r.tokens_out,
            "cost_usd": r.cost_usd,
            "refused": bool(r.refused),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def count_tenant_conversations(db: AsyncSession, tenant_id: str) -> int:
    """Count total traces for a tenant (for pagination metadata)."""
    from sqlalchemy import func
    result = await db.execute(
        select(func.count()).select_from(traces).where(traces.c.tenant_id == tenant_id)
    )
    return int(result.scalar() or 0)


async def get_tenant_stats(
    db: AsyncSession, tenant_id: str
) -> dict[str, Any]:
    """Aggregate usage stats for a tenant.

    Returns: ``total_conversations, total_tokens, total_cost_usd,
    avg_latency_ms, refusal_rate, last_activity_at``.
    """
    row = (await db.execute(
        select(
            func.count().label("total_conversations"),
            func.coalesce(func.sum(traces.c.tokens_in + traces.c.tokens_out), 0).label("total_tokens"),
            func.coalesce(func.sum(traces.c.cost_usd), 0.0).label("total_cost_usd"),
            func.coalesce(func.avg(traces.c.latency_ms), 0.0).label("avg_latency_ms"),
            # SQLite stores booleans as 0/1 — SUM gives the refused count.
            func.coalesce(func.sum(traces.c.refused), 0).label("total_refused"),
            func.max(traces.c.created_at).label("last_activity_at"),
        ).where(traces.c.tenant_id == tenant_id)
    )).first()

    total = int(row.total_conversations or 0)
    refused = int(row.total_refused or 0)
    return {
        "tenant_id": tenant_id,
        "total_conversations": total,
        "total_tokens": int(row.total_tokens or 0),
        "total_cost_usd": round(float(row.total_cost_usd or 0.0), 6),
        "avg_latency_ms": round(float(row.avg_latency_ms or 0.0), 2),
        "refusal_rate": round(refused / total, 4) if total > 0 else 0.0,
        "last_activity_at": (
            row.last_activity_at.isoformat() if row.last_activity_at else None
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Platform owner functions
# ─────────────────────────────────────────────────────────────────────────────


async def is_platform_owner(db: AsyncSession, user_id: int) -> bool:
    """True if the user has the platform_owner flag."""
    r = (await db.execute(
        select(users.c.is_platform_owner).where(users.c.id == user_id)
    )).first()
    return bool(r and r.is_platform_owner)


async def list_all_tenants(db: AsyncSession, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """List all tenants with member_count, conversation_count, total_cost_usd (paginated)."""
    # Aggregate traces per tenant.
    trace_agg = (
        select(
            traces.c.tenant_id.label("tid"),
            func.count().label("conversation_count"),
            func.coalesce(func.sum(traces.c.cost_usd), 0.0).label("total_cost_usd"),
        )
        .group_by(traces.c.tenant_id)
        .subquery()
    )
    member_agg = (
        select(
            tenant_memberships.c.tenant_id.label("tid"),
            func.count().label("member_count"),
        )
        .group_by(tenant_memberships.c.tenant_id)
        .subquery()
    )
    cfg_agg = (
        select(
            tenant_configs.c.tenant_id.label("tid"),
            tenant_configs.c.onboarded.label("onboarded"),
        )
        .subquery()
    )

    rows = (await db.execute(
        select(
            tenants.c.id,
            tenants.c.name,
            tenants.c.is_demo,
            tenants.c.created_at,
            func.coalesce(member_agg.c.member_count, 0).label("member_count"),
            func.coalesce(trace_agg.c.conversation_count, 0).label("conversation_count"),
            func.coalesce(trace_agg.c.total_cost_usd, 0.0).label("total_cost_usd"),
            func.coalesce(cfg_agg.c.onboarded, False).label("onboarded"),
        )
        .outerjoin(member_agg, member_agg.c.tid == tenants.c.id)
        .outerjoin(trace_agg, trace_agg.c.tid == tenants.c.id)
        .outerjoin(cfg_agg, cfg_agg.c.tid == tenants.c.id)
        .order_by(tenants.c.created_at)
        .limit(min(max(limit, 1), 500))
        .offset(max(offset, 0))
    )).all()

    return [
        {
            "id": r.id,
            "name": r.name,
            "is_demo": bool(r.is_demo),
            "onboarded": bool(r.onboarded),
            "member_count": int(r.member_count or 0),
            "conversation_count": int(r.conversation_count or 0),
            "total_cost_usd": round(float(r.total_cost_usd or 0.0), 6),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def get_platform_stats(db: AsyncSession) -> dict[str, Any]:
    """Global platform stats across all tenants."""
    tenant_row = (await db.execute(
        select(
            func.count().label("total_tenants"),
        ).select_from(tenants)
    )).first()
    user_row = (await db.execute(
        select(func.count().label("total_users")).select_from(users)
    )).first()
    trace_row = (await db.execute(
        select(
            func.count().label("total_conversations"),
            func.coalesce(func.sum(traces.c.tokens_in + traces.c.tokens_out), 0).label("total_tokens"),
            func.coalesce(func.sum(traces.c.cost_usd), 0.0).label("total_cost_usd"),
            func.coalesce(func.avg(traces.c.latency_ms), 0.0).label("avg_latency_ms"),
        ).select_from(traces)
    )).first()
    return {
        "total_tenants": int(tenant_row.total_tenants or 0),
        "total_users": int(user_row.total_users or 0),
        "total_conversations": int(trace_row.total_conversations or 0),
        "total_tokens": int(trace_row.total_tokens or 0),
        "total_cost_usd": round(float(trace_row.total_cost_usd or 0.0), 6),
        "avg_latency_ms": round(float(trace_row.avg_latency_ms or 0.0), 2),
    }


async def reset_demo_tenant() -> dict[str, Any]:
    """Reset the demo tenant's business data (delegates to demo_reset).

    Returns the summary dict from ``reset_demo_data``.
    """
    return await reset_demo_data()
