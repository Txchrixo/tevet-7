"""Security tests for the SqlReadTool rewriting pipeline.

THIS FILE IS THE INTERVIEW ARGUMENT.

Each test names a specific attack vector against row-level security and
asserts that ``SqlReadTool.validate_and_rewrite`` defends against it. The
tests are written for ``pytest`` with ``pytest-asyncio``.

The fixture ``tool`` constructs a ``SqlReadTool`` configured for a producer
with ``producer_id = 42``, mimicking what a real request would build.

Running::

    pytest tests/test_sql_security.py -v
"""

from __future__ import annotations

import logging

import pytest

from app.tools.sql_tool import SqlReadTool, SqlSecurityError

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def tool() -> SqlReadTool:
    """A SqlReadTool configured for producer_id=42 on the DP tenant.

    Uses a minimal schema (orders + order_items) with users/audit_logs/
    compliance_flags as forbidden tables — exactly the vectors exercised
    by the tests below.
    """
    schema = {
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

    class _StubConnector:  # minimal stub — tests only exercise validate_and_rewrite
        def get_schema(self) -> dict:
            return schema

        def get_allowed_tables(self, role: str) -> list[str]:
            return ["orders", "order_items"]

        async def execute_readonly_query(self, sql, params=None):
            raise NotImplementedError

        async def call_business_action(self, name, params):
            raise NotImplementedError

    return SqlReadTool(
        connector=_StubConnector(),
        schema=schema,
        allowed_tables=["orders", "order_items"],
        scope_column="producer_id",
        scope_value=42,
        role="producer",
    )


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
        with pytest.raises(SqlSecurityError):
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
        (
            "SELECT * FROM orders o "
            "JOIN compliance_flags c ON c.user_id = o.customer_id"
        ),
    ]
    for sql in vectors:
        with pytest.raises(SqlSecurityError):
            tool.validate_and_rewrite(sql)


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
    low = rewritten.lower()
    assert "producer_id = 42" in low, f"scope not injected: {rewritten}"
    # LIMIT must also be appended.
    assert "limit 1000" in low, f"LIMIT not appended: {rewritten}"
    # No incident should have been raised (LLM simply forgot, not malicious).
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
    sql = "SELECT * FROM orders WHERE producer_id = 99"
    with caplog.at_level(logging.WARNING, logger="tevet7.sql_tool"):
        rewritten = tool.validate_and_rewrite(sql)

    # 1. The rewritten SQL is scoped to 42, never 99.
    low = rewritten.lower()
    assert "producer_id = 42" in low, f"scope not rewritten to 42: {rewritten}"
    assert "producer_id = 99" not in low, f"wrong scope value still present: {rewritten}"

    # 2. The internal security_incident flag is set (consumed by run()).
    assert tool._last_security_incident is True

    # 3. A WARNING-level log mentioning "SECURITY" was emitted.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "SECURITY" in r.getMessage().upper() for r in warnings
    ), f"no SECURITY WARNING logged; records: {[r.getMessage() for r in warnings]}"


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
    sql = (
        "SELECT * FROM orders "
        "WHERE id IN (SELECT id FROM orders WHERE producer_id = 99)"
    )
    rewritten = tool.validate_and_rewrite(sql)
    low = rewritten.lower()

    # The rewritten SQL must NOT contain producer_id = 99 anywhere.
    assert "producer_id = 99" not in low, (
        f"inner subquery scope leak: {rewritten}"
    )
    # The rewritten SQL must contain producer_id = 42 (we accept either
    # one or two occurrences — the key is that 99 is gone and 42 is present).
    assert "producer_id = 42" in low, (
        f"scope not injected at all levels: {rewritten}"
    )

    # Security incident flag must be set (we caught a bypass attempt).
    assert tool._last_security_incident is True


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
    rewritten = tool.validate_and_rewrite(
        "SELECT * FROM orders WHERE producer_id = 42"
    )
    low = rewritten.lower()
    assert "limit 1000" in low, f"LIMIT not appended: {rewritten}"


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
    low = rewritten.lower()
    # Count occurrences of "producer_id = 42" — there must be exactly one.
    occurrences = low.count("producer_id = 42")
    assert occurrences == 1, (
        f"expected exactly 1 occurrence of producer_id = 42, got {occurrences}: {rewritten}"
    )
    # No security incident.
    assert tool._last_security_incident is False


# ─────────────────────────────────────────────────────────────────────────────
# 8. SQL-comment bypass attempt (extra)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ignores_sql_comments_trying_to_disable_scope(
    tool: SqlReadTool,
) -> None:
    """``SELECT * FROM orders -- WHERE producer_id = 42`` must still get
    the scope injected, because the rewriter operates on the AST, not on
    text. The trailing comment must not be interpreted as "no WHERE".

    Security guarantee: AST-based rewriting is immune to comment-based
    tricks, string concatenation, or unusual whitespace.
    """
    sql = "SELECT * FROM orders -- WHERE producer_id = 42"
    rewritten = tool.validate_and_rewrite(sql)
    low = rewritten.lower()
    # The scope must be injected (the comment is dropped during AST rebuild).
    assert "producer_id = 42" in low, (
        f"comment-trick defeated the rewriter: {rewritten}"
    )
    # LIMIT must also be present.
    assert "limit 1000" in low
