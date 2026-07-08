"""Onboarding service for Tevet-7 (Phase 6b).

Implements the multi-step wizard that turns a freshly-created tenant into
an agent-ready workspace:

  1. ``start_onboarding``      - creates/updates a ``tenant_configs`` row
                                  with the chosen connector_type
                                  (``"postgres"`` or ``"csv"``).
  2. ``connect_postgres``      - tests a Postgres connection URL.
     ``connect_csv``           - saves an uploaded CSV file + tests loading.
  3. ``detect_schema``         - uses the connector's ``detect_schema()``
                                  to auto-discover tables/columns. Returns
                                  a draft for the user to review/edit.
  4. ``save_schema``           - persists the user's edited schema as the
                                  tenant's ``schema_config``.
  5. ``save_roles``            - persists the tenant's roles + scope columns.
  6. ``complete_onboarding``   - flips ``onboarded=True``. The chat
                                  endpoint refuses to run before this.
  7. ``get_onboarding_status`` - returns the current onboarding state
                                  (used by the wizard to resume mid-flow).

All functions are async and operate on the ``tenant_configs`` table. They
are tenant-scoped - the caller (HTTP layer) MUST verify the user is a
member of ``tenant_id`` before invoking them.

The service does NOT modify the CORE agentic - only the ``tenant_configs``
table + the connector layer. The agent + tools + tracing are unchanged.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.connectors.csv_connector import CsvConnector, _ensure_csv_dir
from app.connectors.postgres_connector import PostgresConnector
from app.db_seed import get_engine, tenant_configs

logger = logging.getLogger("tevet7.tenants.onboarding")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


async def get_tenant_config_row(tenant_id: str) -> dict[str, Any] | None:
    """Public wrapper around :func:`_get_config_row`.

    Returns the tenant_configs row for ``tenant_id`` (with JSON fields
    parsed into dicts), or ``None`` if the tenant has no config row.

    Used by ``GET /api/tenants/{tenant_id}/example-questions`` to load
    the schema_config + onboarded flag without going through the admin
    surface (which requires the admin role).
    """
    return await _get_config_row(tenant_id)


async def resolve_role_scope(
    tenant_id: str, role: str, scope_value: int | str | None,
) -> tuple[str | None, int | str | None]:
    """Resolve the (scope_column, scope_value) pair for a role on a tenant.

    Onboarded tenants define their roles in ``roles_config`` (the wizard's
    "define roles" step): ``{"driver": {"scope_column": "driver_id"},
    "admin": {"scope_column": null}}``. That mapping is the source of
    truth - a scoped custom role MUST get its scope column from here,
    otherwise row-level security silently degrades to "no scoping".

    Tenants without a roles_config (the demo tenant "dp", the legacy body
    path) fall back to the historical rule: ONLY "admin" is unscoped,
    every other role (producer, customer, unknown) is scoped by
    ``producer_id`` - the same semantics the old role-coercion in
    app/api/chat.py enforced (customer used to be coerced to producer).
    Fail-closed: an unrecognized role must never mean "no scoping".

    Returns ``(None, None)`` when the role is unscoped (e.g. admin).
    """
    config = await _get_config_row(tenant_id)
    roles_cfg = (config or {}).get("roles_config") or {}
    role_cfg = roles_cfg.get(role)
    if role_cfg is not None:
        scope_column = role_cfg.get("scope_column")
    else:
        scope_column = None if role == "admin" else "producer_id"
    if not scope_column:
        return None, None
    return scope_column, scope_value


async def _get_config_row(tenant_id: str) -> dict[str, Any] | None:
    """Return the tenant_configs row for ``tenant_id``, or None."""
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
                tenant_configs.c.created_at,
                tenant_configs.c.updated_at,
            ).where(tenant_configs.c.tenant_id == tenant_id)
        )
        row = r.fetchone()
    if row is None:
        return None
    schema_cfg = None
    if row.schema_config:
        try:
            schema_cfg = json.loads(row.schema_config)
        except (ValueError, TypeError):
            schema_cfg = None
    roles_cfg = None
    if row.roles_config:
        try:
            roles_cfg = json.loads(row.roles_config)
        except (ValueError, TypeError):
            roles_cfg = None
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "connector_type": row.connector_type,
        "connection_url": row.connection_url,
        "csv_path": row.csv_path,
        "schema_config": schema_cfg,
        "roles_config": roles_cfg,
        "onboarded": bool(row.onboarded),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def _upsert_config(
    tenant_id: str,
    *,
    connector_type: str | None = None,
    connection_url: str | None = None,
    csv_path: str | None = None,
    schema_config: dict | None = None,
    roles_config: dict | None = None,
    onboarded: bool | None = None,
) -> None:
    """Insert-or-update the tenant_configs row for ``tenant_id``.

    Only the fields passed as non-None are written (except ``onboarded``
    which is written iff explicitly passed - to allow flipping to True
    without touching the other fields). ``updated_at`` is always bumped.
    """
    engine = get_engine()
    now = datetime.utcnow()
    existing = await _get_config_row(tenant_id)
    # Build the values dict - only include keys that are not None (so we
    # don't overwrite existing values with NULL).
    values: dict[str, Any] = {"updated_at": now}
    if connector_type is not None:
        values["connector_type"] = connector_type
    if connection_url is not None:
        values["connection_url"] = connection_url
    if csv_path is not None:
        values["csv_path"] = csv_path
    if schema_config is not None:
        values["schema_config"] = json.dumps(schema_config, ensure_ascii=False)
    if roles_config is not None:
        values["roles_config"] = json.dumps(roles_config, ensure_ascii=False)
    if onboarded is not None:
        values["onboarded"] = onboarded

    if existing is None:
        # Insert - fill the required fields with sensible defaults.
        insert_values = {
            "tenant_id": tenant_id,
            "connector_type": connector_type or "sqlite_demo",
            "connection_url": connection_url,
            "csv_path": csv_path,
            "schema_config": values.get(
                "schema_config",
                json.dumps({}, ensure_ascii=False),
            ),
            "roles_config": values.get(
                "roles_config",
                json.dumps({}, ensure_ascii=False),
            ),
            "onboarded": bool(onboarded) if onboarded is not None else False,
            "created_at": now,
            "updated_at": now,
        }
        async with engine.begin() as txn:
            await txn.execute(tenant_configs.insert().values(**insert_values))
    else:
        async with engine.begin() as txn:
            await txn.execute(
                tenant_configs.update()
                .where(tenant_configs.c.tenant_id == tenant_id)
                .values(**values)
            )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


async def start_onboarding(tenant_id: str, connector_type: str) -> dict[str, Any]:
    """Create or reset the tenant's onboarding session.

    Sets ``connector_type`` and flips ``onboarded=False`` (a re-onboarding
    must complete again before the agent runs). Returns the new config row.

    Raises ``ValueError`` if ``connector_type`` is not one of
    ``"postgres"`` or ``"csv"`` (``"sqlite_demo"`` is reserved for the
    demo tenant and cannot be set via this function).
    """
    if connector_type not in ("postgres", "csv"):
        raise ValueError(
            f"connector_type must be 'postgres' or 'csv', got {connector_type!r}"
        )
    await _upsert_config(
        tenant_id,
        connector_type=connector_type,
        # Reset the connection / csv / schema / roles so a re-onboarding
        # starts from a clean slate.
        connection_url=None,
        csv_path=None,
        schema_config={},
        roles_config={},
        onboarded=False,
    )
    logger.info(
        "start_onboarding - tenant=%s connector_type=%s",
        tenant_id, connector_type,
    )
    config = await _get_config_row(tenant_id)
    # Strip the raw JSON strings before returning to the API caller.
    return _public_config(config)


async def connect_postgres(tenant_id: str, connection_url: str) -> dict[str, Any]:
    """Test a Postgres connection URL and save it if the test passes.

    Returns ``{ok, error, tables_count}`` from the connector's
    ``test_connection()``. On success, also persists ``connection_url``
    to the tenant_configs row (so ``detect_schema`` can use it next).
    """
    connector = PostgresConnector(
        tenant_id=tenant_id,
        connection_url=connection_url,
        schema_config=None,
    )
    result = await connector.test_connection()
    if result["ok"]:
        await _upsert_config(
            tenant_id,
            connector_type="postgres",
            connection_url=connection_url,
        )
        logger.info(
            "connect_postgres - tenant=%s ok=True tables_count=%d",
            tenant_id, result.get("tables_count", 0),
        )
    else:
        logger.warning(
            "connect_postgres - tenant=%s ok=False error=%s",
            tenant_id, result.get("error"),
        )
    return result


async def connect_csv(
    tenant_id: str, file_bytes: bytes, filename: str,
) -> dict[str, Any]:
    """Save an uploaded CSV file and test loading it.

    The file is saved to ``/tmp/tevet7_csv/<tenant_id>.csv`` (overwriting
    any previous upload). Returns ``{ok, error, tables_count}`` from the
    connector's ``test_connection()``. On success, also persists
    ``csv_path`` to the tenant_configs row.

    Also invalidates any previously-loaded per-tenant SQLite file so the
    next request reloads the new CSV.
    """
    if not file_bytes:
        return {"ok": False, "error": "CSV file is empty.", "tables_count": 0}
    csv_dir = _ensure_csv_dir()
    # Sanitize the filename for disk - keep the extension, slugify the
    # base name. We use the tenant_id as the on-disk filename so multiple
    # uploads from the same tenant overwrite (not accumulate).
    ext = ".csv"
    base = os.path.basename(filename or "upload.csv")
    if "." in base:
        ext = "." + base.rsplit(".", 1)[-1].lower()
        if ext not in (".csv", ".tsv", ".txt"):
            ext = ".csv"
    csv_path = csv_dir / f"{tenant_id}{ext}"
    csv_path.write_bytes(file_bytes)
    # Invalidate any previously-loaded per-tenant SQLite file so the
    # next request reloads the new CSV.
    db_path = Path(_ensure_csv_dir()) / f"{tenant_id}.db"
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            logger.warning("could not delete stale CSV db %s", db_path, exc_info=True)
    connector = CsvConnector(
        tenant_id=tenant_id,
        csv_path=str(csv_path),
        schema_config=None,
    )
    result = await connector.test_connection()
    if result["ok"]:
        await _upsert_config(
            tenant_id,
            connector_type="csv",
            csv_path=str(csv_path),
        )
        logger.info(
            "connect_csv - tenant=%s ok=True tables_count=%d cols=%d",
            tenant_id, result.get("tables_count", 0),
            len(result.get("columns", []) or []),
        )
    else:
        logger.warning(
            "connect_csv - tenant=%s ok=False error=%s",
            tenant_id, result.get("error"),
        )
    return result


async def detect_schema(tenant_id: str) -> dict[str, Any]:
    """Auto-detect the tenant's schema using the connector's
    ``detect_schema()``. Returns the draft schema (the user reviews +
    edits it before ``save_schema`` persists it).

    Raises ``ValueError`` if the tenant has no connector configured yet
    (the user must call ``connect_postgres`` / ``connect_csv`` first).
    """
    config = await _get_config_row(tenant_id)
    if config is None:
        raise ValueError(
            f"tenant {tenant_id!r} has no onboarding session - call "
            "start_onboarding first."
        )
    ctype = config["connector_type"]
    if ctype == "postgres":
        if not config["connection_url"]:
            raise ValueError(
                "no connection_url saved - call connect_postgres first."
            )
        connector = PostgresConnector(
            tenant_id=tenant_id,
            connection_url=config["connection_url"],
            schema_config=None,
        )
    elif ctype == "csv":
        if not config["csv_path"]:
            raise ValueError("no csv_path saved - call connect_csv first.")
        connector = CsvConnector(
            tenant_id=tenant_id,
            csv_path=config["csv_path"],
            schema_config=None,
        )
    else:
        raise ValueError(
            f"detect_schema is only supported for 'postgres' / 'csv' tenants, "
            f"got connector_type={ctype!r}."
        )
    draft = await connector.detect_schema()
    # Stash the draft in the tenant_configs row as the schema_config (so
    # the user can review/edit it via the next step). The user MUST call
    # save_schema to confirm - detect_schema does NOT mark the tenant
    # onboarded.
    await _upsert_config(tenant_id, schema_config=draft)
    logger.info(
        "detect_schema - tenant=%s connector=%s tables=%d",
        tenant_id, ctype, len(draft.get("tables", [])),
    )
    return draft


async def save_schema(tenant_id: str, schema_config: dict) -> None:
    """Persist the user's edited schema as the tenant's schema_config."""
    if not isinstance(schema_config, dict):
        raise ValueError("schema_config must be a dict")
    if "tables" not in schema_config:
        raise ValueError("schema_config must have a 'tables' key")
    await _upsert_config(tenant_id, schema_config=schema_config)
    logger.info(
        "save_schema - tenant=%s tables=%d",
        tenant_id, len(schema_config.get("tables", [])),
    )


def _stamp_roles_on_schema(schema_config: dict, roles_config: dict) -> bool:
    """Propagate the wizard's roles onto the saved schema tables.

    The auto-detected schema only knows the legacy defaults
    (``allowed_for_roles=["producer", "admin"]``, ``tenant_scope_column``
    set only for a column literally named ``producer_id``). The wizard's
    "define roles" step is the source of truth, so after save_roles every
    table must:

    - list the tenant's declared roles in ``allowed_for_roles`` (otherwise
      a custom role like "driver" has zero queryable tables), and
    - carry the scoped role's ``tenant_scope_column`` when that column
      exists in the table (otherwise the sqlglot rewriter has nothing to
      match and row-level security silently does not apply).

    Mutates ``schema_config`` in place; returns True when anything changed.
    Note: the schema carries ONE scope column per table, so the first
    scoped role whose column exists wins (multi-scope-column tenants are
    not supported by the current data model).
    """
    role_names = set(roles_config.keys()) | {"admin"}
    scoped_columns = [
        cfg.get("scope_column")
        for cfg in roles_config.values()
        if isinstance(cfg, dict) and cfg.get("scope_column")
    ]
    changed = False
    for table in schema_config.get("tables", []):
        merged_roles = sorted(set(table.get("allowed_for_roles", [])) | role_names)
        if merged_roles != table.get("allowed_for_roles"):
            table["allowed_for_roles"] = merged_roles
            changed = True
        col_names = {c.get("name") for c in table.get("columns", [])}
        for scope_col in scoped_columns:
            if scope_col in col_names:
                if table.get("tenant_scope_column") != scope_col:
                    table["tenant_scope_column"] = scope_col
                    changed = True
                break
    return changed


async def save_roles(tenant_id: str, roles_config: dict) -> None:
    """Persist the tenant's roles + scope columns.

    Also re-stamps the saved schema_config (see
    :func:`_stamp_roles_on_schema`) so the declared roles and scope
    columns actually reach the connector + sqlglot rewriter.
    """
    if not isinstance(roles_config, dict):
        raise ValueError("roles_config must be a dict")
    config = await _get_config_row(tenant_id)
    schema_config = (config or {}).get("schema_config")
    if schema_config and _stamp_roles_on_schema(schema_config, roles_config):
        await _upsert_config(
            tenant_id, roles_config=roles_config, schema_config=schema_config,
        )
    else:
        await _upsert_config(tenant_id, roles_config=roles_config)
    logger.info(
        "save_roles - tenant=%s roles=%s",
        tenant_id, list(roles_config.keys()),
    )


async def complete_onboarding(tenant_id: str) -> None:
    """Flip ``onboarded=True`` so the chat endpoint accepts requests.

    Raises ``ValueError`` if the tenant's config is incomplete (missing
    schema_config or roles_config). The user must call ``save_schema``
    + ``save_roles`` first.
    """
    config = await _get_config_row(tenant_id)
    if config is None:
        raise ValueError(
            f"tenant {tenant_id!r} has no onboarding session - call "
            "start_onboarding first."
        )
    if not config["schema_config"]:
        raise ValueError("cannot complete onboarding - save_schema must run first.")
    if not config["schema_config"].get("tables"):
        raise ValueError(
            "cannot complete onboarding - schema_config has no tables."
        )
    if not config["roles_config"]:
        raise ValueError("cannot complete onboarding - save_roles must run first.")
    # Re-stamp roles onto the schema (idempotent): covers the case where
    # save_schema was re-run AFTER save_roles and wiped the stamped
    # allowed_for_roles / tenant_scope_column.
    schema_config = config["schema_config"]
    if _stamp_roles_on_schema(schema_config, config["roles_config"]):
        await _upsert_config(tenant_id, schema_config=schema_config, onboarded=True)
    else:
        await _upsert_config(tenant_id, onboarded=True)
    logger.info("complete_onboarding - tenant=%s onboarded=True", tenant_id)


async def get_onboarding_status(tenant_id: str) -> dict[str, Any]:
    """Return the current onboarding state for ``tenant_id``.

    Returns ``{onboarded, connector_type, schema_tables_count, roles_count,
    has_connection, has_csv, has_schema, has_roles, created_at, updated_at}``.

    Used by the wizard to resume mid-flow + by the frontend to gate the
    chat endpoint with a clear "complete onboarding" message.
    """
    config = await _get_config_row(tenant_id)
    if config is None:
        return {
            "onboarded": False,
            "connector_type": None,
            "schema_tables_count": 0,
            "roles_count": 0,
            "has_connection": False,
            "has_csv": False,
            "has_schema": False,
            "has_roles": False,
            "created_at": None,
            "updated_at": None,
        }
    schema_tables_count = len(config["schema_config"].get("tables", [])) if config["schema_config"] else 0
    roles_count = len(config["roles_config"]) if config["roles_config"] else 0
    return {
        "onboarded": config["onboarded"],
        "connector_type": config["connector_type"],
        "schema_tables_count": schema_tables_count,
        "roles_count": roles_count,
        "has_connection": bool(config["connection_url"]),
        "has_csv": bool(config["csv_path"]),
        "has_schema": bool(config["schema_config"] and config["schema_config"].get("tables")),
        "has_roles": bool(config["roles_config"]),
        "created_at": config["created_at"].isoformat() if config["created_at"] else None,
        "updated_at": config["updated_at"].isoformat() if config["updated_at"] else None,
    }


def _public_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Strip raw JSON strings + ISO-format datetimes for the API caller."""
    if config is None:
        return {}
    return {
        "tenant_id": config["tenant_id"],
        "connector_type": config["connector_type"],
        "connection_url": config["connection_url"],
        "csv_path": config["csv_path"],
        "schema_config": config["schema_config"],
        "roles_config": config["roles_config"],
        "onboarded": config["onboarded"],
        "created_at": config["created_at"].isoformat() if config["created_at"] else None,
        "updated_at": config["updated_at"].isoformat() if config["updated_at"] else None,
    }
