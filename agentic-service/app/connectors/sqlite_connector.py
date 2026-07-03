"""SqliteConnector — real Connector implementation backed by aiosqlite.

Phase 1 target: drive the Producer Copilot against a fictitious SQLite
database (see ``app/db_seed.py``) so the demo runs without Postgres/Docker.

The connector is the ONLY object that touches the tenant's data. Tools
(``SqlReadTool``) go through it; they never see a connection string. The
``execute_readonly_query`` method enforces read-only-ness a second time
by refusing any statement that is not a SELECT — defense in depth on top
of the sqlglot rewriter.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import sqlglot
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.connectors.base import ActionResult, Connector, QueryResult
from app.db_seed import get_engine

logger = logging.getLogger("tevet7.connectors.sqlite")

# Path to the canonical schema.yaml — load lazily so tests can construct a
# connector without the file existing.
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.yaml"


class SqliteConnector(Connector):
    """Connector backed by the in-process SQLite database.

    The schema is loaded from ``app/schema.yaml``. The connection is shared
    with ``app.db_seed.get_engine()`` so the seeded fictitious data is
    available.
    """

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self._engine = engine

    # ── engine plumbing ──────────────────────────────────────────────────────
    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = get_engine()
        return self._engine

    # ── schema discovery ─────────────────────────────────────────────────────
    def get_schema(self) -> dict:
        """Load and return ``app/schema.yaml`` as a dict."""
        with _SCHEMA_PATH.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)

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
        """Execute a (post-rewrite) SELECT on the SQLite database.

        Defense in depth: even though the SqlReadTool has already validated
        the SQL via sqlglot, we re-parse here and refuse anything that is not
        a SELECT. SQLite itself has no read-only role concept, so this is our
        second layer.
        """
        # Parse + verify it's a SELECT (reject writes a second time).
        try:
            ast = sqlglot.parse_one(sql, dialect="sqlite")
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"unparseable SQL: {exc}") from exc
        if not isinstance(ast, sqlglot.exp.Select):
            raise ValueError(
                f"execute_readonly_query rejected non-SELECT statement: {type(ast).__name__}"
            )

        async with self.engine.connect() as conn:
            # SQLAlchemy text() with named params; we map our dict through.
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
