"""Tenants package for Tevet-7 (Phase 6a — Option C modular monolith).

Public surface
--------------

    from app.tenants import tenants_router

The tenant service functions (``create_tenant``, ``list_user_tenants``,
``set_active_membership``, ``seed_demo_tenant``) live in
``app.tenants.service`` and are imported by ``app.db_seed.init_db`` to
seed the demo "dp" tenant on startup.

Architecture
------------

Tenants are the top-level isolation boundary in Tevet-7: every business
row (orders, products, stocks, documents, traces, approvals) carries a
``tenant_id`` so the same database can host multiple customers without
cross-contamination. The row-level ``producer_id`` scoping is a SECOND
layer inside one tenant (producer Marie sees only her rows within tenant
``dp``).

The CORE agentic (agents/tools/tracing) is unaware of tenants — it
receives ``tenant_id`` as a plain string from the HTTP layer and uses it
as a filter when querying. This module owns the tenant CRUD + the
membership model (which user belongs to which tenant with which role).
"""

from __future__ import annotations

from app.tenants.routes import router as tenants_router

__all__ = ["tenants_router"]
