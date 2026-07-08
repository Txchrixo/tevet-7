"""Security tests for the SqlReadTool rewriting pipeline.

THIS FILE IS THE INTERVIEW ARGUMENT.

Each test names a specific attack vector against row-level security and
asserts that ``SqlReadTool.validate_and_rewrite`` defends against it. The
tests are written for ``pytest`` with ``pytest-asyncio``. The test names
and docstrings were locked in during Phase 0 (before the implementation
existed); the bodies below exercise the Phase 1 implementation without
any modification to those docstrings or names. If a test fails, it means
we have a security regression and the release is blocked.

Running::

    pytest tests/test_sql_security.py -v

The fixture ``tool`` constructs a ``SqlReadTool`` configured for a producer
with ``producer_id = 42``, mimicking what a real request would build.
Tests that assert on ``run()`` (the end-to-end path) inject a fixed-SQL
generator via the ``generator`` constructor parameter — the same seam the
orchestrator uses to swap rule-based and LLM generators — so no
monkeypatching is needed.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
import sqlglot
from sqlglot import exp

from app.connectors.base import QueryResult
from app.tools.sql_tool import SqlReadTool, SqlSecurityError


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA: dict[str, Any] = {
    "metadata": {"default_limit": 1000},
    "tables": [
        {
            "name": "orders",
            "tenant_scope_column": "producer_id",
            "allowed_for_roles": ["producer", "admin"],
        },
        {
            "name": "order_items",
            "tenant_scope_column": "producer_id",
            "allowed_for_roles": ["producer", "admin"],
        },
    ],
    "forbidden_tables": ["users", "audit_logs", "compliance_flags"],
}

ALLOWED_TABLES = ["orders", "order_items"]


class _StubConnector:
    """Read-only connector double: records the SQL it ran, returns no rows."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def get_schema(self) -> dict:
        return SCHEMA

    def get_allowed_tables(self, role: str) -> list[str]:
        return list(ALLOWED_TABLES)

    async def execute_readonly_query(self, sql: str, params=None) -> QueryResult:
        self.executed.append(sql)
        return QueryResult(columns=[], rows=[], rowcount=0, executed_sql=sql)

    async def call_business_action(self, name: str, params: dict) -> Any:
        raise NotImplementedError("read-only stub - no business actions")


class _FixedSQLGenerator:
    """SQLGenerator double that returns a canned SQL string.

    Simulates an LLM that produced ``sql`` (possibly malicious) so ``run()``
    tests exercise the full generate -> rewrite -> execute pipeline.
    """

    def __init__(self, sql: str) -> None:
        self._sql = sql

    async def generate(
        self,
        question: str,
        role: str,
        scope_column: str | None,
        scope_value: int | str | None,
    ) -> str:
        return self._sql


def _make_tool(generator_sql: str | None = None) -> SqlReadTool:
    """Build a SqlReadTool for producer_id=42, optionally with a fixed-SQL
    generator (for ``run()`` tests)."""
    return SqlReadTool(
        connector=_StubConnector(),
        schema=SCHEMA,
        allowed_tables=list(ALLOWED_TABLES),
        scope_column="producer_id",
        scope_value=42,
        generator=_FixedSQLGenerator(generator_sql) if generator_sql else None,
    )


@pytest.fixture
def tool() -> SqlReadTool:
    """A SqlReadTool configured for producer_id=42 on the DP tenant."""
    return _make_tool()


def _scope_values(sql: str) -> list[str]:
    """Every literal value compared to ``producer_id`` anywhere in ``sql``.

    Walks the AST (all levels: outer WHERE, subqueries, CTEs) so tests
    assert on semantics, not on string formatting details of the rewriter.
    """
    ast = sqlglot.parse_one(sql, dialect="sqlite")
    values: list[str] = []
    for eq in ast.find_all(exp.EQ):
        if isinstance(eq.left, exp.Column) and eq.left.name == "producer_id":
            values.append(str(eq.right.this if isinstance(eq.right, exp.Literal) else eq.right))
    return values


