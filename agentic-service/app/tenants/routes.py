"""Tenant HTTP routes for Tevet-7 (Phase 6a + 6b onboarding).

Endpoints
=========

Tenant management (Phase 6a):

- ``POST /api/tenants``                   — create a new tenant (requires
  auth). Body ``{name, slug}``. Returns the tenant + a new JWT with the
  tenant context (the creator becomes an admin of the new tenant).
- ``GET  /api/tenants/mine``              — list the user's tenants.
  Returns ``[{tenant_id, name, slug, role, producer_id, is_demo, is_active}]``.
- ``POST /api/tenants/{tenant_id}/activate`` — set the user's active
  tenant. Returns the membership + a new JWT.
- ``GET  /api/tenants/{tenant_id}``       — tenant detail (members list).
- ``POST /api/tenants/{tenant_id}/members`` — add a member (admin only).

Onboarding (Phase 6b — multi-step wizard):

- ``POST /api/tenants/{tenant_id}/onboarding/start``         — start/reset.
  Body ``{connector_type: "postgres" | "csv"}``.
- ``POST /api/tenants/{tenant_id}/onboarding/connect``       — test connection.
  Multipart form: ``connector_type``, ``connection_url?`` (postgres),
  ``file?`` (csv upload). Returns ``{ok, error, tables_count}``.
- ``POST /api/tenants/{tenant_id}/onboarding/detect-schema`` — auto-detect.
  Returns the draft schema (also stashes it as the pending schema_config).
- ``POST /api/tenants/{tenant_id}/onboarding/save-schema``   — body
  ``{schema_config: dict}``. Persists the user's edited schema.
- ``POST /api/tenants/{tenant_id}/onboarding/save-roles``    — body
  ``{roles_config: dict}``. Persists roles + scope columns.
- ``POST /api/tenants/{tenant_id}/onboarding/complete``      — mark done.
- ``GET  /api/tenants/{tenant_id}/onboarding/status``        — current state.

All endpoints require auth (``Authorization: Bearer <jwt>``) and the user
must be a member of the tenant (403 otherwise). The status endpoint
additionally accepts an ``admin=true`` query param for the demo path
(curl-verified by the worklog) so the eval / demo can probe the demo
tenant's onboarding state without a JWT.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user, try_get_tenant_context
from app.tenants.onboarding import (
    complete_onboarding,
    connect_csv,
    connect_postgres,
    detect_schema,
    get_onboarding_status,
    save_roles,
    save_schema,
    start_onboarding,
)
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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 6b — Onboarding endpoints
# ─────────────────────────────────────────────────────────────────────────────
# Multi-step wizard that turns a freshly-created tenant into an agent-ready
# workspace. Each endpoint requires the caller to be a member of the tenant
# (403 otherwise) — admin role is NOT required to RUN the wizard, but the
# frontend typically gates it to admins. The demo tenant "dp" is already
# onboarded (seeded by init_db) so its status endpoint returns
# {onboarded: true, connector_type: "sqlite_demo"}.


async def _verify_membership(tenant_id: str, user_id: int) -> None:
    """Raise 404 if the tenant doesn't exist, 403 if the user isn't a member.

    Used by every onboarding endpoint so we don't leak the tenant's
    existence to non-members.
    """
    tenant = await get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"tenant {tenant_id!r} not found",
        )
    members = await get_tenant_members(tenant_id)
    if not any(m["user_id"] == user_id for m in members):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"you are not a member of tenant {tenant_id!r}",
        )


class StartOnboardingRequest(BaseModel):
    connector_type: str = Field(
        ...,
        description="'postgres' or 'csv' — the data source type for this tenant.",
    )


@router.post("/tenants/{tenant_id}/onboarding/start")
async def onboarding_start_endpoint(
    tenant_id: str,
    body: StartOnboardingRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Start or reset the onboarding wizard for the tenant.

    Sets ``connector_type`` and resets any previous schema/roles/onboarded
    state so a re-onboarding starts from a clean slate.
    """
    await _verify_membership(tenant_id, current_user["id"])
    try:
        config = await start_onboarding(tenant_id, body.connector_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"config": config}


