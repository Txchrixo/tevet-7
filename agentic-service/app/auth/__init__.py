"""Authentication package for Tevet-7 (Phase 6a — Option C modular monolith).

Public surface
--------------

    from app.auth import (
        auth_router,
        create_access_token,
        verify_token,
        hash_password,
        verify_password,
        get_current_user,
        get_tenant_context,
    )

* :data:`auth_router` — FastAPI router mounted under ``/api/auth`` with
  ``POST /signup``, ``POST /login``, ``GET /me``.
* :func:`create_access_token` / :func:`verify_token` — JWT helpers (HS256,
  ``JWT_SECRET`` from settings).
* :func:`hash_password` / :func:`verify_password` — bcrypt wrappers.
* :func:`get_current_user` / :func:`get_tenant_context` — FastAPI
  dependencies used by every authenticated HTTP route.

Architecture note
-----------------

This module is intentionally a sibling of ``app/agents/`` and
``app/tools/``. The CORE agentic (agents/tools/tracing/connectors) never
imports from ``app.auth`` — it has no notion of users or JWTs. The HTTP
layer (``app/api/*``) extracts the identity from the JWT (or from the
body, for the eval backward-compat path) and passes plain
``role``/``producer_id``/``tenant_id`` strings down to the orchestrator.

See ``docs/architecture.md`` and the Phase 6a entry in ``worklog.md`` for
the rationale (Option C: modular monolith — separate modules, single
deployment, no microservices).
"""

from __future__ import annotations

from app.auth.dependencies import (
    TenantContext,
    get_current_user,
    get_tenant_context,
)
from app.auth.jwt import (
    create_access_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.auth.routes import router as auth_router

__all__ = [
    "auth_router",
    "create_access_token",
    "verify_token",
    "hash_password",
    "verify_password",
    "get_current_user",
    "get_tenant_context",
    "TenantContext",
]
