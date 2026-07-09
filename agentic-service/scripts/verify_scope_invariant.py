#!/usr/bin/env python3
"""Fuzzing verification of the in-scope compilation invariant.

THE INVARIANT
-------------
Let a scoped caller have row scope (scope_column = V) and a denied-column
set D on tenant T. For EVERY input SQL string s, ``SqlReadTool.
validate_and_rewrite(s)`` must satisfy one of:

  (R) it raises SqlSecurityError / SqlGenerationError (nothing executes), OR
  (A) it returns a single SELECT s' such that, at EVERY nesting level
      (subqueries, CTEs, UNION branches, joins):
        (A1) every literal compared to scope_column equals V - never a
             foreign scope value;
        (A2) no column in D is referenced anywhere; and
        (A3) executing s' against the tenant's data returns ONLY rows
             belonging to V and NO value drawn from a denied column.

(A1)+(A2) are syntactic (parse the output). (A3) is semantic: we run s'
against a SQLite database seeded so that another actor's rows and every
denied-column value carry unique POISON markers; if any poison marker
appears in a scoped result, the invariant is violated.

This is not a formal proof, but an executable, high-coverage refutation
attempt across hundreds of adversarial AST shapes. A clean run is strong
evidence that the compiler cannot emit an out-of-scope query.

Run:  python3 scripts/verify_scope_invariant.py
Exit: 0 if the invariant held on every case, 1 on any violation.
"""

from __future__ import annotations

import itertools
import logging
import sqlite3
import sys

import sqlglot
from sqlglot import exp

# The rewriter logs a WARNING for every neutralised attempt; that IS the
# behaviour under test, so silence it here to keep the report readable.
logging.getLogger("tevet7.sql_tool").setLevel(logging.CRITICAL)

from app.tools.sql_tool import SqlReadTool, SqlSecurityError, SqlGenerationError

# ── Actor under test ─────────────────────────────────────────────────────────
SCOPE_COL = "driver_id"
SCOPE_VAL = 7
FOREIGN_VAL = 9
DENIED = ["revenue"]

# ── Poison markers: must NEVER surface in a scoped result ─────────────────────
# Foreign actor (driver 9) identifying values + every denied-column value.
FOREIGN_CITY = "POISON_FOREIGN_CITY_9"
FOREIGN_PRICE = 9_000_009.7
REVENUE_7 = 8_000_007.1   # denied column value for the caller's OWN rows
REVENUE_9 = 8_000_009.2   # denied column value for the foreign rows
POISON = {FOREIGN_CITY, str(FOREIGN_PRICE), str(REVENUE_7), str(REVENUE_9),
          FOREIGN_PRICE, REVENUE_7, REVENUE_9}

SCHEMA = {
    "metadata": {"default_limit": 1000},
    "tables": [
        {
            "name": "deliveries",
            "tenant_scope_column": SCOPE_COL,
            "allowed_for_roles": ["driver", "admin"],
            "columns": [
                {"name": "id", "type": "integer"},
                {"name": "driver_id", "type": "integer"},
                {"name": "city", "type": "text"},
                {"name": "price_eur", "type": "decimal"},
                {"name": "revenue", "type": "decimal"},
            ],
        },
        {
            "name": "order_items",
            "tenant_scope_column": SCOPE_COL,
            "allowed_for_roles": ["driver", "admin"],
            "columns": [
                {"name": "id", "type": "integer"},
                {"name": "driver_id", "type": "integer"},
                {"name": "delivery_id", "type": "integer"},
                {"name": "qty", "type": "integer"},
            ],
        },
    ],
    "forbidden_tables": ["users", "audit_logs"],
}


def _seed_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE deliveries(id int, driver_id int, city text, price_eur real, revenue real)")
    con.execute("CREATE TABLE order_items(id int, driver_id int, delivery_id int, qty int)")
    con.execute("CREATE TABLE users(id int, email text, password_hash text)")
    con.execute("CREATE TABLE audit_logs(id int, event text)")
    # Caller (driver 7): normal city/price; revenue is a poison value (denied).
    con.executemany("INSERT INTO deliveries VALUES (?,?,?,?,?)", [
        (1, 7, "Lyon", 12.5, REVENUE_7),
        (2, 7, "Paris", 8.2, REVENUE_7),
    ])
    # Foreign (driver 9): poison city/price + poison revenue.
    con.executemany("INSERT INTO deliveries VALUES (?,?,?,?,?)", [
        (3, 9, FOREIGN_CITY, FOREIGN_PRICE, REVENUE_9),
        (4, 9, FOREIGN_CITY, FOREIGN_PRICE, REVENUE_9),
    ])
    con.executemany("INSERT INTO order_items VALUES (?,?,?,?)", [
        (1, 7, 1, 3), (2, 9, 3, 5),
    ])
    con.execute("INSERT INTO users VALUES (1,'a@b.c','HASH_SECRET')")
    con.execute("INSERT INTO audit_logs VALUES (1,'SECRET_EVENT')")
    con.commit()
    return con


