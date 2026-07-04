"""CsvConnector — Connector backed by a tenant's uploaded CSV file.

Phase 6b onboarding backend — the connector used by tenants who upload a CSV
file during onboarding (the easiest path to demo the platform without
standing up a Postgres). The connector:

1. Reads the CSV file with pandas (header + first N rows for type inference).
2. Loads the CSV into a per-tenant in-memory SQLite table (the connector
   owns its own async engine — it does NOT touch the demo's ``dev.db``).
3. Exposes the same ``execute_readonly_query`` contract as the other
   connectors so the sqlglot rewriter + SqlReadTool work unchanged.
4. Auto-detects the schema (column names + inferred types: int, float, text)
   — used by the onboarding wizard's "detect schema" step.
5. Tests the file is readable — used by the onboarding wizard's "test
   connection" step.

Per-tenant SQLite files are stored under ``/tmp/tevet7_csv/<tenant_id>.db``
so the data survives across requests in the same process (a fresh in-memory
DB would lose its data on every request). The CSV is re-loaded only once
per file path (lazy, cached by the connector instance).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import sqlglot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.connectors.base import ActionResult, Connector, QueryResult

logger = logging.getLogger("tevet7.connectors.csv")

# Directory where per-tenant SQLite files are stored. Created lazily.
_CSV_DIR = Path(tempfile.gettempdir()) / "tevet7_csv"


def _ensure_csv_dir() -> Path:
    """Ensure the per-tenant SQLite directory exists, return its path."""
    _CSV_DIR.mkdir(parents=True, exist_ok=True)
    return _CSV_DIR


def _tenant_db_path(tenant_id: str) -> Path:
    """Return the on-disk SQLite path for a CSV-backed tenant."""
    # Sanitize the tenant_id (lowercase letters/digits/hyphens only —
    # enforced at tenant creation, but defensive here too).
    safe = "".join(c for c in tenant_id if c.isalnum() or c in "-_")
    if not safe:
        safe = "tenant"
    return _ensure_csv_dir() / f"{safe}.db"


def _infer_sqlite_type(values: list[Any]) -> str:
    """Infer the SQLite column type from a sample of values.

    Returns ``"INTEGER"``, ``"REAL"``, or ``"TEXT"``. A column is INTEGER
    if every non-empty value parses as an int; REAL if every non-empty
    value parses as a float (int or float); TEXT otherwise.
    """
    seen_any = False
    all_int = True
    all_float = True
    for v in values:
        if v is None or v == "" or (isinstance(v, float) and v != v):
            continue
        seen_any = True
        s = str(v).strip()
        if all_int:
            try:
                int(s)
            except (ValueError, TypeError):
                all_int = False
        if all_float:
            try:
                float(s)
            except (ValueError, TypeError):
                all_float = False
        if not all_int and not all_float:
            break
    if not seen_any:
        return "TEXT"
    if all_int:
        return "INTEGER"
    if all_float:
        return "REAL"
    return "TEXT"


def _coerce_value(raw: Any, col_type: str) -> Any:
    """Coerce a CSV string value to the inferred Python type."""
    if raw is None or raw == "":
        return None
    s = str(raw)
    if col_type == "INTEGER":
        try:
            return int(s)
        except (ValueError, TypeError):
            return s
    if col_type == "REAL":
        try:
            return float(s)
        except (ValueError, TypeError):
            return s
    return s


class CsvConnector(Connector):
    """Connector backed by a tenant's uploaded CSV file.

    Parameters
    ----------
    tenant_id:
        The tenant id this connector belongs to.
    csv_path:
        Absolute path to the uploaded CSV file. The onboarding wizard
        saves uploads to ``/tmp/tevet7_csv/<tenant_id>.csv`` and stores
        that path in ``tenant_configs.csv_path``.
    schema_config:
        The tenant's saved schema_config dict (same shape as
        ``app/schema.yaml``). May be ``None`` during the onboarding
        wizard's "detect schema" step (before ``save_schema`` has run).
    """

    def __init__(
        self,
        tenant_id: str,
        csv_path: str,
        schema_config: dict | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.csv_path = csv_path
        self._schema_config: dict | None = schema_config
        self._engine: AsyncEngine | None = None
        self._loaded = False  # has the CSV been loaded into the SQLite file?

    # ── engine plumbing ──────────────────────────────────────────────────────
    @property
    def engine(self) -> AsyncEngine:
        """Lazy-create the per-tenant SQLite engine + load the CSV once."""
        if self._engine is None:
            db_path = _tenant_db_path(self.tenant_id)
            url = f"sqlite+aiosqlite:///{db_path}"
            self._engine = create_async_engine(url, echo=False, future=True)
        if not self._loaded:
            # Synchronous load — pandas + csv are sync; we do it once on
            # the first engine access. Errors propagate up (caller will
            # see them in test_connection / detect_schema).
            self._load_csv_into_sqlite()
            self._loaded = True
        return self._engine

    def _load_csv_into_sqlite(self) -> None:
        """Read the CSV with pandas and load it into the per-tenant SQLite.

        Idempotent: if the table already exists in the SQLite file (a
        previous request already loaded it), we skip the load. The
        onboarding wizard calls ``connect_csv`` which forces a re-load by
        deleting the SQLite file first.
        """
        import pandas as pd  # local import — pandas is heavy
        from sqlalchemy import create_engine as _sync_create_engine

        if not os.path.exists(self.csv_path):
            raise FileNotFoundError(f"CSV file not found: {self.csv_path}")

        db_path = _tenant_db_path(self.tenant_id)
        # Sync engine — pandas' to_sql is sync-only.
        sync_url = f"sqlite:///{db_path}"
        sync_engine = _sync_create_engine(sync_url, future=True)
        try:
            # Check if the table already exists — if so, skip the load.
            with sync_engine.connect() as conn:
                from sqlalchemy import inspect as _inspect
                inspector = _inspect(sync_engine)
                existing = inspector.get_table_names()
            table_name = self._infer_table_name()
            if table_name in existing:
                logger.info(
                    "CsvConnector: table %s already loaded for tenant=%s — skipping",
                    table_name, self.tenant_id,
                )
                return
            # Read the CSV and write it to the SQLite file.
            df = pd.read_csv(self.csv_path)
            df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
            df.to_sql(table_name, sync_engine, index=False, if_exists="replace")
            logger.info(
                "CsvConnector: loaded %d rows × %d cols from %s into %s (table=%s)",
                len(df), len(df.columns), self.csv_path, db_path, table_name,
            )
        finally:
            sync_engine.dispose()

    def _infer_table_name(self) -> str:
        """Derive a SQLite table name from the CSV filename."""
        base = os.path.basename(self.csv_path)
        name, _ = os.path.splitext(base)
        # Sanitize: lowercase, replace non-alphanumeric with underscore.
        safe = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
        if not safe:
            safe = "data"
        return safe

    async def _dispose(self) -> None:
        if self._engine is not None:
            try:
                await self._engine.dispose()
            except Exception:  # noqa: BLE001
                logger.warning("CsvConnector dispose failed", exc_info=True)
        self._engine = None
        self._loaded = False

    # ── schema discovery ─────────────────────────────────────────────────────
    def get_schema(self) -> dict:
        """Return the tenant's saved schema_config dict."""
        if self._schema_config is None:
            raise ValueError(
                f"CsvConnector for tenant {self.tenant_id!r} has no saved "
                "schema_config — run onboarding first."
            )
        return self._schema_config

    def get_allowed_tables(self, role: str) -> list[str]:
        """Tables where ``role`` is in ``allowed_for_roles``.

        If no table has ``allowed_for_roles`` set (e.g. the schema was
        saved via the onboarding wizard which doesn't set it), all tables
        are allowed — the scoping is enforced by the sqlglot rewriter.
        """
        schema = self.get_schema()
        out: list[str] = []
        has_roles = False
        for t in schema.get("tables", []):
            roles = t.get("allowed_for_roles", [])
            if roles:
                has_roles = True
                if role in roles:
                    out.append(t["name"])
            else:
                # No roles restriction → all tables allowed.
                out.append(t["name"])
        return out

    # ── read path ────────────────────────────────────────────────────────────
    async def execute_readonly_query(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a (post-rewrite) SELECT on the per-tenant SQLite.

        Defense in depth: re-parse with sqlglot and refuse anything that
        is not a SELECT (the CSV SQLite has no concept of a read-only
        role, so this is our second layer after the rewriter).
        """
        try:
            ast = sqlglot.parse_one(sql, dialect="sqlite")
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
        """Test that the CSV file exists + is readable. Returns
        ``{ok, error, tables_count}`` — ``tables_count`` is 1 (a CSV
        yields exactly one table).
        """
        try:
            if not os.path.exists(self.csv_path):
                return {
                    "ok": False,
                    "error": f"CSV file not found: {self.csv_path}",
                    "tables_count": 0,
                }
            # Try reading the first few rows to confirm it's a valid CSV.
            import pandas as pd
            df = pd.read_csv(self.csv_path, nrows=5)
            if df.empty:
                return {
                    "ok": False,
                    "error": "CSV file has no columns or no rows.",
                    "tables_count": 0,
                }
            return {
                "ok": True,
                "error": None,
                "tables_count": 1,
                "rows_preview": df.head(3).to_dict(orient="records"),
                "columns": list(df.columns),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "CsvConnector.test_connection failed for tenant=%s: %s",
                self.tenant_id, exc,
            )
            return {"ok": False, "error": str(exc), "tables_count": 0}

    async def detect_schema(self) -> dict:
        """Auto-detect the schema by reading the CSV header + inferring types.

        Returns a dict in the same shape as ``app/schema.yaml``. The CSV
        yields a single table whose name is derived from the filename.
        Each column's type is inferred from a sample of values (int →
        float → text fallback).
        """
        import pandas as pd

        if not os.path.exists(self.csv_path):
            raise FileNotFoundError(f"CSV file not found: {self.csv_path}")
        # Read up to 1000 rows for type inference (cheap and accurate enough).
        df = pd.read_csv(self.csv_path, nrows=1000)
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
        table_name = self._infer_table_name()

        # Infer types per column.
        columns: list[dict[str, Any]] = []
        for col in df.columns:
            col_type = _infer_sqlite_type(df[col].tolist())
            columns.append(
                {
                    "name": str(col),
                    "type": _sqlite_type_to_schema(col_type),
                    "description": f"Column {col} of type {col_type}.",
                }
            )

        # Heuristic scope column: a column literally named `producer_id`
        # (case-insensitive) is the row-level scope.
        col_names = [c["name"] for c in columns]
        scope_col = "producer_id" if "producer_id" in col_names else None

        return {
            "metadata": {
                "tenant_id": self.tenant_id,
                "schema_version": "auto-detect-csv",
                "description": (
                    f"Schéma auto-détecté depuis le fichier CSV « {os.path.basename(self.csv_path)} » "
                    "— à valider par l'administrateur du tenant."
                ),
                "default_limit": 1000,
            },
            "tables": [
                {
                    "name": table_name,
                    "description": f"Table {table_name} (auto-détectée depuis le CSV).",
                    "tenant_scope_column": scope_col,
                    "allowed_for_roles": ["producer", "admin"],
                    "columns": columns,
                    "joins_to": [],
                }
            ],
            "forbidden_tables": [],
            "business_actions": [],
        }


def _sqlite_type_to_schema(sqlite_type: str) -> str:
    """Map a SQLite storage type to the schema.yaml type vocabulary."""
    t = (sqlite_type or "").upper()
    if t == "INTEGER":
        return "integer"
    if t == "REAL":
        return "decimal"
    return "text"
