"""Security tests for the SqlReadTool rewriting pipeline.

THIS FILE IS THE INTERVIEW ARGUMENT.

Each test names a specific attack vector against row-level security and
asserts that ``SqlReadTool.validate_and_rewrite`` defends against it. The
tests are written for ``pytest`` with ``pytest-asyncio``. In Phase 0 the
bodies are TODOs because ``validate_and_rewrite`` is not yet implemented —
but the INTENT of every test is crystal-clear and locked in.

When Phase 1 implements ``validate_and_rewrite``, these tests must pass
without modification to their docstrings or names. If a test fails, it
means we have a security regression and the release is blocked.

Running (once Phase 1 lands)::

    pytest tests/test_sql_security.py -v

The fixture ``tool`` constructs a ``SqlReadTool`` configured for a producer
with ``producer_id = 42``, mimicking what a real request would build.
"""

from __future__ import annotations

import pytest

# These imports will resolve once Phase 1 implements the modules. In Phase 0
# they are valid module paths; the classes exist but methods are stubs.
from app.tools.sql_tool import SqlReadTool, SqlSecurityError


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def tool() -> SqlReadTool:
    """A SqlReadTool configured for producer_id=42 on the DP tenant.

    In Phase 1 this will be built from a real Connector + the loaded
    schema.yaml. For Phase 0 we construct it with lightweight stubs so the
    test file is syntactically importable.
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

    class _StubConnector:  # pragma: no cover — replaced in Phase 1
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
    # TODO(Phase 1): implement once validate_and_rewrite is wired up.
    pytest.skip("Phase 1: implement validate_and_rewrite first.")


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
    # TODO(Phase 1): implement.
    pytest.skip("Phase 1: implement validate_and_rewrite first.")


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
    # TODO(Phase 1): implement.
    pytest.skip("Phase 1: implement validate_and_rewrite first.")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Reject/rewrite wrong scope value
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejects_wrong_scope_value(tool: SqlReadTool) -> None:
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
    # TODO(Phase 1): implement.
    pytest.skip("Phase 1: implement validate_and_rewrite first.")


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
    # TODO(Phase 1): implement.
    pytest.skip("Phase 1: implement validate_and_rewrite first.")


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
    # TODO(Phase 1): implement.
    pytest.skip("Phase 1: implement validate_and_rewrite first.")


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
    # TODO(Phase 1): implement.
    pytest.skip("Phase 1: implement validate_and_rewrite first.")


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
    # TODO(Phase 1): implement.
    pytest.skip("Phase 1: implement validate_and_rewrite first.")