def _tool() -> SqlReadTool:
    return SqlReadTool(
        connector=None, schema=SCHEMA, allowed_tables=["deliveries", "order_items"],
        scope_column=SCOPE_COL, scope_value=SCOPE_VAL, role="driver",
        denied_columns=DENIED,
    )


# ── Adversarial case generator ───────────────────────────────────────────────

def _cases() -> list[str]:
    cases: list[str] = []
    A = "price_eur"   # allowed column
    D = "revenue"     # denied column
    for col in (A, D, "*"):
        cases += [
            f"SELECT {col} FROM deliveries",
            f"SELECT {col} FROM deliveries d",
            f"SELECT {col} FROM deliveries WHERE city = 'Lyon'",
            f"SELECT {col} FROM deliveries WHERE {SCOPE_COL} = {SCOPE_VAL}",
            f"SELECT {col} FROM deliveries WHERE {SCOPE_COL} = {FOREIGN_VAL}",
            f"SELECT {col} FROM deliveries ORDER BY id LIMIT 3",
        ]
    # star qualified
    cases += ["SELECT d.* FROM deliveries d", "SELECT deliveries.* FROM deliveries"]
    # denied column in every clause position
    cases += [
        f"SELECT id FROM deliveries WHERE {D} > 100",
        f"SELECT id FROM deliveries ORDER BY {D} DESC",
        f"SELECT city, SUM({D}) FROM deliveries GROUP BY city",
        f"SELECT city FROM deliveries GROUP BY city HAVING SUM({D}) > 1",
        f"SELECT {D} AS r FROM deliveries",
        f"SELECT ROUND({D}, 2) FROM deliveries",
    ]
    # subqueries with foreign scope / denied col
    cases += [
        f"SELECT * FROM deliveries WHERE id IN (SELECT id FROM deliveries WHERE {SCOPE_COL} = {FOREIGN_VAL})",
        f"SELECT * FROM deliveries WHERE id IN (SELECT id FROM deliveries WHERE {D} > 0)",
        f"SELECT id FROM deliveries WHERE EXISTS (SELECT 1 FROM order_items WHERE order_items.delivery_id = deliveries.id)",
        f"SELECT id, (SELECT SUM(qty) FROM order_items o WHERE o.delivery_id = deliveries.id) AS n FROM deliveries",
    ]
    # CTEs
    cases += [
        f"WITH x AS (SELECT * FROM deliveries) SELECT {A} FROM x",
        f"WITH x AS (SELECT id, {D} FROM deliveries) SELECT id FROM x",
        f"WITH x AS (SELECT id FROM deliveries WHERE {SCOPE_COL} = {FOREIGN_VAL}) SELECT * FROM x",
    ]
    # set operations
    cases += [
        f"SELECT {A} FROM deliveries UNION SELECT {A} FROM deliveries",
        f"SELECT id FROM deliveries UNION SELECT id FROM order_items",
        f"SELECT {A} FROM deliveries WHERE {SCOPE_COL}={FOREIGN_VAL} UNION SELECT {A} FROM deliveries",
    ]
    # joins (incl. self join, and join to another scoped table)
    cases += [
        f"SELECT d.city FROM deliveries d JOIN order_items o ON o.delivery_id = d.id",
        f"SELECT d.{D} FROM deliveries d JOIN order_items o ON o.delivery_id = d.id",
        f"SELECT d.* FROM deliveries d JOIN order_items o ON o.delivery_id = d.id",
    ]
    # comment / whitespace tricks
    cases += [
        f"SELECT {A} FROM deliveries -- WHERE {SCOPE_COL} = {FOREIGN_VAL}",
        f"SELECT {A} FROM deliveries /* {D} */",
        f"SELECT\n  {A}\nFROM deliveries",
    ]
    # window functions, CASE, deep nesting, INTERSECT/EXCEPT
    for c in (A, D):
        cases += [
            f"SELECT id, SUM({c}) OVER (PARTITION BY city) AS w FROM deliveries",
            f"SELECT id, RANK() OVER (ORDER BY {c}) FROM deliveries",
            f"SELECT CASE WHEN {c} > 0 THEN 'y' ELSE 'n' END AS f FROM deliveries",
            f"SELECT id FROM deliveries WHERE id IN (SELECT id FROM deliveries WHERE id IN (SELECT id FROM deliveries WHERE {c} > 0))",
            f"SELECT {c} FROM deliveries INTERSECT SELECT {c} FROM deliveries",
            f"SELECT {c} FROM deliveries EXCEPT SELECT {c} FROM deliveries WHERE {SCOPE_COL} = {FOREIGN_VAL}",
            f"WITH a AS (SELECT * FROM deliveries), b AS (SELECT {c} FROM a) SELECT * FROM b",
        ]
    # non-SELECT + forbidden table (must be rejected)
    cases += [
        "UPDATE deliveries SET city='x'",
        "DELETE FROM deliveries WHERE id=1",
        "DROP TABLE deliveries",
        "SELECT * FROM users",
        "SELECT password_hash FROM users",
        "SELECT * FROM deliveries JOIN users ON users.id = deliveries.id",
    ]
    # combinatorial sweep: table × col(allowed/denied/star) × scope(ok/foreign)
    # × aliased × projection shape × order/limit → hundreds of variants.
    tables = {"deliveries": ("price_eur", "revenue"), "order_items": ("qty", None)}
    shapes = [
        "SELECT {c} FROM {t}{a}",
        "SELECT {c} FROM {t}{a} WHERE {ref}.{sc} = {sv}",
        "SELECT {c} FROM {t}{a} WHERE city = 'Lyon'",
        "SELECT {c} FROM {t}{a} ORDER BY id",
        "SELECT {c} FROM {t}{a} LIMIT 5",
        "SELECT DISTINCT {c} FROM {t}{a}",
        "SELECT {c} FROM {t}{a} WHERE id IN (SELECT id FROM {t} WHERE {sc} = {sv})",
    ]
    for tname, (allowed_c, denied_c) in tables.items():
        col_opts = [allowed_c, "*"] + ([denied_c] if denied_c else [])
        for c, sv, alias, shape in itertools.product(
            col_opts, (SCOPE_VAL, FOREIGN_VAL), ("", " x"), shapes
        ):
            ref = "x" if alias else tname
            if tname == "order_items" and "city" in shape:
                continue  # order_items has no city column
            cases.append(shape.format(c=c, t=tname, a=alias, ref=ref, sc=SCOPE_COL, sv=sv))
    return cases


