"""``POST /chat`` — main entry point for the Producer Copilot.

Phase 1 implementation
======================

The endpoint accepts a JSON request with the user's message + identity
(``identity_id``, ``producer_id``, ``role``), constructs a per-request
``SqlReadTool`` configured with the caller's ``scope_value``, runs the
``AgentOrchestrator``, and returns a JSON envelope with the natural-language
answer, the SQL used, a chart spec, the audit trail (steps + security
checks), token accounting, and the measured latency.

In Phase 1 (rule-based, no LLM) we still return ``tokens_in`` / ``tokens_out``
populated with simulated values so the inspector UI is consistent with the
Phase 2 (LLM) baseline. The latency is real (measured).

Security model
==============

1. **Identity.** The request body carries ``identity_id``, ``producer_id``,
   ``role``. In production these come from the verified JWT; in Phase 1 we
   accept them from the body for the demo (no JWT verification yet).
   ``producer_id`` is the row-level scope_value for producers; for admins
   it is ``null`` (no row-level filter).
2. **Scoping.** ``producer_id`` is passed to ``SqlReadTool`` as
   ``scope_value``. The rewriter injects ``WHERE producer_id = N`` at every
   SELECT that touches a scoped table — see ``app/tools/sql_tool.py``.
3. **Read-only.** The ``SqliteConnector`` re-parses the SQL and refuses any
   non-SELECT statement. SQLite has no read-only role concept, so this is
   our second layer of defense (sqlglot is the first).
4. **Quota.** Not enforced in Phase 1 (no LLM, tokens are simulated).

Response shape
==============

The response is always HTTP 200 with the full envelope (refusals included),
so the frontend can render a single success path. See the contract in
``worklog.md`` (Task 11) for the exact JSON schema.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.agents.orchestrator import AgentOrchestrator
from app.connectors.sqlite_connector import SqliteConnector
from app.tools.sql_tool import SqlReadTool

logger = logging.getLogger("tevet7.api.chat")

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Inbound chat request.

    ``identity_id`` is a human-readable handle (e.g. "marie"); ``producer_id``
    is the row-level scope value (NULL for admin); ``role`` selects the table
    allowlist + decides whether scoping is enforced.
    """

    message: str = Field(..., min_length=1, max_length=4000, description="User message.")
    identity_id: str = Field(..., description="Caller identity handle (e.g. 'marie').")
    producer_id: int | None = Field(
        default=None,
        description="Producer id (row-level scope). NULL for admin role.",
    )
    role: Literal["producer", "admin"] = Field(
        ..., description="Caller role. 'admin' disables row-level scoping."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Handler
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> dict[str, Any]:
    """Run the rule-based agent loop and return the full audit envelope.

    Always returns HTTP 200 — refusals and errors are encoded in the JSON
    body (``refused: true``, ``answer`` explaining what happened) so the
    frontend has a single success path.
    """
    logger.info(
        "chat called — identity=%s producer_id=%s role=%s msg_len=%d",
        req.identity_id,
        req.producer_id,
        req.role,
        len(req.message),
    )
    try:
        # Build a per-request connector + tool + orchestrator.
        connector = SqliteConnector()
        schema = connector.get_schema()
        allowed_tables = connector.get_allowed_tables(req.role)
        scope_column = "producer_id" if req.role == "producer" else None
        scope_value = req.producer_id if req.role == "producer" else None

        sql_tool = SqlReadTool(
            connector=connector,
            schema=schema,
            allowed_tables=allowed_tables,
            scope_column=scope_column,
            scope_value=scope_value,
            role=req.role,
        )
        orchestrator = AgentOrchestrator(
            sql_tool=sql_tool, role=req.role, producer_id=req.producer_id
        )
        response = await orchestrator.run(req.message)

        # Serialise to the API contract (snake_case → snake_case as is,
        # but `sql` is the public name; the orchestrator stores `sql_used`
        # internally as `sql` already).
        return {
            "answer": response.answer,
            "sql": response.sql,
            "scope_clause": response.scope_clause,
            "chart": response.chart,
            "tokens_in": response.tokens_in,
            "tokens_out": response.tokens_out,
            "latency_ms": response.latency_ms,
            "tool_calls": response.tool_calls,
            "steps": response.steps,
            "security_checks": response.security_checks,
            "refused": response.refused,
            "tables_touched": response.tables_touched,
            "sources": response.sources,
        }
    except Exception as exc:  # noqa: BLE001 — never crash the frontend
        logger.exception("Unhandled error in /chat")
        return {
            "answer": (
                "Une erreur inattendue est survenue. L'équipe Tevet-7 a été notifiée. "
                "Réessayez dans un instant."
            ),
            "sql": None,
            "scope_clause": None,
            "chart": None,
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": 0,
            "tool_calls": [],
            "steps": [],
            "security_checks": [],
            "refused": True,
            "tables_touched": [],
            "sources": [],
            "error": str(exc),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Schema endpoint — return the loaded schema.yaml as JSON
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/schema")
async def get_schema() -> dict[str, Any]:
    """Return the loaded ``schema.yaml`` as JSON.

    The frontend uses this to display the tenant's data contract in the
    inspector (tables, columns, scoping rules).
    """
    connector = SqliteConnector()
    return connector.get_schema()


@router.get("/chat/health", include_in_schema=False)
async def chat_health() -> dict[str, Any]:
    """Lightweight health probe scoped to the chat router."""
    return {"status": "ok", "router": "chat"}
