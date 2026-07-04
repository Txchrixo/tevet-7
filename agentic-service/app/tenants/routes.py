"""Tenant HTTP routes for Tevet-7 (Phase 6a).

Endpoints
=========

- ``POST /api/tenants``                   — create a new tenant (requires
  auth). Body ``{name, slug}``. Returns the tenant + a new JWT with the
  tenant context (the creator becomes an admin of the new tenant).
- ``GET  /api/tenants/mine``              — list the user's tenants.
  Returns ``[{tenant_id, name, slug, role, producer_id, is_demo, is_active}]``.
- ``POST /api/tenants/{tenant_id}/activate`` — set the user's active
  tenant. Returns the membership + a new JWT.
- ``GET  /api/tenants/{tenant_id}``       — tenant detail (members list).

All endpoints require auth (``Authorization: Bearer <jwt>``).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.tenants.service import (
    add_tenant_member,
    create_tenant,
    get_tenant,
    get_tenant_members,
    list_user_tenants,
    set_active_membership,
)

logger = logging.getLogger("tevet7.tenants.routes")

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────────────────────


class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Tenant display name.")
    slug: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
        description=(
            "Tenant slug (lowercase letters, digits, hyphens; used as the "
            "tenant id). Example: 'fresh-logistics'."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/tenants — create
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/tenants")
async def create_tenant_endpoint(
    body: CreateTenantRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new tenant + a fresh JWT with the new tenant's context.

    The creator becomes an admin of their new tenant (``role="admin"``,
    ``producer_id=None``). The new membership is ``is_active=True`` so
    the returned JWT immediately has the right tenant context — the
    frontend can call ``/api/chat`` right away without an extra
    ``activate`` round-trip.
    """
    try:
        tenant = await create_tenant(
            name=body.name, slug=body.slug, owner_user_id=current_user["id"],
        )
    except ValueError as exc:
        detail = str(exc)
        if "already taken" in detail:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=detail
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=detail
        ) from exc
    # Issue a new JWT with the new tenant's context.
    membership, token = await set_active_membership(
        user_id=current_user["id"], tenant_id=tenant["id"],
    )
    return {"tenant": tenant, "membership": membership, "token": token}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/tenants/mine — list user's tenants
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/tenants/mine")
async def list_my_tenants_endpoint(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """List the tenants the current user belongs to.

    Each item carries ``{tenant_id, name, slug, role, producer_id,
    is_demo, is_active}``. The frontend uses this to render the tenant
    switcher.
    """
    items = await list_user_tenants(current_user["id"])
    return {"count": len(items), "tenants": items}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/tenants/{tenant_id}/activate — set active tenant
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/tenants/{tenant_id}/activate")
async def activate_tenant_endpoint(
    tenant_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Set the user's active tenant and return a fresh JWT.

    Raises 403 if the user is not a member of ``tenant_id``.
    """
    try:
        membership, token = await set_active_membership(
            user_id=current_user["id"], tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return {"membership": membership, "token": token}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/tenants/{tenant_id} — tenant detail
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/tenants/{tenant_id}")
async def get_tenant_endpoint(
    tenant_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return a tenant + its members list.

    The caller must be a member of the tenant (403 otherwise). The
    members list includes each member's user_id, email, name, role, and
    producer_id — enough for the admin UI to render a roster.
    """
    tenant = await get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"tenant {tenant_id!r} not found",
        )
    # Verify the caller is a member.
    members = await get_tenant_members(tenant_id)
    caller_is_member = any(
        m["user_id"] == current_user["id"] for m in members
    )
    if not caller_is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"you are not a member of tenant {tenant_id!r}",
        )
    return {"tenant": tenant, "members": members}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/tenants/{tenant_id}/members — add a member (admin only)
# ─────────────────────────────────────────────────────────────────────────────


class AddMemberRequest(BaseModel):
    email: str = Field(..., description="Email of the user to add (must already have an account).")
    role: str = Field(..., description="'producer' | 'admin' | 'customer'.")
    producer_id: int | None = Field(None, description="Row-level scope value (NULL for admin).")


@router.post("/tenants/{tenant_id}/members")
async def add_member_endpoint(
    tenant_id: str,
    body: AddMemberRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Add a user (by email) to a tenant. Admin-only.

    Looks up the user by email — if they don't have an account yet,
    returns 404. The new membership is ``is_active=False`` (the added
    user must explicitly activate it).
    """
    # Verify caller is an admin of this tenant.
    members = await get_tenant_members(tenant_id)
    caller = next((m for m in members if m["user_id"] == current_user["id"]), None)
    if caller is None or caller["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only tenant admins can add members",
        )
    # Look up the target user by email.
    from app.auth.service import get_user_by_email
    target = await get_user_by_email(body.email)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no user with email {body.email!r}",
        )
    try:
        membership = await add_tenant_member(
            tenant_id=tenant_id,
            user_id=target["id"],
            role=body.role,
            producer_id=body.producer_id,
        )
    except ValueError as exc:
        detail = str(exc)
        if "already a member" in detail:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=detail
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=detail
        ) from exc
    return {"membership": membership}
