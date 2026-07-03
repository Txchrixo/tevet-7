"""``POST /chat`` — the main entry point for the Producer Copilot.

Phase 0 status
==============

This router is **mounted** so the OpenAPI docs are populated and the
contract is visible, but the handler returns ``HTTP 501 NotImplemented``.
Phase 1 will replace the body with the real agent run.

Request / response contract (stable from Phase 0)
==================================================

Request body::

    {
      "message": "Quel est mon CA ce mois-ci ?",
      "tenant_id": "dp",
      "user_id": "u_42",
      "role": "producer"
    }

Response (Phase 1+): Server-Sent Events stream of chunks, ending with a
final ``AgentResponse`` JSON envelope. Chunk schema:

    event: token
    data: {"delta": "Votre CA"}

    event: tool_call
    data: {"name": "SqlReadTool", "input": "..."}

    event: tool_result
    data: {"rowcount": 1, "sql_used": "SELECT ..."}

    event: final
    data: { ... full AgentResponse ... }

    event: error
    data: {"message": "..."}

Why SSE and not WebSocket? SSE is simpler, plays well with FastAPI's
``StreamingResponse``, and is enough for a unidirectional token stream.
Phase 2 may add a WebSocket for richer interactions (interrupts,
clarifications).

Security model (the bit you CANNOT get wrong)
=============================================

1. **Auth.** The request MUST carry a ``Authorization: Bearer <jwt>``
   header. We verify the JWT with ``JWT_SECRET`` and extract:

       - ``tenant_id``
       - ``user_id``
       - ``role``        (producer | customer | admin)
       - ``scope_value`` (e.g. producer_id = 42)

   The body's ``tenant_id`` / ``role`` are accepted ONLY for dev convenience
   and are cross-checked against the JWT claims. **In production we NEVER
   trust client-supplied role/scope — the JWT is the only source of truth.**
   A mismatch returns ``HTTP 401``.

2. **Quota.** Before invoking the agent, we check that the tenant has not
   exceeded ``TOKEN_QUOTA_PER_TENANT_PER_DAY``. Quota is consumed
   post-hoc using ``tokens_used`` from the ``AgentResponse``. Exceeding the
   cap returns ``HTTP 429`` with a ``Retry-After`` header.

3. **Tracing.** Every request opens a Langfuse trace with the tenant_id,
   user_id, role, and scope_value as metadata. The orchestrator's LLM and
   tool calls become nested spans. The trace URL is returned in the final
   ``AgentResponse.trace_url`` for support debugging.

4. **Rate limit.** (Phase 2) Per-user sliding-window rate limit on top of
   the per-tenant token quota, to prevent a single user from starving the
   tenant.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

logger = logging.getLogger("tevet7.api.chat")

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Inbound chat request.

    ``tenant_id`` and ``role`` are present for dev convenience and for the
    prototype (which doesn't mint real JWTs yet). In production they are
    ALWAYS overwritten by the JWT claims; a mismatch raises ``HTTP 401``.
    """

    message: str = Field(..., min_length=1, max_length=4000, description="User message.")
    tenant_id: str = Field(..., description="Tenant identifier (e.g. 'dp').")
    user_id: str = Field(..., description="End-user identifier (verified via JWT).")
    role: Literal["producer", "customer", "admin"] = Field(
        ..., description="Caller role. Verified against JWT in production."
    )
    # Optional: conversation ID for multi-turn memory (Phase 2).
    conversation_id: str | None = None


class ChatError(BaseModel):
    """Standard error envelope for the non-streaming failure path."""

    message: str
    code: str
    trace_id: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Handler
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/chat", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def chat(req: ChatRequest, request: Request) -> dict:
    """Main chat endpoint. **Phase 0: not yet implemented.**

    The signature and the security model above are stable. Phase 1 replaces
    the body with the real implementation, which:

    1. Verifies the ``Authorization`` header (JWT) and extracts identity
       claims. ``req.tenant_id`` / ``req.role`` are cross-checked against
       the JWT; any mismatch returns ``HTTP 401``.
    2. Checks the per-tenant token quota (``HTTP 429`` on overflow).
    3. Opens a Langfuse trace.
    4. Constructs the per-request ``Connector`` + ``SqlReadTool`` + other
       tools, passing ``scope_value`` from the JWT.
    5. Builds the ``AgentOrchestrator`` with the rendered system prompt.
    6. Streams SSE chunks back via ``StreamingResponse``.
    7. On completion, persists ``tokens_used`` to the quota table and
       returns the trace URL in the final ``event: final`` chunk.

    Returns HTTP 501 in Phase 0 so the prototype can detect the missing
    backend and fall back to a mock without parsing errors.
    """
    logger.info(
        "chat called (Phase 0 stub) — tenant=%s user=%s role=%s msg_len=%d",
        req.tenant_id,
        req.user_id,
        req.role,
        len(req.message),
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "The /chat endpoint is not implemented in Phase 0. "
            "The skeleton returns 501 by design so the Next.js prototype can "
            "fall back to a mock. See app/api/chat.py and docs/architecture.md."
        ),
    )