# ─────────────────────────────────────────────────────────────────────────────
# 1. Statement-kind guard
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejects_non_select_statement(tool: SqlReadTool) -> None:
    """UPDATE / DELETE / DROP / INSERT / TRUNCATE / ALTER must be rejected.

    Security guarantee: even if the LLM hallucinates a write statement
    (or is jailbroken into producing one), the tool refuses to run it.
    This is the most basic defense — read tool stays read.

    Test vectors:
      - ``UPDATE orders SET status='completed'``
      - ``DELETE FROM orders WHERE id = 1``
      - ``DROP TABLE orders``
      - ``INSERT INTO orders (...) VALUES (...)``
      - ``TRUNCATE orders``
      - ``ALTER TABLE orders DROP COLUMN producer_id``
    Each must raise ``SqlSecurityError``.
    """
    vectors = [
        "UPDATE orders SET status='completed'",
        "DELETE FROM orders WHERE id = 1",
        "DROP TABLE orders",
        "INSERT INTO orders (id, producer_id) VALUES (1, 42)",
        "TRUNCATE orders",
        "ALTER TABLE orders DROP COLUMN producer_id",
    ]
    for sql in vectors:
        with pytest.raises(SqlSecurityError, match="not allowed - only SELECT"):
            tool.validate_and_rewrite(sql)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Forbidden-table guard
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejects_forbidden_table(tool: SqlReadTool) -> None:
    """Queries on ``users``, ``audit_logs``, ``compliance_flags`` must be
    rejected — these are control-plane tables that no agent may touch.

    Security guarantee: the forbidden list is absolute. Even if an admin
    misconfigures the role allowlist, the forbidden list catches it.

    Test vectors:
      - ``SELECT * FROM users``
      - ``SELECT count(*) FROM audit_logs``
      - ``SELECT * FROM orders o JOIN compliance_flags c ON c.user_id = o.customer_id``
    """
    vectors = [
        "SELECT * FROM users",
        "SELECT count(*) FROM audit_logs",
        "SELECT * FROM orders o JOIN compliance_flags c ON c.user_id = o.customer_id",
    ]
    for sql in vectors:
        with pytest.raises(SqlSecurityError, match="Forbidden table"):
            tool.validate_and_rewrite(sql)

    # The forbidden list must also catch tables smuggled in through a CTE:
    # the CTE body references ``users`` even though the outer SELECT does not.
    with pytest.raises(SqlSecurityError):
        tool.validate_and_rewrite("WITH x AS (SELECT * FROM users) SELECT * FROM x")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Auto-inject scope when missing
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_injects_scope_when_missing(tool: SqlReadTool) -> None:
    """``SELECT * FROM orders`` (no WHERE) must become
    ``SELECT * FROM orders WHERE producer_id = 42``.

    Security guarantee: the LLM may forget the scope filter; the rewriter
    must always add it. This is the most common LLM mistake and the most
    important auto-fix.
    """
    rewritten = tool.validate_and_rewrite("SELECT * FROM orders")
    assert _scope_values(rewritten) == ["42"], (
        f"expected exactly one producer_id = 42 predicate, got: {rewritten!r}"
    )
    assert tool._last_rewrites_applied >= 1
    # A missing filter is an LLM mistake, not an attack — no incident flag.
    assert tool._last_security_incident is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Reject/rewrite wrong scope value
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejects_wrong_scope_value(
    tool: SqlReadTool, caplog: pytest.LogCaptureFixture
) -> None:
    """``SELECT * FROM orders WHERE producer_id = 99`` for user 42 must be
    rewritten to ``producer_id = 42`` AND a SECURITY WARNING must be logged.

    Security guarantee: this is the LLM trying to read another producer's
    data. We do not silently fix it — we log a security incident (so audit
    can investigate), but we still return a safe query scoped to 42 so the
    user gets a non-leaking answer rather than an error that hints at the
    existence of producer 99.

    The test asserts:
      1. The rewritten SQL contains ``producer_id = 42`` (not 99).
      2. ``ToolResult.security_incident`` is True when ``run()`` is called.
      3. A WARNING-level log record with "SECURITY" was emitted.
    """
    attack_sql = "SELECT * FROM orders WHERE producer_id = 99"

    # 1. The rewriter replaces the wrong scope value.
    with caplog.at_level(logging.WARNING, logger="tevet7.sql_tool"):
        rewritten = tool.validate_and_rewrite(attack_sql)
    assert _scope_values(rewritten) == ["42"]
    assert "99" not in rewritten

    # 2. End to end: run() surfaces the incident to the orchestrator.
    run_tool = _make_tool(generator_sql=attack_sql)
    result = await run_tool.run("montre-moi les commandes du producteur 99")
    assert result.success is True
    assert result.security_incident is True
    assert result.sql_used is not None and _scope_values(result.sql_used) == ["42"]

    # 3. The audit trail: a WARNING record mentioning SECURITY.
    security_warnings = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "SECURITY" in r.getMessage()
    ]
    assert security_warnings, "expected a WARNING log record containing 'SECURITY'"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Subquery bypass attempt
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejects_subquery_accessing_other_producer(tool: SqlReadTool) -> None:
    """Tricky bypass attempt:

        SELECT * FROM orders
        WHERE id IN (
          SELECT id FROM orders WHERE producer_id = 99
        )

    The outer WHERE has no producer_id filter at all (looks innocent); the
    inner subquery scopes to producer 99. A naive regex rewriter checking
    only the top-level WHERE would miss this.

    Security guarantee: the AST walk must find EVERY reference to a
    scoped table and ensure the scope predicate is correct at every level.
    This is why we use sqlglot AST manipulation, not regex.

    The test asserts:
      1. The rewritten SQL has ``producer_id = 42`` at both the outer and
         inner levels (or the query is rejected outright).
      2. ``ToolResult.security_incident`` is True.
    """
    attack_sql = (
        "SELECT * FROM orders "
        "WHERE id IN (SELECT id FROM orders WHERE producer_id = 99)"
    )

    # 1. Every producer_id predicate — inner AND outer — must be 42.
    rewritten = tool.validate_and_rewrite(attack_sql)
    values = _scope_values(rewritten)
    assert values, "expected at least one producer_id predicate after rewrite"
    assert set(values) == {"42"}, (
        f"expected every scope predicate to be 42, got {values} in {rewritten!r}"
    )
    assert "99" not in rewritten

    # 2. The inner rewrite is flagged as a security incident end to end.
    run_tool = _make_tool(generator_sql=attack_sql)
    result = await run_tool.run("commandes qui matchent celles du producteur 99")
    assert result.security_incident is True


