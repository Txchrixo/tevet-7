"""Column-level access control tests for SqlReadTool.

Phase 1 of "provable in-scope compilation": beyond row-level scoping, a
scoped role may be denied specific columns (e.g. a "driver" denied
"revenue"). The rewriter must reject any reference to a denied column
ANYWHERE in the AST and expand ``SELECT *`` to the allowed columns.
"""

from __future__ import annotations

import pytest
import sqlglot
from sqlglot import exp

from app.tools.sql_tool import SqlReadTool, SqlSecurityError

SCHEMA = {
    "metadata": {"default_limit": 1000},
    "tables": [
        {
            "name": "deliveries",
            "tenant_scope_column": "driver_id",
            "allowed_for_roles": ["driver", "admin"],
            "columns": [
                {"name": "id", "type": "integer"},
                {"name": "driver_id", "type": "integer"},
                {"name": "city", "type": "text"},
                {"name": "price_eur", "type": "decimal"},
                {"name": "revenue", "type": "decimal"},
                {"name": "cost", "type": "decimal"},
            ],
        },
    ],
    "forbidden_tables": [],
}


def _tool(denied: list[str] | None = None, role: str = "driver") -> SqlReadTool:
    return SqlReadTool(
        connector=None,
        schema=SCHEMA,
        allowed_tables=["deliveries"],
        scope_column="driver_id",
        scope_value=7,
        role=role,
        denied_columns=denied,
    )


def _cols(sql: str) -> set[str]:
    ast = sqlglot.parse_one(sql, dialect="sqlite")
    return {c.name for c in ast.find_all(exp.Column)}


# ── Reject denied columns wherever they appear ───────────────────────────────

@pytest.mark.parametrize("sql", [
    "SELECT revenue FROM deliveries",
    "SELECT id, revenue FROM deliveries",
    "SELECT id FROM deliveries WHERE revenue > 100",
    "SELECT id FROM deliveries ORDER BY revenue DESC",
    "SELECT city, SUM(revenue) FROM deliveries GROUP BY city",
    "SELECT city FROM deliveries GROUP BY city HAVING SUM(revenue) > 10",
    "SELECT id FROM deliveries WHERE id IN (SELECT id FROM deliveries WHERE revenue > 5)",
    "SELECT revenue AS r FROM deliveries",
    "SELECT ROUND(revenue, 2) FROM deliveries",
])
def test_denied_column_rejected_everywhere(sql: str) -> None:
    tool = _tool(denied=["revenue"])
    with pytest.raises(SqlSecurityError, match="not readable"):
        tool.validate_and_rewrite(sql)
    assert tool._last_security_incident is True


def test_multiple_denied_columns() -> None:
    tool = _tool(denied=["revenue", "cost"])
    with pytest.raises(SqlSecurityError):
        tool.validate_and_rewrite("SELECT cost FROM deliveries")


# ── Allowed columns pass (with row scope injected) ───────────────────────────

def test_allowed_columns_pass() -> None:
    tool = _tool(denied=["revenue"])
    out = tool.validate_and_rewrite("SELECT id, city, price_eur FROM deliveries")
    assert "driver_id = 7" in out
    assert "revenue" not in out.lower()


def test_derived_value_named_like_denied_is_allowed() -> None:
    """Computing a value from ALLOWED columns and aliasing it 'revenue' is
    fine - we deny access to the stored column, not the word."""
    tool = _tool(denied=["revenue"])
    out = tool.validate_and_rewrite(
        "SELECT price_eur * 1.2 AS revenue FROM deliveries"
    )
    assert "price_eur" in out.lower()
    assert "driver_id = 7" in out


# ── SELECT * expansion excludes denied columns ───────────────────────────────

def test_star_expanded_to_allowed_columns() -> None:
    tool = _tool(denied=["revenue", "cost"])
    out = tool.validate_and_rewrite("SELECT * FROM deliveries")
    cols = _cols(out)
    assert "revenue" not in cols and "cost" not in cols
    # allowed columns are present
    assert {"id", "city", "price_eur"} <= cols
    assert "driver_id = 7" in out


def test_qualified_star_expanded() -> None:
    tool = _tool(denied=["revenue"])
    out = tool.validate_and_rewrite("SELECT d.* FROM deliveries d")
    cols = _cols(out)
    assert "revenue" not in cols
    assert "price_eur" in cols


def test_star_no_denylist_untouched() -> None:
    tool = _tool(denied=None)
    out = tool.validate_and_rewrite("SELECT * FROM deliveries")
    # No column policy -> star preserved, only row scope added.
    assert "*" in out
    assert "driver_id = 7" in out


def test_star_unknown_columns_fails_closed() -> None:
    """A scoped table with no column metadata cannot have '*' safely
    expanded when a deny list exists -> reject."""
    schema = {
        "metadata": {"default_limit": 1000},
        "tables": [{
            "name": "deliveries",
            "tenant_scope_column": "driver_id",
            "allowed_for_roles": ["driver"],
            "columns": [],  # unknown
        }],
        "forbidden_tables": [],
    }
    tool = SqlReadTool(
        connector=None, schema=schema, allowed_tables=["deliveries"],
        scope_column="driver_id", scope_value=7, role="driver",
        denied_columns=["revenue"],
    )
    with pytest.raises(SqlSecurityError, match="cannot be safely expanded"):
        tool.validate_and_rewrite("SELECT * FROM deliveries")


# ── Admin is not column-restricted ───────────────────────────────────────────

def test_admin_not_column_restricted() -> None:
    tool = _tool(denied=["revenue"], role="admin")
    # admin: enforce_scope is False, so column policy does not apply.
    out = tool.validate_and_rewrite("SELECT revenue FROM deliveries")
    assert "revenue" in out.lower()
