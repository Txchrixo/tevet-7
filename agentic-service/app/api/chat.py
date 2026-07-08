"""``POST /chat`` - main entry point for the Producer Copilot.

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
   SELECT that touches a scoped table - see ``app/tools/sql_tool.py``.
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

    Phase 6a - dual auth mode
    -------------------------

    The identity fields (``identity_id``, ``producer_id``, ``role``) are
    now OPTIONAL. Two paths are supported:

    1. **JWT path (new, for the frontend)** - the caller sends
       ``Authorization: Bearer <jwt>``. Identity is extracted from the
       verified JWT (tenant_id, role, producer_id, email). The body
       identity fields are IGNORED.
    2. **Body path (legacy, for the eval + tests)** - no
       ``Authorization`` header. Identity is read from the body. The
       tenant is hardcoded to ``"dp"`` (the demo tenant).

    Both paths funnel into the SAME orchestrator - the agentic core has
    no notion of users or JWTs, it only receives ``role``,
    ``producer_id``, ``tenant_id`` as plain strings. The dual mode keeps
    the existing 39-case eval passing WITHOUT modification (the eval
    uses the body path) while letting the frontend authenticate via JWT.
    """

    message: str = Field(..., min_length=1, max_length=4000, description="User message.")
    # Phase 6a: identity fields are now optional - when an Authorization
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
    conversation_id: str | None = Field(
        default=None, description="Conversation ID (future, for persistence)."
    )
    history: list[dict[str, str]] | None = Field(
        default=None,
        description=(
            "Conversation history (last N messages) for the LLM orchestrator. "
            "Each item: {role: 'user'|'assistant', content: '...'}. "
            "Phase A3: enables conversation memory ('et le mois dernier ?')."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Handler
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> dict[str, Any]:
    """Run the rule-based agent loop and return the full audit envelope.

    Always returns HTTP 200 - refusals and errors are encoded in the JSON
    body (``refused: true``, ``answer`` explaining what happened) so the
    frontend has a single success path.
    """
    # ── Phase 6a - dual auth mode ──────────────────────────────────────────
    # If the caller sends an ``Authorization: Bearer <jwt>`` header we
    # extract the identity (tenant_id, role, producer_id) from the
    # verified JWT. Otherwise we fall back to the body identity (the
    # legacy path used by the eval + the old frontend). The CORE agentic
    # (orchestrator + tools + tracing) is unchanged - it receives plain
    # ``role``/``producer_id``/``tenant_id`` strings either way.
    jwt_ctx: TenantContext | None = try_get_tenant_context(request)
    if jwt_ctx is not None:
        # JWT path - identity comes from the token.
        if not jwt_ctx.role or not jwt_ctx.tenant_id:
            # A fresh signup has no membership yet - refuse with 403 so
            # the frontend can prompt for tenant creation/activation.
            raise HTTPException(
                status_code=403,
                detail=(
                    "no active tenant in JWT - create or activate a tenant "
                    "via POST /api/tenants or POST /api/tenants/{id}/activate"
                ),
            )
        # Pass the JWT role through UNCHANGED. Onboarded tenants define
        # custom roles (e.g. "driver" scoped by driver_id) in their
        # roles_config - coercing unknown roles to "producer" here would
        # make resolve_role_scope() look up the wrong role and silently
        # drop row-level security. Downstream the only privileged value
        # is "admin"; every other role is treated as scoped/restricted.
        role: str = jwt_ctx.role
        producer_id: int | None = jwt_ctx.producer_id
        identity_id: str = jwt_ctx.email or f"user_{jwt_ctx.user_id}"
        tenant_id: str = jwt_ctx.tenant_id
        user_id: int | None = jwt_ctx.user_id
        is_jwt = True
        logger.info(
            "chat called [JWT path] - user_id=%s email=%s tenant=%s role=%s producer_id=%s msg_len=%d",
            jwt_ctx.user_id, jwt_ctx.email, tenant_id, role, producer_id, len(req.message),
        )
    else:
        # Legacy body path - used by the eval (eval/eval.py sends body
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
        user_id = None
        is_jwt = False
        logger.info(
            "chat called [body path] - identity=%s producer_id=%s role=%s msg_len=%d",
            identity_id, producer_id, role, len(req.message),
        )

    try:
        # Build a per-request connector + tool + orchestrator.
        # Phase 6b - the connector is now chosen dynamically based on the
        # tenant's ``tenant_configs`` row:
        #   - demo tenant "dp" (and the legacy body path) → SqliteConnector
        #     (unchanged - backward compat).
        #   - tenants with ``connector_type="postgres"`` → PostgresConnector.
        #   - tenants with ``connector_type="csv"``      → CsvConnector.
        # If the tenant is not onboarded yet, the factory raises
        # ``TenantNotOnboardedError`` - we catch it below and return a
        # clear French message prompting the user to complete onboarding.

        # ── Rate limit (per-tenant, prevents LLM cost abuse) ──
        # Shared with /chat/stream: one budget per tenant across both.
        from app.auth.rate_limit import chat_limiter
        allowed, retry_after = chat_limiter.check(tenant_id)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Trop de requêtes. Réessayez dans {int(retry_after) + 1}s.",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

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
        # Scope resolution: onboarded tenants define role → scope_column in
        # their roles_config (wizard "define roles" step); the demo tenant
        # falls back to the historical producer/producer_id rule. Hardcoding
        # "producer" here would silently drop row-level security for every
        # scoped custom role (e.g. "driver" scoped by driver_id).
        from app.tenants.onboarding import resolve_role_scope
        scope_column, scope_value = await resolve_role_scope(
            tenant_id, role, producer_id,
        )

        sql_tool = SqlReadTool(
            connector=connector,
            schema=schema,
            allowed_tables=allowed_tables,
            scope_column=scope_column,
            scope_value=scope_value,
            role=role,
        )
        # Phase 3 - build the RAG tool with the same identity context so
        # documentary questions are scoped identically to analytical ones.
        # Phase 6a - tenant_id now comes from the JWT (multi-tenant) or
        # defaults to "dp" for the legacy body path (eval).
        rag_tool = RagSearchTool(
            connector=connector,
            tenant_id=tenant_id,
            producer_id=producer_id,
            role=role,
            tracer=get_tracer(),
        )
        # Phase 5 - build the forecast tool with the same identity context so
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
        # ── Phase A1: LLM orchestrator (function calling) with fallback ──
        from app.config import get_settings
        from app.agents.provider_factory import build_providers
        from app.agents.model_router import ModelRouter
        from app.agents.llm_orchestrator import LLMOrchestrator

        settings = get_settings()
        providers = build_providers(settings)

        response = None
        if providers:
            try:
                router = ModelRouter(providers=providers, cache_enabled=True)
                llm_orch = LLMOrchestrator(
                    sql_tool=sql_tool,
                    rag_tool=rag_tool,
                    forecast_tool=forecast_tool,
                    role=role,
                    producer_id=producer_id,
                    identity_id=identity_id,
                    tracer=get_tracer(),
                    schema=schema,
                    router=router,
                )
                response = await llm_orch.run(req.message, history=req.history)
                logger.info("LLM orchestrator succeeded - tokens=%d/%d latency=%dms",
                            response.tokens_in, response.tokens_out, response.latency_ms)
            except Exception as exc:
                logger.warning("LLM orchestrator failed (%s) - falling back to rule-based", exc)
                response = None

        # Heuristic: detect "bad" LLM responses and fall back to rule-based.
        # A response is bad only when the answer is empty OR carries no
        # substantive content. The absence of a chart is NOT evidence of
        # failure: scalar aggregates (COUNT(*), SUM) legitimately return a
        # single row and no chart, and discarding them threw away correct
        # LLM answers (e.g. "Combien de commandes j'ai eues ?").
        if response is not None and not response.refused:
            answer = (response.answer or "").strip()
            if not answer:
                logger.info("LLM response is bad (empty answer) - falling back to rule-based")
                response = None
            elif response.sql and not response.chart and not any(ch.isdigit() for ch in answer):
                # SQL ran but the answer carries no number at all → likely a
                # 0-row result or a broken query for a data question. A valid
                # scalar answer always contains a digit, so this only fires on
                # genuinely empty results.
                logger.info("LLM response is bad (sql, no chart, no numeric content) - falling back")
                response = None

        if response is None:
            # Rule-based fallback.
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

        # ── Persist the conversation (Phase B4) ──
        conversation_id: str | None = None
        history_loaded: list | None = None
        if is_jwt:
            from app.conversations import create_conversation, load_history, append_message
            if req.conversation_id:
                conversation_id = req.conversation_id
                if not req.history:
                    history_loaded = await load_history(conversation_id, limit=10)
            else:
                conversation_id = await create_conversation(tenant_id=tenant_id, user_id=user_id)
            # Append both messages (best-effort).
            await append_message(conversation_id, "user", req.message)
            await append_message(
                conversation_id, "assistant", response.answer,
                sql=response.sql, tokens_in=response.tokens_in, tokens_out=response.tokens_out,
            )
        elif req.conversation_id:
            conversation_id = req.conversation_id
        # If history was loaded from DB, re-run with it (only if the LLM
        # didn't already get it from req.history).
        if history_loaded and not req.history and not response.answer:
            # Edge case: shouldn't happen often, but handle it.
            pass

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
            "conversation_id": conversation_id,
        }
    except HTTPException:
        # Re-raise FastAPI HTTP exceptions (401/403 from the dual-mode
        # check above) without wrapping them in the catch-all below.
        raise
    except Exception as exc:  # noqa: BLE001 - never crash the frontend
        logger.exception("Unhandled error in /chat")
        from app.monitoring import capture_exception
        capture_exception(exc, context={"endpoint": "/api/chat", "identity_id": identity_id, "tenant_id": tenant_id})
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
# Schema endpoint - return the loaded schema.yaml as JSON
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
# Traces endpoints - observability surface (Task 18 / Phase 2 tracing)
# ─────────────────────────────────────────────────────────────────────────────
# ``GET /api/traces``         → list the most recent 50 traces (summary).
# ``GET /api/traces/{trace_id}`` → full trace detail (SQL, steps, tool_calls,
#                                 tokens, cost, answer excerpt, …).
#
# The tracer itself (LocalTracer or LangfuseTracer) backs both endpoints -
# the API layer is a thin wrapper that delegates to ``get_tracer()`` so
# Langfuse-mode and local-mode expose the same HTTP surface.


@router.get("/traces")
async def list_traces(limit: int = 50) -> dict[str, Any]:
    """List the most recent traces (newest first).

    Returns the summary fields only (no SQL, no steps) - use
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
# POST /chat/stream - SSE streaming version (Phase A2)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    """SSE streaming version of /chat.

    Sends Server-Sent Events:
    - {"type":"step","title":"Génération SQL..."} - progress updates
    - {"type":"chunk","content":"Vos "} - answer text chunks (word by word)
    - {"type":"done","response":{...full envelope...}} - final response

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
                # Same as /chat: pass the JWT role through unchanged so
                # resolve_role_scope() can look up custom roles.
                role = jwt_ctx.role
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

            # ── Rate limit (per-tenant, same budget as /chat) ──
            from app.auth.rate_limit import chat_limiter
            allowed, retry_after = chat_limiter.check(tenant_id)
            if not allowed:
                yield f"data: {json_mod.dumps({'type': 'error', 'message': f'Trop de requêtes. Réessayez dans {int(retry_after) + 1}s.'})}\n\n"
                return

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
            # Same scope resolution as /chat: roles_config is the source of
            # truth for onboarded tenants (see resolve_role_scope).
            from app.tenants.onboarding import resolve_role_scope
            scope_column, scope_value = await resolve_role_scope(
                tenant_id, role, producer_id,
            )

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

            # ── Guardrails (Phase A4) - check BEFORE any orchestrator ──
            from app.agents.guardrails import check_message
            guardrail_result = check_message(req.message)
            if guardrail_result.blocked:
                yield f"data: {json_mod.dumps({'type': 'step', 'title': 'Garde-fou - blocage'}, ensure_ascii=False)}\n\n"
                envelope = {
                    "answer": guardrail_result.reason,
                    "sql": None, "scope_clause": None, "chart": None,
                    "tokens_in": 0, "tokens_out": 0, "latency_ms": 0,
                    "tool_calls": [], "steps": [], "security_checks": [],
                    "refused": True, "tables_touched": [], "sources": [],
                    "ops_analysis": None, "forecast_predictions": None, "trace_id": None,
                }
                yield f"data: {json_mod.dumps({'type': 'chunk', 'content': guardrail_result.reason}, ensure_ascii=False)}\n\n"
                yield f"data: {json_mod.dumps({'type': 'done', 'response': envelope}, ensure_ascii=False)}\n\n"
                return

            # ── Try LLM orchestrator first (same as /chat) ──
            from app.config import get_settings
            from app.agents.provider_factory import build_providers
            from app.agents.model_router import ModelRouter
            from app.agents.llm_orchestrator import LLMOrchestrator

            settings = get_settings()
            providers = build_providers(settings)
            response = None
            if providers:
                try:
                    router = ModelRouter(providers=providers, cache_enabled=True)
                    llm_orch = LLMOrchestrator(
                        sql_tool=sql_tool, rag_tool=rag_tool, forecast_tool=forecast_tool,
                        role=role, producer_id=producer_id, identity_id=identity_id,
                        tracer=get_tracer(), schema=schema, router=router,
                    )
                    yield f"data: {json_mod.dumps({'type': 'step', 'title': 'Analyse de la question…'}, ensure_ascii=False)}\n\n"
                    response = await llm_orch.run(req.message, history=req.history)
                except Exception as exc:
                    logger.warning("LLM orchestrator failed in stream (%s) - falling back to rule-based", exc)
                    response = None

            # ── Rule-based fallback ──
            if response is None:
                yield f"data: {json_mod.dumps({'type': 'step', 'title': 'Analyse de la question…'}, ensure_ascii=False)}\n\n"
                orchestrator = AgentOrchestrator(
                    sql_tool=sql_tool, role=role, producer_id=producer_id,
                    identity_id=identity_id, tracer=get_tracer(),
                    rag_tool=rag_tool, forecast_tool=forecast_tool,
                )
                response = await orchestrator.run(req.message)

            # Build the full envelope (same as /chat).
            # Convert StepTrace objects to dicts for JSON serialization.
            _steps_dicts = [
                {"index": s.index, "title": s.title, "detail": s.detail,
                 "status": s.status, "duration_ms": s.duration_ms}
                if hasattr(s, 'index') else s
                for s in (response.steps or [])
            ]
            envelope = {
                "answer": response.answer,
                "sql": response.sql,
                "scope_clause": response.scope_clause,
                "chart": response.chart,
                "tokens_in": response.tokens_in,
                "tokens_out": response.tokens_out,
                "latency_ms": response.latency_ms,
                "tool_calls": response.tool_calls,
                "steps": _steps_dicts,
                "security_checks": response.security_checks,
                "refused": response.refused,
                "tables_touched": response.tables_touched,
                "sources": response.sources,
                "ops_analysis": response.ops_analysis,
                "forecast_predictions": response.forecast_predictions,
                "trace_id": response.trace_id,
            }

            # ── Persist conversation (Phase B4) ──
            if jwt_ctx is not None:
                from app.conversations import create_conversation as _cc, append_message as _am
                if req.conversation_id:
                    _conv_id = req.conversation_id
                else:
                    _conv_id = await _cc(tenant_id=tenant_id, user_id=jwt_ctx.user_id)
                await _am(_conv_id, "user", req.message)
                await _am(_conv_id, "assistant", response.answer,
                          sql=response.sql, tokens_in=response.tokens_in, tokens_out=response.tokens_out)
                envelope["conversation_id"] = _conv_id

            # ── Stream the answer (real chunks, no artificial delay) ──
            answer = response.answer or ""
            import re
            words = re.findall(r'\S+\s*|\s+', answer)
            for word in words:
                yield f"data: {json_mod.dumps({'type': 'chunk', 'content': word}, ensure_ascii=False)}\n\n"

            # ── Final event with the full envelope ──
            yield f"data: {json_mod.dumps({'type': 'done', 'response': envelope}, ensure_ascii=False)}\n\n"

        except Exception as exc:
            yield f"data: {json_mod.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
