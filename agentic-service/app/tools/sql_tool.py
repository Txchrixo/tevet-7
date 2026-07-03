"""SqlReadTool — the most important tool in Tevet-7.

SECURITY NOTES
==============

We **never trust the LLM** for security. The LLM is asked to produce SQL, but
that SQL is **parsed, validated, and rewritten** by `sqlglot` *before* it is
ever sent to the database. This is the row-level security guarantee per
tenant.

The rewriting pipeline (see ``validate_and_rewrite``) enforces:

1. **Statement kind.** Only ``SELECT`` (and ``WITH ... SELECT``) is allowed.
   ``INSERT`` / ``UPDATE`` / ``DELETE`` / ``DROP`` / ``TRUNCATE`` / ``ALTER``
   / any DDL is rejected.
2. **Table allowlist.** Only tables in ``allowed_tables`` may be referenced,
   anywhere in the query (including subqueries, JOINs, CTEs). The forbidden
   list (``users``, ``audit_logs``, ...) is rejected even for admins.
3. **Row-level scoping.** For every producer-scoped table referenced, the
   query must include ``WHERE {scope_column} = {scope_value}`` at the top
   level **and** inside every subquery that touches the same table. If the
   LLM produced a query missing the filter (or with a wrong value), the
   rewriter injects the correct one and logs a ``SECURITY WARNING`` — the
   attempt is treated as a security event for audit purposes.
4. **Result limit.** ``LIMIT {default_limit}`` is appended if not present.
5. **No dangerous functions.** ``pg_sleep``, ``lo_import``, ``pg_read_file``,
   ``COPY``, ``CREATE``, etc. are stripped/rejected.

Because the rewrite is deterministic and based on AST manipulation (not
regex), it cannot be defeated by SQL comments, string tricks, or unusual
formatting.

On top of this, the connector opens a **read-only Postgres role** per
tenant, so even a hypothetical bypass of the rewriter cannot lead to writes.

The combination "LLM generates + sqlglot rewrites + read-only role" is the
three-layer defense in depth we pitch to enterprise customers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.connectors.base import Connector, QueryResult

logger = logging.getLogger("tevet7.sql_tool")

# ─────────────────────────────────────────────────────────────────────────────
# Result type returned to the orchestrator
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ToolResult:
    """Structured result returned by SqlReadTool.run() to the agent.

    Fields mirror what the Producer Copilot prompt expects in its response
    schema (``sql_used``, ``sources``, etc.).
    """

    success: bool
    query_result: QueryResult | None = None
    error: str | None = None
    # The natural-language question that triggered this tool call — useful
    # for Langfuse attribution and for the agent to cite back to the user.
    question: str | None = None
    # Tables this query actually touched (post-rewrite). Used to populate
    # the agent's `sources` field.
    tables_touched: list[str] = field(default_factory=list)
    # Number of times the rewriter had to fix the LLM's SQL (e.g. inject
    # scope, add LIMIT, drop forbidden table). Non-zero => log a warning.
    rewrites_applied: int = 0
    # True if the rewriter caught an attempt to bypass row-level security.
    security_incident: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class SqlSecurityError(Exception):
    """Raised when the LLM-generated SQL violates a security rule.

    The orchestrator turns this into a polite refusal to the user, and we
    log it as a security event for audit.
    """


class SqlGenerationError(Exception):
    """Raised when the LLM fails to produce parseable SQL."""


# ─────────────────────────────────────────────────────────────────────────────
# The tool
# ─────────────────────────────────────────────────────────────────────────────


class SqlReadTool:
    """Read-only SQL tool with mandatory row-level scoping.

    Construction
    ------------
    The tool is constructed **per request** with the verified identity of the
    caller (``scope_value`` comes from the JWT, never from the request body)::

        tool = SqlReadTool(
            connector=tenant_connector,
            schema=loaded_schema_dict,
            allowed_tables=connector.get_allowed_tables(role="producer"),
            scope_column="producer_id",
            scope_value=42,                       # from JWT
        )

    Pipeline
    --------
    ``run(question)`` orchestrates three steps:

    1. ``generate_sql(question)`` — ask the LLM to translate the question
       into SQL, given the schema (compact text form) and the few-shot
       examples in the system prompt.
    2. ``validate_and_rewrite(sql)`` — sqlglot parses the SQL, applies the
       five security checks described in the module docstring, and returns
       the rewritten SQL.
    3. ``execute(sql)`` — the connector runs the rewritten SQL on its
       read-only connection.

    Phase 0 status: methods are stubbed with detailed TODOs. The signatures
    and the security contract are stable; only the bodies change in Phase 1.
    """

    # Default result limit if the schema doesn't override it.
    DEFAULT_LIMIT = 1000

    def __init__(
        self,
        connector: Connector,
        schema: dict[str, Any],
        allowed_tables: list[str],
        scope_column: str,
        scope_value: int | str,
        llm_client: Any | None = None,
    ) -> None:
        self.connector = connector
        self.schema = schema
        self.allowed_tables = set(allowed_tables)
        # Forbidden tables are tenant-wide: nobody, not even admins, may
        # query them via the agent (they're reserved for the control plane).
        self.forbidden_tables = set(schema.get("forbidden_tables", []))
        self.scope_column = scope_column
        self.scope_value = scope_value
        self.default_limit = schema.get("metadata", {}).get("default_limit", self.DEFAULT_LIMIT)
        self.llm_client = llm_client

    # ───────────────────────────────────────────────────────────────────────
    # Step 1 — SQL generation (LLM)
    # ───────────────────────────────────────────────────────────────────────
    async def generate_sql(self, question: str) -> str:
        """Ask the LLM to translate ``question`` into a SQL SELECT.

        The prompt includes:
        - The allowed tables + their columns (compact text form).
        - The scope column + the scope value (so the model can pre-inject it
          — though the rewriter will catch it if the model forgets).
        - A few-shot example or two.

        Returns the raw SQL string. Does NOT validate it — that's the
        rewriter's job.

        TODO(Phase 1):
          - Build the schema-as-text representation (cache per-tenant).
          - Call OpenAI with the sql_read_tool function schema.
          - Parse the tool call result, fall back to a second attempt if
            the model returns malformed SQL.
        """
        raise NotImplementedError("Phase 1: wire up the OpenAI call.")

    # ───────────────────────────────────────────────────────────────────────
    # Step 2 — Validation & rewriting (sqlglot)
    # ───────────────────────────────────────────────────────────────────────
    async def validate_and_rewrite(self, sql: str) -> str:
        """Parse ``sql`` with sqlglot and return a safe, rewritten SQL string.

        Pipeline (all checks raise ``SqlSecurityError`` on violation):

        a) Parse. If unparseable, raise ``SqlGenerationError``.
        b) Reject if the statement is anything other than SELECT
           (no INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER/...).
        c) Walk the AST: collect every table referenced (top-level, JOINs,
           subqueries, CTEs). Reject if any is in ``forbidden_tables`` or
           not in ``allowed_tables``.
        d) For every producer-scoped table (those with
           ``tenant_scope_column`` in the schema), ensure the WHERE clause
           (at every level that touches the table) includes
           ``{scope_column} = {scope_value}``. If missing or wrong:
              - rewrite the AST to inject the correct predicate,
              - increment ``rewrites_applied``,
              - if the existing predicate used a *different* scope value
                (the LLM tried to bypass), set ``security_incident=True``
                and log a ``SECURITY WARNING`` — but still return a safe
                query (scoped to the right producer) so the user gets an
                answer and we get an audit trail.
        e) Reject dangerous function calls (``pg_sleep``, ``lo_import``,
           ``pg_read_file``, ``COPY``).
        f) If no ``LIMIT`` is present, append ``LIMIT {default_limit}``.

        Returns the rewritten SQL as a string.

        TODO(Phase 1):
          - Use ``sqlglot.parse_one(sql, dialect="postgres")``.
          - Walk with ``ast.find_all(exp.Table)`` for table collection.
          - Use ``ast.find_all(exp.Where)`` to inspect predicates.
          - Inject scope predicates via ``ast.where(...)``.
          - Add the LIMIT via ``ast.set("limit", exp.Limit(...))``.
        """
        raise NotImplementedError("Phase 1: implement the sqlglot rewrite pipeline.")

    # ───────────────────────────────────────────────────────────────────────
    # Step 3 — Execution (Connector)
    # ───────────────────────────────────────────────────────────────────────
    async def execute(self, sql: str) -> QueryResult:
        """Run the rewritten SQL via the connector's read-only connection.

        ``sql`` must already have been through ``validate_and_rewrite``;
        we do NOT re-validate here (the contract is that the orchestrator
        calls the steps in order).
        """
        return await self.connector.execute_readonly_query(sql)

    # ───────────────────────────────────────────────────────────────────────
    # Orchestrator entry point
    # ───────────────────────────────────────────────────────────────────────
    async def run(self, question: str) -> ToolResult:
        """End-to-end: question -> SQL -> rewrite -> execute -> ToolResult.

        Catches ``SqlSecurityError`` and ``SqlGenerationError`` and converts
        them to a ``ToolResult`` with ``success=False`` so the agent can
        explain the failure to the user without crashing.
        """
        try:
            raw_sql = await self.generate_sql(question)
            safe_sql = await self.validate_and_rewrite(raw_sql)
            result = await self.execute(safe_sql)
            return ToolResult(
                success=True,
                query_result=result,
                question=question,
                tables_touched=self._extract_tables(safe_sql),
            )
        except SqlSecurityError as exc:
            # Security violations are logged at WARNING with the offending
            # SQL redacted (we keep the structure, drop the values).
            logger.warning(
                "SqlSecurityError for scope_value=%s: %s", self.scope_value, exc
            )
            return ToolResult(
                success=False,
                error=str(exc),
                question=question,
                security_incident=True,
            )
        except SqlGenerationError as exc:
            logger.info("SqlGenerationError: %s", exc)
            return ToolResult(success=False, error=str(exc), question=question)
        except Exception as exc:  # noqa: BLE001 — surface to agent, don't crash
            logger.exception("Unexpected error in SqlReadTool.run")
            return ToolResult(success=False, error=f"unexpected: {exc!r}", question=question)

    # ───────────────────────────────────────────────────────────────────────
    # Helpers
    # ───────────────────────────────────────────────────────────────────────
    def _extract_tables(self, sql: str) -> list[str]:
        """Return the list of tables actually referenced in ``sql``.

        Used to populate ``ToolResult.tables_touched``. In Phase 1 this will
        reuse the AST walk from ``validate_and_rewrite`` (we'll cache the
        parsed tree on the result instead of re-parsing).
        """
        # TODO(Phase 1): implement with sqlglot.
        return []