# ─────────────────────────────────────────────────────────────────────────────
# 6. Auto-append LIMIT
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_adds_limit_when_missing(tool: SqlReadTool) -> None:
    """``SELECT * FROM orders WHERE producer_id = 42`` must become the same
    with ``LIMIT 1000`` appended.

    Security guarantee: prevents the LLM from accidentally DoSing the DB
    with an unbounded scan, and bounds memory usage on the connector side.
    """
    rewritten = tool.validate_and_rewrite("SELECT * FROM orders WHERE producer_id = 42")
    ast = sqlglot.parse_one(rewritten, dialect="sqlite")
    limit = ast.args.get("limit")
    assert limit is not None, f"expected a LIMIT clause, got: {rewritten!r}"
    assert limit.expression.this == "1000"

    # An explicit LIMIT chosen by the generator must be preserved, not doubled.
    kept = tool.validate_and_rewrite(
        "SELECT * FROM orders WHERE producer_id = 42 LIMIT 5"
    )
    kept_ast = sqlglot.parse_one(kept, dialect="sqlite")
    assert kept_ast.args["limit"].expression.this == "5"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Preserve correct scope (no false positives)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preserves_existing_correct_scope(tool: SqlReadTool) -> None:
    """When the LLM produces a correct ``WHERE producer_id = 42``, the
    rewriter must NOT double-inject (``WHERE producer_id = 42 AND
    producer_id = 42``) and must NOT flag a security incident.

    Security guarantee (false-positive control): correct queries pass
    through untouched (modulo LIMIT). This keeps the audit log signal-to-
    noise ratio high — every security_incident=True is a real attempt.
    """
    rewritten = tool.validate_and_rewrite(
        "SELECT * FROM orders WHERE producer_id = 42"
    )
    # Exactly ONE scope predicate — no double injection.
    assert _scope_values(rewritten) == ["42"]
    assert tool._last_security_incident is False

    # End to end: a well-behaved generator never trips the incident flag.
    run_tool = _make_tool(
        generator_sql="SELECT * FROM orders WHERE producer_id = 42"
    )
    result = await run_tool.run("mes commandes")
    assert result.success is True
    assert result.security_incident is False


# ─────────────────────────────────────────────────────────────────────────────
# 8. SQL-comment bypass attempt (extra)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ignores_sql_comments_trying_to_disable_scope(tool: SqlReadTool) -> None:
    """``SELECT * FROM orders -- WHERE producer_id = 42`` must still get
    the scope injected, because the rewriter operates on the AST, not on
    text. The trailing comment must not be interpreted as "no WHERE".

    Security guarantee: AST-based rewriting is immune to comment-based
    tricks, string concatenation, or unusual whitespace.
    """
    rewritten = tool.validate_and_rewrite(
        "SELECT * FROM orders -- WHERE producer_id = 42"
    )
    # A commented-out WHERE is not a WHERE: the real predicate was injected.
    assert _scope_values(rewritten) == ["42"]
    assert tool._last_rewrites_applied >= 1

    # Same trick with a block comment.
    rewritten2 = tool.validate_and_rewrite(
        "SELECT * FROM orders /* WHERE producer_id = 99 */"
    )
    assert _scope_values(rewritten2) == ["42"]
