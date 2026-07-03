"""Connector abstract base class.

A Connector is the abstraction between the agent and a tenant's data. Drive
Producteur will use a ``PostgresConnector``. Other tenants may use a
``RestApiConnector``, ``ShopifyConnector``, etc.

Why an abstraction?
-------------------

1. **Security boundary.** Tools (e.g. ``SqlReadTool``) never touch a tenant
   DB directly — they go through a connector that owns the credentials, the
   read-only enforcement, and the row-level scope. The agent never sees a
   connection string.

2. **Pluggability.** Onboarding a new tenant means writing a new Connector
   subclass and registering it. Agent prompts and tools are reusable.

3. **Observability.** Every connector call is wrapped in a Langfuse span,
   so we can see exactly what data the agent touched per request.

4. **Write-action control.** Read paths go through ``execute_readonly_query``.
   Write paths go through ``call_business_action`` and (in Phase 4) through
   the human-in-the-loop queue — never through the read tool.

Concrete subclasses to implement (Phase 1+):

- ``PostgresConnector`` — asyncpg with a read-only role + per-tenant scope.
- ``RestApiConnector`` — translate SQL-like requests to REST calls, or expose
  a fixed set of pre-defined "named queries" instead of free SQL.
- ``ShopifyConnector`` — wraps the Shopify Admin API with GraphQL.

The contract below is stable across all of them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class QueryResult:
    """Result of a read-only query executed by a Connector.

    Attributes
    ----------
    columns:
        Ordered list of column names (matches the order of values in each row).
    rows:
        List of rows; each row is a list of values in column order. We use
        lists (not dicts) to keep memory low on large result sets; the tool
        layer can zip with ``columns`` if it wants dicts.
    rowcount:
        Number of rows returned. Note: for ``SELECT`` this equals
        ``len(rows)``; we keep it explicit for clarity and for connectors
        where the underlying API reports a count differently.
    executed_sql:
        The EXACT SQL that was executed, post-rewriting. This is what we
        show to the user via the agent's ``sql_used`` field — never the
        LLM-generated SQL, which may have been rewritten for security.
    """

    columns: list[str]
    rows: list[Sequence[Any]]
    rowcount: int
    executed_sql: str

    # Convenience: True when the query returned no rows. The agent uses this
    # to decide whether to say "I don't know" rather than fabricate.
    @property
    def is_empty(self) -> bool:
        return self.rowcount == 0

    def as_dicts(self) -> list[dict[str, Any]]:
        """Return rows as a list of dicts (column name -> value)."""
        return [dict(zip(self.columns, row)) for row in self.rows]


@dataclass
class ActionResult:
    """Result of a write-side business action (Phase 4).

    Most actions require human approval before they fire; the connector
    returns this structure once the action has been approved and applied
    (or rejected).
    """

    action_name: str
    success: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    approved_by: str | None = None   # user_id of the human approver


class Connector(ABC):
    """Abstract contract every tenant connector must implement.

    Subclasses are constructed per-tenant at request time (or fetched from a
    small per-process cache), with credentials looked up from the control
    plane. The agent and tools receive a fully-configured connector instance
    and never see the credentials.
    """

    # ── Schema discovery ────────────────────────────────────────────────────
    @abstractmethod
    def get_schema(self) -> dict:
        """Return the tenant's schema as a dict (parsed from schema.yaml).

        The schema is the source of truth for what tables/columns exist,
        which are producer-scoped, and which roles may access each table.
        ``SqlReadTool`` consumes this to (a) build the LLM prompt and
        (b) validate the generated SQL.
        """

    @abstractmethod
    def get_allowed_tables(self, role: str) -> list[str]:
        """Return the list of table names the given role may read.

        This is the *table-level* allow list. Row-level scoping (the
        ``producer_id`` filter) is enforced separately by the rewriting layer.
        """

    # ── Read path ───────────────────────────────────────────────────────────
    @abstractmethod
    async def execute_readonly_query(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a SQL query on a **read-only** connection.

        The caller (``SqlReadTool``) is responsible for ensuring the SQL has
        been validated and rewritten. The connector enforces read-only-ness a
        second time at the DB level (read-only Postgres role), so even a bug
        in the rewriter cannot lead to a write.

        Parameters
        ----------
        sql:
            Validated, rewritten SQL. Must be a SELECT.
        params:
            Optional bind parameters (named, SQLAlchemy-style).

        Returns
        -------
        QueryResult
            The query result, including the exact SQL that ran.
        """

    # ── Write path (Phase 4) ────────────────────────────────────────────────
    @abstractmethod
    async def call_business_action(
        self,
        name: str,
        params: dict[str, Any],
    ) -> ActionResult:
        """Execute a named business action (e.g. ``update_stock``,
        ``cancel_order``, ``refund_payment``).

        This is the ONLY path for writes. Actions are:

        - Defined in ``schema.yaml`` under ``business_actions``.
        - Restricted by ``allowed_for_roles``.
        - Flagged ``requires_approval: true`` go through the human-in-the-loop
          queue and only fire once an admin/approver accepts them.

        Phase 0: not implemented. Raises ``NotImplementedError``.
        """

    # ── Health ──────────────────────────────────────────────────────────────
    async def ping(self) -> bool:
        """Lightweight liveness check against the tenant data source.

        Used by the control plane to surface tenant connector status in the
        admin UI. Default implementation returns ``True``; subclasses should
        override with a real check (e.g. ``SELECT 1`` on the read replica).
        """
        return True
