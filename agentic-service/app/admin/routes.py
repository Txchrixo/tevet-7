"""Admin routes — tenant admin + platform owner surfaces.

Phase 6c: these endpoints power the admin console UI. They are mounted at
``/api/admin`` by main.py. Tracer calls removed (LocalTracer has no .trace
method); the underlying service functions are traced via spans where needed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import service as admin_service
from app.auth.dependencies import require_platform_owner, require_tenant_admin
from app.database import get_db

router = APIRouter()


@router.get("/tenants/{tenant_id}/users", response_model=list[dict[str, Any]])
async def admin_tenant_users(
    ctx=Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List members of the tenant. Admins + platform owners only."""
    return await admin_service.get_tenant_users(db, ctx.tenant_id)


@router.get("/tenants/{tenant_id}/config", response_model=dict[str, Any])
async def admin_tenant_config(
    ctx=Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the tenant config (parsed). Admins + platform owners only."""
    return await admin_service.get_tenant_config(db, ctx.tenant_id)


@router.get("/tenants/{tenant_id}/conversations", response_model=list[dict[str, Any]])
async def admin_tenant_conversations(
    ctx=Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List recent traces for a tenant. Admins + platform owners only."""
    return await admin_service.get_tenant_conversations(db, ctx.tenant_id, limit)


@router.get("/tenants/{tenant_id}/stats", response_model=dict[str, Any])
async def admin_tenant_stats(
    ctx=Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Aggregate stats for the tenant. Admins + platform owners only."""
    return await admin_service.get_tenant_stats(db, ctx.tenant_id)


@router.get("/platform/tenants", response_model=list[dict[str, Any]])
async def admin_platform_tenants(
    user=Depends(require_platform_owner),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all tenants (platform owner only)."""
    return await admin_service.list_all_tenants(db)


@router.get("/platform/stats", response_model=dict[str, Any])
async def admin_platform_stats(
    user=Depends(require_platform_owner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Global platform stats (platform owner only)."""
    return await admin_service.get_platform_stats(db)


@router.post("/platform/reset-demo", response_model=dict[str, Any])
async def admin_platform_reset_demo(
    user=Depends(require_platform_owner),
) -> dict[str, Any]:
    """Reset the demo tenant's business data (platform owner only).

    Note: no `db` dependency here — reset_demo_data() calls init_db() which
    drops + recreates all tables, so we can't have an open session.
    """
    return await admin_service.reset_demo_tenant()