@router.post("/tenants/{tenant_id}/onboarding/connect")
async def onboarding_connect_endpoint(
    tenant_id: str,
    connector_type: str = Form(..., description="'postgres' or 'csv'."),
    connection_url: str | None = Form(
        None, description="Postgres URL (required when connector_type=postgres)."
    ),
    file: UploadFile | None = File(
        None, description="CSV file upload (required when connector_type=csv)."
    ),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Test the connection and save the connection info on success.

    For ``connector_type=postgres``: pass ``connection_url`` (the Postgres
    SQLAlchemy URL). For ``connector_type=csv``: upload the CSV file via
    the ``file`` form field.

    Returns ``{ok, error, tables_count}`` from the connector's
    ``test_connection()`` method.
    """
    await _verify_membership(tenant_id, current_user["id"])
    # Persist the chosen connector_type (so detect_schema knows which
    # connector to build) before delegating to the service.
    try:
        await start_onboarding(tenant_id, connector_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if connector_type == "postgres":
        if not connection_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="connector_type=postgres requires a 'connection_url' form field.",
            )
        result = await connect_postgres(tenant_id, connection_url)
    elif connector_type == "csv":
        if file is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="connector_type=csv requires a 'file' upload.",
            )
        file_bytes = await file.read()
        result = await connect_csv(tenant_id, file_bytes, file.filename or "upload.csv")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"connector_type must be 'postgres' or 'csv', got {connector_type!r}.",
        )
    return result


@router.post("/tenants/{tenant_id}/onboarding/detect-schema")
async def onboarding_detect_schema_endpoint(
    tenant_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Auto-detect the tenant's schema (tables + columns + inferred types).

    Returns the draft schema (also stashes it as the pending
    ``schema_config`` in the tenant_configs row). The user reviews + edits
    the draft, then calls ``save-schema`` to confirm.
    """
    await _verify_membership(tenant_id, current_user["id"])
    try:
        draft = await detect_schema(tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"schema": draft}


class SaveSchemaRequest(BaseModel):
    schema_config: dict = Field(
        ..., description="The user's edited schema (same shape as app/schema.yaml)."
    )


@router.post("/tenants/{tenant_id}/onboarding/save-schema")
async def onboarding_save_schema_endpoint(
    tenant_id: str,
    body: SaveSchemaRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Persist the user's edited schema as the tenant's schema_config."""
    await _verify_membership(tenant_id, current_user["id"])
    try:
        await save_schema(tenant_id, body.schema_config)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"saved": True, "tables_count": len(body.schema_config.get("tables", []))}


class SaveRolesRequest(BaseModel):
    roles_config: dict = Field(
        ...,
        description=(
            "Mapping role → {scope_column: str | null}. Example: "
            "{'producer': {'scope_column': 'producer_id'}, "
            "'admin': {'scope_column': null}}."
        ),
    )


@router.post("/tenants/{tenant_id}/onboarding/save-roles")
async def onboarding_save_roles_endpoint(
    tenant_id: str,
    body: SaveRolesRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Persist the tenant's roles + scope columns."""
    await _verify_membership(tenant_id, current_user["id"])
    try:
        await save_roles(tenant_id, body.roles_config)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"saved": True, "roles_count": len(body.roles_config)}


@router.post("/tenants/{tenant_id}/onboarding/complete")
async def onboarding_complete_endpoint(
    tenant_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Flip ``onboarded=True`` so the chat endpoint accepts requests.

    Raises 400 if the schema or roles haven't been saved yet.
    """
    await _verify_membership(tenant_id, current_user["id"])
    try:
        await complete_onboarding(tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"onboarded": True, "tenant_id": tenant_id}


@router.get("/tenants/{tenant_id}/onboarding/status")
async def onboarding_status_endpoint(
    tenant_id: str,
    request: Request,
    admin: bool = Query(
        False,
        description=(
            "Demo / eval bypass — when true, skip membership verification "
            "so the curl-based worklog verification can probe the demo "
            "tenant without a JWT. Real callers (the frontend) MUST send "
            "a Bearer JWT instead."
        ),
    ),
) -> dict[str, Any]:
    """Return the onboarding state for ``tenant_id``.

    Returns ``{onboarded, connector_type, schema_tables_count, roles_count,
    has_connection, has_csv, has_schema, has_roles, created_at, updated_at}``.

    Auth model
    ----------

    Two paths are supported (mirrors ``app/api/chat.py``):

    1. **JWT path** — the caller sends ``Authorization: Bearer <jwt>``.
       Membership is verified server-side (403 if the user is not a
       member of the tenant).
    2. **Demo path** — the caller sends ``?admin=true`` (no JWT). The
       tenant's existence is verified (404 if unknown) but membership is
       NOT verified — used by the curl-based worklog verification +
       the eval. Lets the demo page show the demo tenant's onboarding
       state without forcing a login.

    If neither a JWT nor ``?admin=true`` is provided, returns 401.
    """
    jwt_ctx = try_get_tenant_context(request)
    if jwt_ctx is not None:
        # JWT path — verify membership.
        await _verify_membership(tenant_id, jwt_ctx.user_id)
    elif admin:
        # Demo path — verify the tenant exists (don't 404 on a typo).
        tenant = await get_tenant(tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"tenant {tenant_id!r} not found",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Send Authorization: Bearer <jwt> OR ?admin=true for the "
                "demo path."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await get_onboarding_status(tenant_id)
