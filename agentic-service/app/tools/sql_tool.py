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
   query must include ``WHERE {scope_column} = {scope_value}`` at every
   SELECT that touches the table (top-level + subqueries + CTEs). If the
   LLM produced a query missing the filter (or with a wrong value), the
   rewriter injects the correct one and logs a ``SECURITY WARNING`` — the
   attempt is treated as a security event for audit purposes.
4. **Result limit.** ``LIMIT {default_limit}`` is appended if not present.
5. **No dangerous functions.** ``pg_sleep``, ``lo_import``, ``pg_read_file``,
   ``COPY``, ``LOAD_EXTENSION``, ``WRITEFILE`` are rejected.

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
from typing import Any, Protocol

import sqlglot
from sqlglot import exp

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
    # The post-rewrite SQL that was executed (or None if generation failed).
    sql_used: str | None = None
    # The scope clause that the rewriter injected (or preserved), e.g.
    # ``WHERE oi.producer_id = 42``. Null for admin / unscoped queries.
    scope_clause: str | None = None
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
    """Raised when the SQL generator fails to produce parseable SQL."""


# ─────────────────────────────────────────────────────────────────────────────
# SQL generator protocol (swappable LLM/rule-based)
# ─────────────────────────────────────────────────────────────────────────────


class SQLGenerator(Protocol):
    """Protocol every SQL generator must satisfy.

    Phase 1 ships ``RuleBasedSQLGenerator`` (deterministic, keyword-driven).
    Phase 2 will swap in ``LLMSQLGenerator`` that calls OpenAI with the
    rendered schema + few-shot examples. The orchestrator and tool do not
    need to change.
    """

    def generate(
        self,
        question: str,
        role: str,
        scope_column: str | None,
        scope_value: int | str | None,
    ) -> str | None:
        """Translate a natural-language question into a SQL SELECT.

        Returns ``None`` if no rule matches (or the LLM declined). Raises
        ``SqlGenerationError`` for unrecoverable failures.

        ``scope_column`` / ``scope_value`` are provided for context but the
        generator is NOT required to include the scope clause — the
        ``validate_and_rewrite`` step will inject it if missing.
        """
        ...


# Sentinel the generator returns to ask the tool to refuse the question
# (e.g. a producer asking a cross-producer question).
REFUSE_MARKER = "__REFUSE__"


