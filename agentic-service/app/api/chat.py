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

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.orchestrator import AgentOrchestrator
from app.auth.dependencies import TenantContext, try_get_tenant_context
from app.connectors.factory import TenantNotOnboardedError, get_connector_for_tenant
from app.connectors.sqlite_connector import SqliteConnector
from app.tools.forecast_tool import ForecastTool
from app.tools.rag_tool import RagSearchTool
from app.tools.sql_tool import SqlReadTool
from app.tracing import get_tracer

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

    Phase 6a — dual auth mode
    -------------------------

    The identity fields (``identity_id``, ``producer_id``, ``role``) are
    now OPTIONAL. Two paths are supported:

    1. **JWT path (new, for the frontend)** — the caller sends
       ``Authorization: Bearer <jwt>``. Identity is extracted from the
       verified JWT (tenant_id, role, producer_id, email). The body
       identity fields are IGNORED.
    2. **Body path (legacy, for the eval + tests)** — no
       ``Authorization`` header. Identity is read from the body. The
       tenant is hardcoded to ``"dp"`` (the demo tenant).

    Both paths funnel into the SAME orchestrator — the agentic core has
    no notion of users or JWTs, it only receives ``role``,
    ``producer_id``, ``tenant_id`` as plain strings. The dual mode keeps
    the existing 39-case eval passing WITHOUT modification (the eval
    uses the body path) while letting the frontend authenticate via JWT.
    """

    message: str = Field(..., min_length=1, max_length=4000, description="User message.")
    # Phase 6a: identity fields are now optional — when an Authorization
    # header is present they're read from the JWT instead. Defaults
    # (None) keep the old body path working for the eval.
    identity_id: str | None = Field(
        default=None,
        description=(
            "Caller identity handle (e.g. 'marie'). OPTIONAL when "
            "Authorization: Bearer is present (read from the JWT)."
        ),
    )
    producer_id: int | None = Field(
        default=None,
        description="Producer id (row-level scope). NULL for admin role.",
    )
    role: Literal["producer", "admin"] | None = Field(
        default=None,
        description=(
            "Caller role. 'admin' disables row-level scoping. OPTIONAL "
            "when Authorization: Bearer is present."
        ),
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
    # ── Phase 6a — dual auth mode ──────────────────────────────────────────
    # If the caller sends an ``Authorization: Bearer <jwt>`` header we
    # extract the identity (tenant_id, role, producer_id) from the
    # verified JWT. Otherwise we fall back to the body identity (the
    # legacy path used by the eval + the old frontend). The CORE agentic
    # (orchestrator + tools + tracing) is unchanged — it receives plain
    # ``role``/``producer_id``/``tenant_id`` strings either way.
    jwt_ctx: TenantContext | None = try_get_tenant_context(request)
    if jwt_ctx is not None:
        # JWT path — identity comes from the token.
        if not jwt_ctx.role or not jwt_ctx.tenant_id:
            # A fresh signup has no membership yet — refuse with 403 so
            # the frontend can prompt for tenant creation/activation.
            raise HTTPException(
                status_code=403,
                detail=(
                    "no active tenant in JWT — create or activate a tenant "
                    "via POST /api/tenants or POST /api/tenants/{id}/activate"
                ),
            )
        # The orchestrator expects role ∈ {"producer", "admin"}.
        # "customer" maps to "producer" for scoping purposes (same
        # row-level filter on producer_id).
        role: str = jwt_ctx.role if jwt_ctx.role in ("producer", "admin") else "producer"
        producer_id: int | None = jwt_ctx.producer_id
        identity_id: str = jwt_ctx.email or f"user_{jwt_ctx.user_id}"
        tenant_id: str = jwt_ctx.tenant_id
        logger.info(
            "chat called [JWT path] — user_id=%s email=%s tenant=%s role=%s producer_id=%s msg_len=%d",
            jwt_ctx.user_id, jwt_ctx.email, tenant_id, role, producer_id, len(req.message),
        )
    else:
        # Legacy body path — used by the eval (eval/eval.py sends body
        # identity without an Authorization header).
        if not req.identity_id or not req.role:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Authorization header missing or invalid, AND body is "
                    "missing identity_id/role. Send either a Bearer JWT or "
                    "the body identity fields (identity_id, role, producer_id)."
                ),
            )
        role = req.role
        producer_id = req.producer_id
        identity_id = req.identity_id
        tenant_id = "dp"  # hardcoded for the demo tenant (eval path)
        logger.info(
            "chat called [body path] — identity=%s producer_id=%s role=%s msg_len=%d",
            identity_id, producer_id, role, len(req.message),
        )

    try:
        # Build a per-request connector + tool + orchestrator.
        # Phase 6b — the connector is now chosen dynamically based on the
        # tenant's ``tenant_configs`` row:
        #   - demo tenant "dp" (and the legacy body path) → SqliteConnector
        #     (unchanged — backward compat).
        #   - tenants with ``connector_type="postgres"`` → PostgresConnector.
        #   - tenants with ``connector_type="csv"``      → CsvConnector.
        # If the tenant is not onboarded yet, the factory raises
        # ``TenantNotOnboardedError`` — we catch it below and return a
        # clear French message prompting the user to complete onboarding.
        try:
            connector = await get_connector_for_tenant(tenant_id)
        except TenantNotOnboardedError:
            return {
                "answer": (
                    "Votre workspace n'est pas encore configuré. Complétez "
                    "l'onboarding pour activer l'agent."
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
                "ops_analysis": None,
                "forecast_predictions": None,
                "trace_id": None,
                "not_onboarded": True,
            }
        schema = connector.get_schema()
        allowed_tables = connector.get_allowed_tables(role)
        scope_column = "producer_id" if role == "producer" else None
        scope_value = producer_id if role == "producer" else None

        sql_tool = SqlReadTool(
            connector=connector,
            schema=schema,
            allowed_tables=allowed_tables,
            scope_column=scope_column,
            scope_value=scope_value,
            role=role,
        )
        # Phase 3 — build the RAG tool with the same identity context so
        # documentary questions are scoped identically to analytical ones.
        # Phase 6a — tenant_id now comes from the JWT (multi-tenant) or
        # defaults to "dp" for the legacy body path (eval).
        rag_tool = RagSearchTool(
            connector=connector,
            tenant_id=tenant_id,
            producer_id=producer_id,
            role=role,
            tracer=get_tracer(),
        )
        # Phase 5 — build the forecast tool with the same identity context so
        # stock-shortage questions are scoped identically. The forecast tool
        # enforces producer scoping internally (queries stock_history /
        # stocks / products WHERE producer_id = :producer_id) so a producer
        # never sees another producer's ML predictions, even with a model bug.
        forecast_tool = ForecastTool(
            connector=connector,
            tenant_id=tenant_id,
            producer_id=producer_id,
            role=role,
            tracer=get_tracer(),
        )
        orchestrator = AgentOrchestrator(
            sql_tool=sql_tool,
            role=role,
            producer_id=producer_id,
            identity_id=identity_id,
            tracer=get_tracer(),
            rag_tool=rag_tool,
            forecast_tool=forecast_tool,
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
            "ops_analysis": response.ops_analysis,
            "forecast_predictions": response.forecast_predictions,
            "trace_id": response.trace_id,
        }
    except HTTPException:
        # Re-raise FastAPI HTTP exceptions (401/403 from the dual-mode
        # check above) without wrapping them in the catch-all below.
        raise
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
            "ops_analysis": None,
            "forecast_predictions": None,
            "trace_id": None,
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


# ─────────────────────────────────────────────────────────────────────────────
# Traces endpoints — observability surface (Task 18 / Phase 2 tracing)
# ─────────────────────────────────────────────────────────────────────────────
# ``GET /api/traces``         → list the most recent 50 traces (summary).
# ``GET /api/traces/{trace_id}`` → full trace detail (SQL, steps, tool_calls,
#                                 tokens, cost, answer excerpt, …).
#
# The tracer itself (LocalTracer or LangfuseTracer) backs both endpoints —
# the API layer is a thin wrapper that delegates to ``get_tracer()`` so
# Langfuse-mode and local-mode expose the same HTTP surface.


@router.get("/traces")
async def list_traces(limit: int = 50) -> dict[str, Any]:
    """List the most recent traces (newest first).

    Returns the summary fields only (no SQL, no steps) — use
    ``/api/traces/{id}`` for the full detail. The default ``limit=50`` keeps
    the response payload small for the inspector UI.
    """
    tracer = get_tracer()
    items = await tracer.list_recent(limit=max(1, min(limit, 200)))
    # Normalise datetimes to ISO strings for JSON.
    for item in items:
        ca = item.get("created_at")
        if ca is not None and hasattr(ca, "isoformat"):
            item["created_at"] = ca.isoformat()
    return {"count": len(items), "traces": items}


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str) -> dict[str, Any]:
    """Return the full detail of one trace.

    404 if the trace is not in the ring buffer nor in the SQLite table.
    """
    tracer = get_tracer()
    row = await tracer.get(trace_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"trace {trace_id} not found")
    ca = row.get("created_at")
    if ca is not None and hasattr(ca, "isoformat"):
        row["created_at"] = ca.isoformat()
    return row


# ─────────────────────────────────────────────────────────────────────────────
# POST /chat/stream — SSE streaming version (Phase A2)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    """SSE streaming version of /chat.

    Sends Server-Sent Events:
    - {"type":"step","title":"Génération SQL..."} — progress updates
    - {"type":"chunk","content":"Vos "} — answer text chunks (word by word)
    - {"type":"done","response":{...full envelope...}} — final response

    The frontend reads the stream and updates the message progressively.
    Falls back to the non-streaming flow if any error occurs.
    """
    import asyncio
    import json as json_mod

    async def event_stream():
        try:
            # ── Auth (same dual-mode as /chat) ──
            jwt_ctx: TenantContext | None = try_get_tenant_context(request)
            if jwt_ctx is not None:
                if not jwt_ctx.role or not jwt_ctx.tenant_id:
                    yield f"data: {json_mod.dumps({'type': 'error', 'message': 'no active tenant'})}\n\n"
                    return
                role = jwt_ctx.role if jwt_ctx.role in ("producer", "admin") else "producer"
                producer_id = jwt_ctx.producer_id
                identity_id = jwt_ctx.email or f"user_{jwt_ctx.user_id}"
                tenant_id = jwt_ctx.tenant_id
            else:
                if not req.identity_id or not req.role:
                    yield f"data: {json_mod.dumps({'type': 'error', 'message': 'auth required'})}\n\n"
                    return
                role = req.role
                producer_id = req.producer_id
                identity_id = req.identity_id
                tenant_id = "dp"

            # ── Build tools (same as /chat) ──
            yield f"data: {json_mod.dumps({'type': 'step', 'title': 'Connexion aux données…'})}\n\n"
            try:
                connector = await get_connector_for_tenant(tenant_id)
            except TenantNotOnboardedError:
                envelope = {
                    "answer": "Votre workspace n'est pas encore configuré. Complétez l'onboarding pour activer l'agent.",
                    "sql": None, "scope_clause": None, "chart": None,
                    "tokens_in": 0, "tokens_out": 0, "latency_ms": 0,
                    "tool_calls": [], "steps": [], "security_checks": [],
                    "refused": True, "tables_touched": [], "sources": [],
                    "ops_analysis": None, "forecast_predictions": None, "trace_id": None,
                    "not_onboarded": True,
                }
                yield f"data: {json_mod.dumps({'type': 'done', 'response': envelope})}\n\n"
                return

            schema = connector.get_schema()
            allowed_tables = connector.get_allowed_tables(role)
            scope_column = "producer_id" if role == "producer" else None
            scope_value = producer_id if role == "producer" else None

            sql_tool = SqlReadTool(
                connector=connector, schema=schema,
                allowed_tables=allowed_tables, scope_column=scope_column,
                scope_value=scope_value, role=role,
            )
            rag_tool = RagSearchTool(
                connector=connector, tenant_id=tenant_id,
                producer_id=producer_id, role=role, tracer=get_tracer(),
            )
            forecast_tool = ForecastTool(
                connector=connector, tenant_id=tenant_id,
                producer_id=producer_id, role=role, tracer=get_tracer(),
            )
            orchestrator = AgentOrchestrator(
                sql_tool=sql_tool, role=role, producer_id=producer_id,
                identity_id=identity_id, tracer=get_tracer(),
                rag_tool=rag_tool, forecast_tool=forecast_tool,
            )

            # ── Run the agent ──
            yield f"data: {json_mod.dumps({'type': 'step', 'title': 'Analyse de la question…'})}\n\n"
            response = await orchestrator.run(req.message)

            # Build the full envelope (same as /chat).
            envelope = {
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
                "ops_analysis": response.ops_analysis,
                "forecast_predictions": response.forecast_predictions,
                "trace_id": response.trace_id,
            }

            # ── Stream the answer word by word ──
            answer = response.answer or ""
            # Split into words but keep the separators (spaces, newlines).
            import re
            words = re.findall(r'\S+\s*|\s+', answer)
            for word in words:
                yield f"data: {json_mod.dumps({'type': 'chunk', 'content': word})}\n\n"
                # Small delay for the typing effect (20ms per word).
                await asyncio.sleep(0.02)

            # ── Final event with the full envelope ──
            yield f"data: {json_mod.dumps({'type': 'done', 'response': envelope})}\n\n"

        except Exception as exc:
            import json as json_mod
            yield f"data: {json_mod.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
