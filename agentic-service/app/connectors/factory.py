"""Connector factory - returns the right connector for a given tenant.

Phase 6b onboarding backend - the chat endpoint (and any other HTTP handler
that touches tenant data) calls ``get_connector_for_tenant(tenant_id)`` to
get a per-request connector instance. The factory loads the tenant's
config row from ``tenant_configs`` and returns:

  - ``SqliteConnector``     when ``connector_type == "sqlite_demo"``
                            (the demo tenant ``dp`` - backward compat).
  - ``PostgresConnector``   when ``connector_type == "postgres"``.
  - ``CsvConnector``        when ``connector_type == "csv"``.
  - ``SqliteConnector``     (fallback) when the tenant has no config row
                            yet - preserves the legacy eval path (body
                            identity → tenant_id="dp") without a DB lookup.

The factory does NOT cache connectors - each request builds a fresh one so
the tenant context is always current (a tenant that re-runs onboarding
mid-session must see their new connector on the next request). The
connector instances are cheap (lazy engine) so per-request construction
is fine.

If the tenant is not onboarded (``tenant_configs.onboarded == False``),
the factory raises ``TenantNotOnboardedError`` so the HTTP layer can
return a clear "complete onboarding" message to the frontend.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select

from app.connectors.base import Connector
from app.connectors.csv_connector import CsvConnector
from app.connectors.postgres_connector import PostgresConnector
from app.connectors.sqlite_connector import SqliteConnector
from app.db_seed import get_engine, tenant_configs

logger = logging.getLogger("tevet7.connectors.factory")


class TenantNotOnboardedError(Exception):
    """Raised when ``get_connector_for_tenant`` is called on a tenant
    whose ``tenant_configs.onboarded`` flag is False.

    The HTTP layer catches this and returns a 409 with a French message
    telling the user to complete onboarding first.
    """

    def __init__(self, tenant_id: str) -> None:
        super().__init__(
            f"Tenant {tenant_id!r} is not onboarded yet - complete onboarding "
            "to activate the agent."
        )
        self.tenant_id = tenant_id


async def _load_tenant_config(tenant_id: str) -> dict[str, Any] | None:
    """Load the tenant's config row from ``tenant_configs``.

    Returns ``None`` if the tenant has no config row (e.g. a brand-new
    tenant that hasn't started onboarding yet, or the legacy demo tenant
    before its config row is seeded).
    """
    engine = get_engine()
    async with engine.connect() as conn:
        r = await conn.execute(
            select(
                tenant_configs.c.id,
                tenant_configs.c.tenant_id,
                tenant_configs.c.connector_type,
                tenant_configs.c.connection_url,
                tenant_configs.c.csv_path,
                tenant_configs.c.schema_config,
                tenant_configs.c.roles_config,
                tenant_configs.c.onboarded,
            ).where(tenant_configs.c.tenant_id == tenant_id)
        )
        row = r.fetchone()
    if row is None:
        return None
    schema_config = None
    if row.schema_config:
        try:
            schema_config = json.loads(row.schema_config)
        except (ValueError, TypeError):
            logger.warning(
                "tenant_configs.schema_config for %r is not valid JSON - treating as empty",
                tenant_id,
            )
    roles_config = None
    if row.roles_config:
        try:
            roles_config = json.loads(row.roles_config)
        except (ValueError, TypeError):
            roles_config = None
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "connector_type": row.connector_type,
        "connection_url": row.connection_url,
        "csv_path": row.csv_path,
        "schema_config": schema_config,
        "roles_config": roles_config,
        "onboarded": bool(row.onboarded),
    }


async def get_connector_for_tenant(tenant_id: str) -> Connector:
    """Return the right connector for the given tenant.

    Raises ``TenantNotOnboardedError`` if the tenant has a config row
    whose ``onboarded`` flag is False, OR if the tenant has no config
    row at all AND is not the demo tenant ``"dp"``.

    For the demo tenant ``"dp"`` (whose config row is seeded by
    ``init_db()`` with ``connector_type="sqlite_demo"``,
    ``onboarded=True``), the factory returns a ``SqliteConnector``. If
    ``dp``'s config row is missing for any reason (e.g. init_db hasn't
    run yet - should not happen in normal operation), we fall back to
    ``SqliteConnector`` so the eval + the demo path keep working
    unchanged.
    """
    config = await _load_tenant_config(tenant_id)

    # No config row → only the demo tenant "dp" gets the SqliteConnector
    # fallback (legacy / eval path - its config row is seeded by
    # init_db). Any OTHER tenant with no config row is genuinely
    # unconfigured → refuse with a clear error so the agent doesn't
    # silently fall through to the demo's data.
    if config is None:
        if tenant_id == "dp":
            return SqliteConnector()
        raise TenantNotOnboardedError(tenant_id)

    # Has a config row but not onboarded yet → refuse with a clear error.
    if not config["onboarded"]:
        raise TenantNotOnboardedError(tenant_id)

    ctype = config["connector_type"]
    schema_cfg = config["schema_config"]

    if ctype == "sqlite_demo":
        # Demo tenant - backward compat: SqliteConnector reads dev.db.
        return SqliteConnector()
    if ctype == "postgres":
        if not config["connection_url"]:
            raise TenantNotOnboardedError(tenant_id)
        return PostgresConnector(
            tenant_id=tenant_id,
            connection_url=config["connection_url"],
            schema_config=schema_cfg,
        )
    if ctype == "csv":
        if not config["csv_path"]:
            raise TenantNotOnboardedError(tenant_id)
        return CsvConnector(
            tenant_id=tenant_id,
            csv_path=config["csv_path"],
            schema_config=schema_cfg,
        )

    # Unknown connector_type - log + fall back to SqliteConnector so the
    # platform doesn't crash for a tenant with a malformed config.
    logger.warning(
        "Unknown connector_type %r for tenant %r - falling back to SqliteConnector",
        ctype, tenant_id,
    )
    return SqliteConnector()


async def is_tenant_onboarded(tenant_id: str) -> bool:
    """Return True iff the tenant has a config row with onboarded=True.

    Used by the HTTP layer to gate endpoints that require an onboarded
    tenant (chat / documents / approvals). The demo tenant ``dp`` is
    always onboarded (seeded with onboarded=True).
    """
    config = await _load_tenant_config(tenant_id)
    if config is None:
        # No row → legacy / demo path (dp's row is seeded by init_db, so
        # this branch is only hit for unknown tenants - return False).
        return False
    return bool(config["onboarded"])