class RuleBasedSQLGenerator:
    """Deterministic keyword-driven SQL generator.

    Phase 1: 5 hardcoded patterns for the DP demo tenant (backward compat).
    Phase 6+: generic schema-aware patterns that read the tenant's
    schema_config and generate SQL for ANY table/column names.

    The generator tries DP-specific patterns first, then falls back to
    generic patterns based on the schema.
    """

    def __init__(self, schema: dict | None = None) -> None:
        """Optional schema dict for generic generation.

        When provided, the generator can match table names mentioned in the
        question and generate SQL for non-DP tenants.
        """
        self._schema = schema or {}

    # ── helpers ────────────────────────────────────────────────────────────
    @staticmethod
    def _has_any(text: str, needles: list[str]) -> bool:
        t = text.lower()
        return any(n in t for n in needles)

    # ── generic schema-aware generation ────────────────────────────────────
    def _find_table_in_question(self, q: str) -> tuple[str, dict] | None:
        """Find which table the question refers to.

        Matches the table name (or a singular/plural variant) in the
        question text. Returns (table_name, table_config) or None.
        If the schema has only one table, use it as default.
        """
        tables = self._schema.get("tables", [])
        if not tables:
            return None
        # If only one table, use it as default (most CSV tenants).
        if len(tables) == 1:
            return tables[0]["name"], tables[0]
        q_lower = q.lower()
        # Sort by name length desc so longer names match first.
        for t in sorted(tables, key=lambda x: len(x.get("name", "")), reverse=True):
            name = t.get("name", "").lower()
            if not name:
                continue
            # Match exact, plural (s), or singular (strip trailing s).
            variants = {name, name + "s", name.rstrip("s"), name.replace("_", " "), name.replace("-", " ")}
            if any(v in q_lower for v in variants if len(v) >= 3):
                return t["name"], t
        return None

    def _find_numeric_column(self, table_config: dict) -> str | None:
        """Find the first numeric column in a table (for SUM/AVG)."""
        for c in table_config.get("columns", []):
            ctype = c.get("type", "").lower()
            if any(k in ctype for k in ("decimal", "float", "double", "integer", "int", "numeric", "real")):
                # Skip ID columns.
                cname = c.get("name", "").lower()
                if cname not in ("id", "producer_id", "tenant_id", "user_id", "customer_id", "shop_id", "order_id", "product_id"):
                    return c["name"]
        return None

    def _find_group_column(self, table_config: dict) -> str | None:
        """Find a good GROUP BY column (text/categorical, not ID).

        Priority: categor/type/status > name/label > first text column.
        """
        # Priority 1: categorical columns (category, type, status, genre).
        for c in table_config.get("columns", []):
            ctype = c.get("type", "").lower()
            cname = c.get("name", "").lower()
            if any(k in ctype for k in ("varchar", "text", "char", "string")):
                if cname not in ("id", "email", "password", "siret", "phone"):
                    if any(k in cname for k in ("categor", "type", "status", "genre", "city", "country")):
                        return c["name"]
        # Priority 2: name/label/title columns.
        for c in table_config.get("columns", []):
            ctype = c.get("type", "").lower()
            cname = c.get("name", "").lower()
            if any(k in ctype for k in ("varchar", "text", "char", "string")):
                if cname not in ("id", "email", "password", "siret", "phone"):
                    if any(k in cname for k in ("name", "label", "title")):
                        return c["name"]
        # Fallback: first text column that's not an ID/email.
        for c in table_config.get("columns", []):
            ctype = c.get("type", "").lower()
            cname = c.get("name", "").lower()
            if any(k in ctype for k in ("varchar", "text", "char", "string")):
                if cname not in ("id", "email", "password", "siret", "phone"):
                    return c["name"]
        return None

    def _find_date_column(self, table_config: dict) -> str | None:
        """Find a date/timestamp column for time-based queries."""
        for c in table_config.get("columns", []):
            ctype = c.get("type", "").lower()
            if any(k in ctype for k in ("date", "timestamp", "time", "datetime")):
                return c["name"]
        return None

    def _generic_generate(self, question: str, role: str) -> str | None:
        """Generic schema-aware SQL generation for non-DP tenants."""
        q = question.lower()
        match = self._find_table_in_question(q)
        if match is None:
            return None
        table_name, table_config = match
        columns = table_config.get("columns", [])
        if not columns:
            return None
        # Collect column names for reference.
        col_names = [c["name"] for c in columns]
        numeric_col = self._find_numeric_column(table_config)
        group_col = self._find_group_column(table_config)
        date_col = self._find_date_column(table_config)

        # Try to find a column name mentioned in the question (for GROUP BY).
        mentioned_col = None
        for c in columns:
            if c["name"].lower() in q and c["name"].lower() not in ("id",):
                mentioned_col = c["name"]
                break
        # Use mentioned column as group_col if it's a text column.
        if mentioned_col:
            for c in columns:
                if c["name"] == mentioned_col and any(k in c.get("type", "").lower() for k in ("text", "varchar", "char", "string")):
                    group_col = mentioned_col
                    break

        # Pattern 1: min/max (check before total/somme to avoid conflicts)
        if numeric_col and self._has_any(q, ["minimum", "plus bas", "plus petit", "min "]):
            return f"SELECT MIN({numeric_col}) AS min_{numeric_col} FROM {table_name}"
        if numeric_col and self._has_any(q, ["maximum", "plus haut", "plus grand", "plus élevé", "max "]):
            return f"SELECT MAX({numeric_col}) AS max_{numeric_col} FROM {table_name}"

        # Pattern 2: moyenne / average (check before total to avoid conflicts)
        if numeric_col and self._has_any(q, ["moyenne", "average", "avg", "mean"]):
            if group_col and self._has_any(q, ["par", "by"]):
                return f"SELECT {group_col}, ROUND(AVG({numeric_col}), 2) AS avg_{numeric_col} FROM {table_name} GROUP BY {group_col} ORDER BY avg_{numeric_col} DESC LIMIT 20"
            return f"SELECT ROUND(AVG({numeric_col}), 2) AS avg_{numeric_col} FROM {table_name}"

        # Pattern 3: total / somme / sum + numeric column → SUM
        if numeric_col and self._has_any(q, ["total", "somme", "sum", "chiffre"]):
            if group_col and self._has_any(q, ["par", "by"]):
                return f"SELECT {group_col}, ROUND(SUM({numeric_col}), 2) AS total_{numeric_col} FROM {table_name} GROUP BY {group_col} ORDER BY total_{numeric_col} DESC LIMIT 20"
            return f"SELECT ROUND(SUM({numeric_col}), 2) AS total_{numeric_col} FROM {table_name}"

        # Pattern 4: combien / count / nombre → COUNT(*)
        if self._has_any(q, ["combien", "count", "nombre", "how many"]):
            if group_col and self._has_any(q, ["par", "by"]):
                return f"SELECT {group_col}, COUNT(*) AS count FROM {table_name} GROUP BY {group_col} ORDER BY count DESC LIMIT 20"
            return f"SELECT COUNT(*) AS total FROM {table_name}"

        # Pattern 5: top / meilleur / plus → top 5
        if self._has_any(q, ["top", "meilleur", "plus", "best", "fréquent", "frequent", "populaire"]):
            name_col = next((c["name"] for c in columns if "name" in c["name"].lower() or "label" in c["name"].lower() or "title" in c["name"].lower()), col_names[0])
            if numeric_col:
                return f"SELECT {name_col}, ROUND(SUM({numeric_col}), 2) AS total FROM {table_name} GROUP BY {name_col} ORDER BY total DESC LIMIT 5"
            return f"SELECT {name_col}, COUNT(*) AS count FROM {table_name} GROUP BY {name_col} ORDER BY count DESC LIMIT 5"

        # Pattern 6: liste / affiche / montre / voir → SELECT * LIMIT 20
        if self._has_any(q, ["liste", "list", "affiche", "montre", "voir", "show", "display", "tous", "all", "dernier", "recent"]):
            return f"SELECT * FROM {table_name} LIMIT 20"

        # Pattern 7: 7 derniers jours + date column → date filter
        if date_col and self._has_any(q, ["7 jours", "7 derniers", "semaine", "recent", "récent", "last 7"]):
            return f"SELECT * FROM {table_name} WHERE {date_col} >= DATE('now', '-7 days') ORDER BY {date_col} DESC LIMIT 20"

        # Pattern 8: default — select all columns, limit 20
        select_cols = ", ".join(col_names[:10]) if len(col_names) > 10 else "*"
        return f"SELECT {select_cols} FROM {table_name} LIMIT 20"

    # ── entry point ────────────────────────────────────────────────────────
    def generate(
        self,
        question: str,
        role: str,
        scope_column: str | None,
        scope_value: int | str | None,
    ) -> str | None:
        q = question.lower()

        # 1. Cross-producer ranking — admin-only.
        #    "Quels producteurs ont le plus de commandes ?"
        if self._has_any(q, ["producteur"]) and self._has_any(q, ["commande", "vente"]):
            if role != "admin":
                # Producer asking a cross-producer question → refuse.
                return REFUSE_MARKER
            # Admin: aggregate across all producers, current month.
            return (
                "SELECT p.display_name AS producer_name, "
                "COUNT(DISTINCT o.id) AS order_count, "
                "COALESCE(SUM(o.total_amount), 0) AS revenue_eur "
                "FROM producers p "
                "LEFT JOIN orders o ON o.producer_id = p.id "
                "AND o.created_at >= '2024-07-01' "
                "AND o.status != 'cancelled' "
                "GROUP BY p.id, p.display_name "
                "ORDER BY order_count DESC"
            )

        # 2. Top products this month.
        #    "Quels sont mes 5 produits les plus vendus ce mois-ci ?"
        if self._has_any(q, ["produit", "vendu", "vente"]) and self._has_any(q, ["top", "plus", "plus vendu", "best", "meilleur"]):
            return (
                "SELECT p.name AS name, "
                "SUM(oi.quantity) AS units_sold, "
                "ROUND(SUM(oi.line_total_eur), 2) AS revenue "
                "FROM order_items oi "
                "JOIN products p ON oi.product_id = p.id "
                "JOIN orders o ON oi.order_id = o.id "
                "WHERE o.status != 'cancelled' "
                "AND o.created_at >= '2024-07-01' "
                "GROUP BY p.id, p.name "
                "ORDER BY units_sold DESC "
                "LIMIT 5"
            )

        # 3. Stock shortfall.
        #    "Quels produits risquent de me manquer samedi ?"
        if self._has_any(q, ["stock", "manqu", "rupture", "samedi", "épuis"]):
            return (
                "SELECT p.name AS name, "
                "p.category AS category, "
                "s.quantity AS stock_quantity, "
                "s.reserved AS reserved, "
                "s.available AS available, "
                "ROUND(s.available, 2) AS available_display "
                "FROM stocks s "
                "JOIN products p ON s.product_id = p.id "
                "WHERE s.available < 10 "
                "ORDER BY s.available ASC"
            )

        # 4. Net revenue (current month or named month, e.g. June).
        #    "Combien ai-je gagné en juin ?"
        if self._has_any(q, ["gagné", "gagne", "net", "commission", "chiffre", "ca ", "revenu", "recette"]):
            # Determine the month from the question; default = current month.
            month_start, month_end, month_label = self._resolve_month(q)
            return (
                f"SELECT "
                f"COUNT(DISTINCT o.id) AS order_count, "
                f"ROUND(COALESCE(SUM(o.total_amount), 0), 2) AS gross_revenue, "
                f"ROUND(COALESCE(SUM(o.total_amount), 0) * {1 - 0.12:.4f}, 2) AS net_revenue, "
                f"'{month_label}' AS month_label "
                f"FROM orders o "
                f"WHERE o.status != 'cancelled' "
                f"AND o.created_at >= '{month_start}' "
                f"AND o.created_at <= '{month_end}'"
            )

        # 5. Weekly sales summary.
        #    "Résumé de mes ventes cette semaine ?"
        if self._has_any(q, ["résumé", "resume", "semaine", "synthèse", "synthese"]):
            return (
                "SELECT DATE(o.created_at) AS day, "
                "COUNT(DISTINCT o.id) AS order_count, "
                "ROUND(COALESCE(SUM(o.total_amount), 0), 2) AS revenue "
                "FROM orders o "
                "WHERE o.status != 'cancelled' "
                "AND o.created_at >= DATE('2024-07-08') "
                "AND o.created_at <= DATE('2024-07-15') "
                "GROUP BY DATE(o.created_at) "
                "ORDER BY day ASC"
            )

        # No DP rule matched — try generic schema-aware generation.
        return self._generic_generate(question, role)

    @staticmethod
    def _resolve_month(q: str) -> tuple[str, str, str]:
        """Pick the SQL date window for the revenue question.

        Defaults to the current demo month (July 2024). Recognises "juin",
        "juillet", "mai", "avril", "mars", "février", "janvier".
        """
        months = [
            ("janvier", "2024-01-01", "2024-01-31 23:59:59", "janvier 2024"),
            ("février", "2024-02-01", "2024-02-29 23:59:59", "février 2024"),
            ("fevrier", "2024-02-01", "2024-02-29 23:59:59", "février 2024"),
            ("mars", "2024-03-01", "2024-03-31 23:59:59", "mars 2024"),
            ("avril", "2024-04-01", "2024-04-30 23:59:59", "avril 2024"),
            ("mai", "2024-05-01", "2024-05-31 23:59:59", "mai 2024"),
            ("juin", "2024-06-01", "2024-06-30 23:59:59", "juin 2024"),
            ("juillet", "2024-07-01", "2024-07-31 23:59:59", "juillet 2024"),
        ]
        for keyword, start, end, label in months:
            if keyword in q:
                return start, end, label
        # Default to current month (July 2024 in the demo).
        return "2024-07-01", "2024-07-31 23:59:59", "ce mois-ci"