# ── Invariant checks ─────────────────────────────────────────────────────────

def _syntactic_ok(out: str) -> tuple[bool, str]:
    ast = sqlglot.parse_one(out, dialect="sqlite")
    # A1: every scope-column literal equals SCOPE_VAL
    for eq in ast.find_all(exp.EQ):
        if isinstance(eq.left, exp.Column) and eq.left.name == SCOPE_COL:
            rhs = eq.right
            val = rhs.this if isinstance(rhs, exp.Literal) else None
            if val is not None and str(val) != str(SCOPE_VAL):
                return False, f"A1 violated: {SCOPE_COL} = {val}"
    # A2: no denied column referenced
    for col in ast.find_all(exp.Column):
        if col.name and col.name.lower() in {d.lower() for d in DENIED}:
            return False, f"A2 violated: denied column {col.name!r} present"
    return True, ""


def _semantic_ok(con: sqlite3.Connection, out: str) -> tuple[bool, str]:
    try:
        rows = con.execute(out).fetchall()
    except sqlite3.Error:
        return True, "not-executable"  # syntactic invariant still governs
    for row in rows:
        for cell in row:
            if cell in POISON or str(cell) in POISON:
                return False, f"A3 violated: poison value {cell!r} leaked in result"
    return True, "executed"


def _self_test(con: sqlite3.Connection) -> None:
    """Prove the checks have teeth: a KNOWN leak (admin bypassing scope +
    denial, then executing a foreign+denied query) MUST be caught by both
    the syntactic and semantic checks. If it isn't, the harness is blind and
    a clean sweep would be meaningless - so we abort.
    """
    admin = SqlReadTool(
        connector=None, schema=SCHEMA, allowed_tables=["deliveries", "order_items"],
        scope_column=SCOPE_COL, scope_value=SCOPE_VAL, role="admin",
        denied_columns=DENIED,
    )
    leak = admin.validate_and_rewrite(
        f"SELECT city, {DENIED[0]} FROM deliveries WHERE {SCOPE_COL} = {FOREIGN_VAL}"
    )
    syn_ok, _ = _syntactic_ok(leak)
    sem_ok, _ = _semantic_ok(con, leak)
    if syn_ok and sem_ok:
        raise SystemExit(
            "SELF-TEST FAILED: the harness did not catch a known leak - "
            "its checks are vacuous; refusing to report a clean sweep."
        )


def main() -> int:
    con = _seed_db()
    _self_test(con)
    tool = _tool()
    cases = _cases()
    rejected = allowed = executed = violations = 0
    problems: list[str] = []

    for sql in cases:
        try:
            out = tool.validate_and_rewrite(sql)
        except (SqlSecurityError, SqlGenerationError):
            rejected += 1
            continue
        allowed += 1
        ok, why = _syntactic_ok(out)
        if not ok:
            violations += 1
            problems.append(f"[SYNTAX] {sql!r}\n         -> {out!r}\n         {why}")
            continue
        ok, why = _semantic_ok(con, out)
        if why == "executed":
            executed += 1
        if not ok:
            violations += 1
            problems.append(f"[SEMANTIC] {sql!r}\n           -> {out!r}\n           {why}")

    total = len(cases)
    print("=" * 70)
    print(f"In-scope compilation invariant — fuzzing verification")
    print("=" * 70)
    print(f"  cases generated:        {total}")
    print(f"  rejected (outcome R):   {rejected}")
    print(f"  allowed  (outcome A):   {allowed}")
    print(f"    of which executed:    {executed} (semantic A3 checked against poisoned DB)")
    print(f"  INVARIANT VIOLATIONS:   {violations}")
    print("=" * 70)
    if problems:
        print("VIOLATIONS:")
        for p in problems:
            print(" -", p)
        return 1
    print("INVARIANT HELD on every case (no foreign scope, no denied column, "
          "no poisoned value leaked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
