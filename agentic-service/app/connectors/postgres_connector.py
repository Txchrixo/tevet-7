"""PostgresConnector - real Connector implementation backed by PostgreSQL.

Phase 6b onboarding backend - the connector used by tenants who configure a
PostgreSQL data source during onboarding. The connector:

1. Connects to the tenant's Postgres via SQLAlchemy async + asyncpg.
2. Loads the tenant's ``schema_config`` (saved by the onboarding wizard as a
   JSON string in ``tenant_configs.schema_config``).
3. Enforces read-only execution a second time at the connector level
   (defense in depth on top of the sqlglot rewriter) - non-SELECT statements
   are refused.
4. Auto-detects the tenant's schema by querying ``information_schema.tables``
   and ``information_schema.columns`` - used by the onboarding wizard's
   "detect schema" step.
5. Tests the connection (``test_connection``) - used by the onboarding
   wizard's "test connection" step before saving the URL.

The connector is constructed per request (not a singleton) so it respects
the tenant context. The agent and tools never see the connection URL - only
the connector does.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlglot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.connectors.base import ActionResult, Connector, QueryResult

logger = logging.getLogger("tevet7.connectors.postgres")


def _to_async_url(connection_url: str) -> str:
    """Coerce a user-supplied connection URL to the async asyncpg form.

    Accepts:
      - ``postgresql+asyncpg://user:pwd@host:5432/db``  → unchanged
      - ``postgresql://user:pwd@host:5432/db``           → swapped to +asyncpg
      - ``postgres://user:pwd@host:5432/db``             → swapped to +asyncpg
    """
    if connection_url.startswith("postgresql+asyncpg://"):
        return connection_url
    if connection_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + connection_url[len("postgresql://"):]
    if connection_url.startswith("postgres://"):
        return "postgresql+asyncpg://" + connection_url[len("postgres://"):]
    return connection_url


class PostgresConnector(Connector):
    """Connector backed by a tenant's PostgreSQL database.

    Parameters
    ----------
    tenant_id:
        The tenant id this connector belongs to (audit / logging).
    connection_url:
        SQLAlchemy URL for the tenant's Postgres. May be in either the
        sync form (``postgresql://...``) or the async form
        (``postgresql+asyncpg://...``) - the connector normalises it.
    schema_config:
        The tenant's saved schema_config dict (parsed from the JSON
        column in ``tenant_configs``). Same shape as ``app/schema.yaml``.
    """

    def __init__(
        self,
        tenant_id: str,
        connection_url: str,
        schema_config: dict | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.connection_url = connection_url
        self._schema_config: dict | None = schema_config
        self._engine: AsyncEngine | None = None

    # ── engine plumbing ──────────────────────────────────────────────────────
    @property
    def engine(self) -> AsyncEngine:
        """Lazy-create the async engine for the tenant's Postgres."""
        if self._engine is None:
            url = _to_async_url(self.connection_url)
            self._engine = create_async_engine(url, echo=False, future=True)
        return self._engine

    async def _dispose(self) -> None:
        """Dispose the engine if it was created. Best-effort - used by the
        onboarding wizard to free connections after a test."""
        if self._engine is not None:
            try:
                await self._engine.dispose()
            except Exception:  # noqa: BLE001
                logger.warning("PostgresConnector dispose failed", exc_info=True)
        self._engine = None

    # ── schema discovery ─────────────────────────────────────────────────────
    def get_schema(self) -> dict:
        """Return the tenant's saved schema_config dict.

        Raises ``ValueError`` if no schema_config has been saved yet - the
        onboarding wizard must call ``detect_schema`` + ``save_schema`` first.
        """
        if self._schema_config is None:
            raise ValueError(
                f"PostgresConnector for tenant {self.tenant_id!r} has no "
                "saved schema_config - run onboarding first."
            )
        return self._schema_config

    def get_allowed_tables(self, role: str) -> list[str]:
        """Tables where ``role`` is in ``allowed_for_roles``."""
        schema = self.get_schema()
        out: list[str] = []
        for t in schema.get("tables", []):
            roles = t.get("allowed_for_roles", [])
            if role in roles:
                out.append(t["name"])
        return out

    # ── read path ────────────────────────────────────────────────────────────
    async def execute_readonly_query(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a (post-rewrite) SELECT on the tenant's Postgres.

        Defense in depth: re-parse the SQL with sqlglot and refuse anything
        that is not a SELECT. The sqlglot rewriter has already enforced
        scoping; this is our second layer. A third layer is the Postgres
        role itself - tenants are encouraged to use a read-only role in
        their connection URL (we don't enforce it here because some tenants
        may share a connection string).
        """
        try:
            ast = sqlglot.parse_one(sql, dialect="postgres")
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"unparseable SQL: {exc}") from exc
        if not isinstance(ast, sqlglot.exp.Select):
            raise ValueError(
                f"execute_readonly_query rejected non-SELECT statement: {type(ast).__name__}"
            )

        async with self.engine.connect() as conn:
            stmt = text(sql)
            if params:
                result = await conn.execute(stmt, params)
            else:
                result = await conn.execute(stmt)
            columns: list[str] = list(result.keys())
            rows: list[Any] = [list(r) for r in result.fetchall()]
            rowcount = len(rows)
        return QueryResult(
            columns=columns,
            rows=rows,
            rowcount=rowcount,
            executed_sql=sql,
        )

    # ── write path (Phase 4) ─────────────────────────────────────────────────
    async def call_business_action(
        self,
        name: str,
        params: dict[str, Any],
    ) -> ActionResult:
        raise NotImplementedError(
            "Business actions are wired in Phase 4 (human-in-the-loop queue)."
        )

    # ── onboarding helpers ──────────────────────────────────────────────────
    async def test_connection(self) -> dict[str, Any]:
        """Test the connection - returns ``{ok, error, tables_count}``.

        Used by the onboarding wizard before saving the URL. Does NOT
        load the schema (use ``detect_schema`` for that). Closes the
        engine after the test so we don't leak a connection pool per
        failed test.
        """
        try:
            # Quick check that asyncpg is importable - if it isn't, the
            # create_async_engine call below would fail with a less clear
            # error.
            import asyncpg  # noqa: F401
        except ImportError as exc:
            return {
                "ok": False,
                "error": "PostgreSQL support requires asyncpg (pip install asyncpg)",
                "tables_count": 0,
            }
        try:
            engine = self.engine
            async with engine.connect() as conn:
                r = await conn.execute(text("SELECT 1"))
                _ = r.scalar() if hasattr(r, "scalar") else None
                # Count user tables (exclude system schemas).
                r2 = await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                        "AND table_type = 'BASE TABLE'"
                    )
                )
                tables_count = int(r2.scalar() or 0)
            return {"ok": True, "error": None, "tables_count": tables_count}
        except Exception as exc:  # noqa: BLE001 - surface any error to the wizard
            logger.warning(
                "PostgresConnector.test_connection failed for tenant=%s: %s",
                self.tenant_id, exc,
            )
            return {"ok": False, "error": str(exc), "tables_count": 0}
        finally:
            await self._dispose()

    async def detect_schema(self) -> dict:
        """Auto-detect the tenant's schema by querying information_schema.

        Returns a dict in the same shape as ``app/schema.yaml``::

            {
              "metadata": {"tenant_id": "<tenant>", "schema_version": "auto"},
              "tables": [
                {
                  "name": "orders",
                  "description": "Table orders",
                  "tenant_scope_column": null,
                  "allowed_for_roles": ["producer", "admin"],
                  "columns": [
                    {"name": "id", "type": "integer", "description": "..."},
                    ...
                  ],
                  "joins_to": [],
                },
                ...
              ],
              "forbidden_tables": [],
              "business_actions": [],
            }

        The user is expected to review + edit the draft (the onboarding
        wizard lets them unselect tables, set the scope column, etc.)
        before ``save_schema`` persists it.
        """
        try:
            import asyncpg  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL support requires asyncpg (pip install asyncpg)"
            ) from exc

        engine = self.engine
        try:
            async with engine.connect() as conn:
                # Tables - exclude system schemas.
                t_res = await conn.execute(
                    text(
                        "SELECT table_name, table_schema FROM information_schema.tables "
                        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                        "AND table_type = 'BASE TABLE' "
                        "ORDER BY table_schema, table_name"
                    )
                )
                table_rows = t_res.fetchall()
                # Columns - one row per (table_schema, table_name, column_name).
                c_res = await conn.execute(
                    text(
                        "SELECT table_name, column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                        "ORDER BY table_name, ordinal_position"
                    )
                )
                col_rows = c_res.fetchall()
        finally:
            await self._dispose()

        # Group columns by table.
        cols_by_table: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            tname = r[0]
            cname = r[1]
            ctype = r[2]
            nullable = r[3]
            cols_by_table.setdefault(tname, []).append(
                {
                    "name": cname,
                    "type": _pg_type_to_schema(ctype),
                    "description": f"Column {cname} of type {ctype} (nullable={nullable}).",
                }
            )

        tables: list[dict[str, Any]] = []
        for r in table_rows:
            tname = r[0]
            # Heuristic: if the table has a `producer_id` column, use it as
            # the scope column (matches the DP convention). Otherwise no
            # row-level scope.
            cols = cols_by_table.get(tname, [])
            col_names = [c["name"] for c in cols]
            scope_col = "producer_id" if "producer_id" in col_names else None
            tables.append(
                {
                    "name": tname,
                    "description": f"Table {tname} (auto-détectée).",
                    "tenant_scope_column": scope_col,
                    "allowed_for_roles": ["producer", "admin"],
                    "columns": cols,
                    "joins_to": [],
                }
            )

        return {
            "metadata": {
                "tenant_id": self.tenant_id,
                "schema_version": "auto-detect",
                "description": (
                    "Schéma auto-détecté depuis information_schema - à valider "
                    "par l'administrateur du tenant."
                ),
                "default_limit": 1000,
            },
            "tables": tables,
            "forbidden_tables": [],
            "business_actions": [],
        }


def _pg_type_to_schema(pg_type: str) -> str:
    """Map a Postgres data_type (from information_schema.columns) to the
    coarse type vocabulary used by ``schema.yaml``.

    The schema vocabulary is small (``integer``, ``decimal``, ``varchar``,
    ``boolean``, ``timestamp``, ``text``) so the agent prompt stays compact.
    Unknown types fall back to ``text``.
    """
    t = (pg_type or "").lower()
    if t in ("integer", "int", "int4", "int2", "smallint", "bigint", "int8"):
        return "integer"
    if t in (
        "numeric", "decimal", "real", "double precision", "float", "float4", "float8",
        "money",
    ):
        return "decimal"
    if t in ("boolean", "bool"):
        return "boolean"
    if t in (
        "timestamp", "timestamp without time zone", "timestamp with time zone",
        "timestamptz",
    ):
        return "timestamp"
    if t in ("date", "time", "time without time zone"):
        return "timestamp"
    if t in ("character varying", "varchar", "character", "char", "bpchar", "uuid"):
        return "varchar"
    return "text"