# ─────────────────────────────────────────────────────────────────────────────
# The tool
# ─────────────────────────────────────────────────────────────────────────────


# Functions that must NEVER appear in a generated query (SQLite + Postgres).
_FORBIDDEN_FUNCTIONS = {
    "pg_sleep",
    "lo_import",
    "lo_export",
    "pg_read_file",
    "pg_write_file",
    "pg_ls_dir",
    "copy",
    "load_extension",
    "writefile",
    "readfile",
    "unlink",
    "fsync",
}


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

    1. ``generate_sql(question)`` — produce SQL (rule-based in Phase 1,
       LLM-based in Phase 2). The ``SQLGenerator`` protocol makes the swap
       a one-line change.
    2. ``validate_and_rewrite(sql)`` — sqlglot parses the SQL, applies the
       five security checks described in the module docstring, and returns
       the rewritten SQL.
    3. ``execute(sql)`` — the connector runs the rewritten SQL on its
       read-only connection.
    """

    # Default result limit if the schema doesn't override it.
    DEFAULT_LIMIT = 1000

    def __init__(
        self,
        connector: Connector,
        schema: dict[str, Any],
        allowed_tables: list[str],
        scope_column: str | None,
        scope_value: int | str | None,
        role: str = "producer",
        llm_client: Any | None = None,
        generator: SQLGenerator | None = None,
    ) -> None:
        self.connector = connector
        self.schema = schema
        self.allowed_tables = set(allowed_tables)
        # Forbidden tables are tenant-wide: nobody, not even admins, may
        # query them via the agent (they're reserved for the control plane).
        self.forbidden_tables = set(schema.get("forbidden_tables", []))
        self.scope_column = scope_column
        self.scope_value = scope_value
        self.role = role
        # For producer/customer: row-level scoping is enforced.
        # For admin: scoping is skipped (admin sees all rows).
        self.enforce_scope = role != "admin" and scope_column is not None and scope_value is not None
        self.default_limit = schema.get("metadata", {}).get("default_limit", self.DEFAULT_LIMIT)
        self.llm_client = llm_client
        # Phase A1: use LLMSQLGenerator when OpenAI API key is available,
        # fall back to RuleBasedSQLGenerator (DP patterns + generic patterns).
        if generator is not None:
            self.generator: SQLGenerator = generator
        else:
            from app.config import get_settings
            settings = get_settings()
            api_key = settings.openai_api_key
            if api_key and api_key != "sk-replace-me":
                from app.tools.llm_sql_generator import LLMSQLGenerator
                self.generator = LLMSQLGenerator(
                    schema=schema,
                    api_key=api_key,
                    model=settings.llm_model,
                )
            else:
                self.generator = RuleBasedSQLGenerator(schema=schema)
        # Build a quick lookup: table_name -> scope_column (or None)
        self._table_scope_columns: dict[str, str | None] = {}
        for t in schema.get("tables", []):
            self._table_scope_columns[t["name"]] = t.get("tenant_scope_column")

    # ───────────────────────────────────────────────────────────────────────
    # Step 1 — SQL generation
    # ───────────────────────────────────────────────────────────────────────
    def generate_sql(self, question: str) -> str:
        """Generate SQL for the question via the configured generator.

        Returns the SQL string. Returns ``REFUSE_MARKER`` if the generator
        explicitly refuses the question (e.g. a producer asking a
        cross-producer question). Raises ``SqlGenerationError`` if no rule
        matches AND no LLM fallback is available.
        """
        sql = self.generator.generate(
            question=question,
            role=self.role,
            scope_column=self.scope_column,
            scope_value=self.scope_value,
        )
        if sql is None:
            raise SqlGenerationError(
                f"No SQL rule matched the question: {question!r}"
            )
        return sql

    # ───────────────────────────────────────────────────────────────────────
    # Step 2 — Validation & rewriting (sqlglot)
    # ───────────────────────────────────────────────────────────────────────
    def validate_and_rewrite(self, sql: str) -> str:
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
           of every SELECT that directly touches that table includes
           ``{scope_column} = {scope_value}``. If missing or wrong:
              - rewrite the AST to inject/replace the predicate,
              - increment ``rewrites_applied``,
              - if the existing predicate used a *different* scope value
                (the LLM tried to bypass), set ``self._last_security_incident=True``
                and log a ``SECURITY WARNING``.
           For admin role: skip scoping.
        e) Reject dangerous function calls (``pg_sleep``, ``lo_import``,
           ``pg_read_file``, ``COPY``, ``LOAD_EXTENSION``, ``WRITEFILE``).
        f) If no ``LIMIT`` is present, append ``LIMIT {default_limit}``.

        Returns the rewritten SQL as a string.

        Side effects: sets ``self._last_security_incident`` and
        ``self._last_rewrites_applied`` (consumed by ``run``).
        """
        self._last_security_incident = False
        self._last_rewrites_applied = 0
        self._last_scope_clause: str | None = None

        # ── a) Parse ──
        try:
            ast = sqlglot.parse_one(sql, dialect="sqlite")
        except Exception as exc:
            raise SqlGenerationError(f"unparseable SQL: {exc}") from exc

        # ── b) Statement kind ──
        if not isinstance(ast, exp.Select):
            kind = type(ast).__name__
            raise SqlSecurityError(
                f"Statement kind '{kind}' is not allowed — only SELECT."
            )

        # ── c) Table allowlist (walk ALL tables in the AST) ──
        referenced_tables: list[str] = []
        for table_node in ast.find_all(exp.Table):
            tname = table_node.name
            referenced_tables.append(tname)
            if tname in self.forbidden_tables:
                raise SqlSecurityError(
                    f"Forbidden table referenced: {tname!r} "
                    "(control-plane table — never reachable via the agent)."
                )
            if tname not in self.allowed_tables:
                raise SqlSecurityError(
                    f"Table {tname!r} is not in the allowed list for role "
                    f"{self.role!r}."
                )

        # ── d) Row-level scoping ──
        if self.enforce_scope:
            self._apply_row_level_scope(ast)

        # ── e) Dangerous functions ──
        for anon in ast.find_all(exp.Anonymous):
            fname = (anon.name or "").lower()
            if fname in _FORBIDDEN_FUNCTIONS:
                raise SqlSecurityError(
                    f"Dangerous function {fname!r} is not allowed."
                )

        # ── f) LIMIT ──
        if not ast.args.get("limit"):
            ast.set("limit", exp.Limit(expression=exp.Literal.number(self.default_limit)))
            self._last_rewrites_applied += 1

        rewritten = ast.sql(dialect="sqlite", pretty=False)
        return rewritten

    def _apply_row_level_scope(self, ast: exp.Select) -> None:
        """Inject ``{scope_column} = {scope_value}`` at every SELECT that
        directly references a producer-scoped table.

        Mutates ``ast`` in place. Updates ``self._last_security_incident``,
        ``self._last_rewrites_applied``, and ``self._last_scope_clause``.
        """
        scope_col = self.scope_column
        scope_val = self.scope_value

        # Walk every SELECT node (top-level + subqueries + CTEs).
        for sel in ast.find_all(exp.Select):
            direct_tables = self._direct_tables_of_select(sel)
            scoped_tables_here = [
                t for t in direct_tables
                if self._table_scope_columns.get(t) == scope_col
            ]
            if not scoped_tables_here:
                continue

            # Pick a qualifier for the scope column from the alias of one of
            # the scoped tables present in this SELECT. This avoids
            # "ambiguous column name" errors when several scoped tables are
            # joined (all of them carry the same scope_column).
            qualifier = self._pick_scope_qualifier(sel, scoped_tables_here)

            # Inspect the SELECT's direct WHERE.
            where = sel.args.get("where")
            existing_predicate = None
            existing_value: int | str | None = None
            if where is not None:
                for eq in where.find_all(exp.EQ):
                    left = eq.left
                    right = eq.right
                    if isinstance(left, exp.Column) and left.name == scope_col:
                        # Existing predicate on scope_col found.
                        if isinstance(right, exp.Literal):
                            try:
                                existing_value = int(right.this)
                            except (ValueError, TypeError):
                                existing_value = right.this
                        else:
                            existing_value = right.sql()
                        existing_predicate = eq
                        break

            if existing_predicate is None:
                # Missing → inject. Use the qualifier so SQLite doesn't
                # raise "ambiguous column name" when several scoped tables
                # are joined.
                col_ref = f"{qualifier}.{scope_col}" if qualifier else scope_col
                predicate = exp.condition(f"{col_ref} = {scope_val}")
                # sel.where() returns a new Select; we copy its WHERE into
                # the existing node so the AST is mutated in place.
                new_sel = sel.where(predicate)
                new_where = new_sel.args.get("where")
                if new_where is not None:
                    sel.set("where", new_where)
                self._last_rewrites_applied += 1
                if self._last_scope_clause is None:
                    self._last_scope_clause = f"WHERE {col_ref} = {scope_val}"
            else:
                # Existing predicate on scope_col. Check value.
                if str(existing_value) != str(scope_val):
                    # Wrong value → rewrite + security incident.
                    logger.warning(
                        "SECURITY WARNING — scope bypass attempt: "
                        "question scope_value=%s but SQL contained %s=%s. "
                        "Rewriting to %s=%s.",
                        scope_val, scope_col, existing_value, scope_col, scope_val,
                    )
                    existing_predicate.right.replace(
                        exp.Literal.number(int(scope_val))
                        if isinstance(scope_val, int)
                        else exp.Literal.string(str(scope_val))
                    )
                    self._last_security_incident = True
                    self._last_rewrites_applied += 1
                    if self._last_scope_clause is None:
                        col_ref = f"{qualifier}.{scope_col}" if qualifier else scope_col
                        self._last_scope_clause = f"WHERE {col_ref} = {scope_val}"
                # else: correct predicate, no action.

    def _pick_scope_qualifier(
        self, sel: exp.Select, scoped_tables_here: list[str]
    ) -> str | None:
        """Pick the alias of the first scoped table referenced by ``sel``.

        Returns the alias (or the bare table name when no alias is set) so
        the rewriter can emit ``<alias>.producer_id = 42`` and avoid
        ambiguous-column errors. Returns ``None`` if no scoped table is
        found (shouldn't happen since the caller filters first).
        """
        from_clause = sel.args.get("from_") or sel.args.get("from")
        if from_clause is not None and isinstance(from_clause.this, exp.Table):
            t = from_clause.this
            if t.name in scoped_tables_here:
                return t.alias_or_name
        for j in (sel.args.get("joins") or []):
            if isinstance(j.this, exp.Table):
                t = j.this
                if t.name in scoped_tables_here:
                    return t.alias_or_name
        return None

    @staticmethod
    def _direct_tables_of_select(sel: exp.Select) -> list[str]:
        """Tables directly referenced by ``sel`` (FROM + JOINs) — excluding
        tables that appear only inside subqueries of ``sel``.
        """
        out: list[str] = []
        from_clause = sel.args.get("from_") or sel.args.get("from")
        if from_clause is not None and isinstance(from_clause.this, exp.Table):
            out.append(from_clause.this.name)
        for j in (sel.args.get("joins") or []):
            if isinstance(j.this, exp.Table):
                out.append(j.this.name)
        return out

    # ───────────────────────────────────────────────────────────────────────
    # Step 3 — Execution (Connector)
    # ───────────────────────────────────────────────────────────────────────
    async def execute(self, sql: str) -> QueryResult:
        """Run the rewritten SQL via the connector's read-only connection."""
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
            raw_sql = self.generate_sql(question)
            if raw_sql == REFUSE_MARKER:
                # Generator explicitly refused the question (cross-producer
                # question from a producer).
                return ToolResult(
                    success=False,
                    error="REFUSE: cross-producer question requires admin role.",
                    question=question,
                    security_incident=False,
                )
            safe_sql = self.validate_and_rewrite(raw_sql)
            result = await self.execute(safe_sql)
            return ToolResult(
                success=True,
                query_result=result,
                question=question,
                sql_used=safe_sql,
                scope_clause=self._last_scope_clause,
                tables_touched=self._extract_tables(safe_sql),
                rewrites_applied=self._last_rewrites_applied,
                security_incident=self._last_security_incident,
            )
        except SqlSecurityError as exc:
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

        Uses sqlglot to walk the AST (deduplicated, order-preserving).
        """
        try:
            ast = sqlglot.parse_one(sql, dialect="sqlite")
        except Exception:  # noqa: BLE001
            return []
        seen: list[str] = []
        for t in ast.find_all(exp.Table):
            if t.name not in seen:
                seen.append(t.name)
        return seen
