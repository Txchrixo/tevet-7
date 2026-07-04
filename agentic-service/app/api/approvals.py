"""``/api/approvals`` — Ops Copilot human-in-the-loop management endpoints.

Phase 4 — Ops Copilot backend (Task 26).

Endpoints
=========

- ``GET  /api/approvals``                       — list pending approval requests
  for the tenant (admin only). Optional ``status`` query param (default
  ``pending``).
- ``GET  /api/approvals/{id}``                  — full detail of one approval
  request: the agent_analysis (parsed JSON), the proposed_decision, the
  onboarding dossier, the human decision (if any).
- ``POST /api/approvals/{id}/decide``           — the human admin closes the
  loop. Body: ``{decision, reason, decided_by}``. ``decision`` is one of
  ``approve`` | ``reject`` | ``override``. Updates BOTH
  ``approval_requests.status`` AND ``producer_onboardings.status`` in the
  same transaction.
- ``POST /api/approvals/analyze/{onboarding_id}`` — re-run the OpsCopilotAgent
  pre-analysis on an onboarding dossier (useful if docs were updated).
  Updates the approval_request's ``agent_analysis`` /
  ``proposed_decision`` / ``proposed_reason`` / ``trace_id``.

Security model (Phase 6a — dual auth mode)
==========================================

Same pattern as ``app/api/chat.py``:

1. **JWT path (new, for the frontend)** — the caller sends
   ``Authorization: Bearer <jwt>``. The ``role`` is extracted from the
   verified JWT and must be ``"admin"`` (otherwise 403). The
   ``tenant_id`` is also extracted from the JWT. The ``admin=true``
   query/body param is IGNORED.
2. **Query/body path (legacy, for the eval + the old frontend)** — no
   ``Authorization`` header. The caller must send ``admin=true`` as a
   query param (GET) or in the body (POST decide). The ``tenant_id``
   comes from the query string and defaults to ``"dp"``.

All endpoints still log the caller's ``decided_by`` identity for audit.

Tracing
=======

- ``POST /api/approvals/{id}/decide`` opens a span
  ``ops_approval_decision`` so the human decision appears in Langfuse
  alongside the agent's original ``ops_onboarding_analysis`` span.
- ``POST /api/approvals/analyze/{onboarding_id}`` delegates to
  ``OpsCopilotAgent.analyze_onboarding`` which already opens its own
  ``ops_onboarding_analysis`` trace.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.agents.ops_copilot import OpsCopilotAgent
from app.auth.dependencies import TenantContext, try_get_tenant_context
from app.db_seed import approval_requests, get_engine, producer_onboardings
from app.tracing import get_tracer

logger = logging.getLogger("tevet7.api.approvals")

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _require_admin(admin: bool, *, source: str = "query") -> None:
    """Phase 4 admin gate. Raises 403 if the caller is not an admin.

    Real JWT-based role enforcement ships in Phase 6 — for now we trust
    the client's ``admin=true`` flag (documented in the endpoint contract).
    """
    if not admin:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Admin access required (set admin=true in {source}). "
                "Phase 6 will enforce this via JWT role claims."
            ),
        )


def _resolve_admin_context(
    request: Request,
    fallback_admin: bool,
    fallback_tenant_id: str = "dp",
    fallback_identity: str = "admin",
) -> tuple[bool, str, str]:
    """Return ``(is_admin, tenant_id, identity_id)`` for an approvals call.

    Phase 6a dual mode:
      - If an ``Authorization: Bearer <jwt>`` header is present and
        valid, the role/tenant_id/email are extracted from the JWT. The
        fallback values (admin query param, tenant_id query param,
        ``"admin"`` identity) are IGNORED. Returns ``is_admin = (role
        == "admin")``.
      - Otherwise the fallback values are used — this is the legacy
        path the eval relies on (``admin=true`` query param).
    """
    jwt_ctx: TenantContext | None = try_get_tenant_context(request)
    if jwt_ctx is not None:
        is_admin = (jwt_ctx.role == "admin")
        tenant_id = jwt_ctx.tenant_id or fallback_tenant_id
        identity_id = jwt_ctx.email or fallback_identity
        return is_admin, tenant_id, identity_id
    return bool(fallback_admin), fallback_tenant_id, fallback_identity


class _Namespace:
    """Tiny attribute-access wrapper around a dict.

    Used to keep the ``_approval_summary`` helper agnostic to whether it
    receives a SQLAlchemy Row or a plain dict — both expose ``.field``
    access via this wrapper.
    """

    def __init__(self, mapping: dict[str, Any]) -> None:
        self._mapping = mapping

    def __getattr__(self, name: str) -> Any:
        try:
            return self._mapping[name]
        except KeyError as exc:  # pragma: no cover — defensive
            raise AttributeError(name) from exc


def _parse_agent_analysis(raw: str | None) -> dict[str, Any] | None:
    """Parse the JSON ``agent_analysis`` column, returning None if missing."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"_raw": raw}


def _iso(value: Any) -> str | None:
    """ISO-format a datetime, returning None for None."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _approval_summary(row: Any, onboarding_row: Any | None = None) -> dict[str, Any]:
    """Project an approval_requests row + (optional) onboarding row into the
    list-endpoint summary shape."""
    analysis = _parse_agent_analysis(row.agent_analysis)
    confidence = (analysis or {}).get("confidence") if analysis else None
    out = {
        "id": row.id,
        "onboarding_id": row.onboarding_id,
        "request_type": row.request_type,
        "legal_name": onboarding_row.legal_name if onboarding_row else None,
        "siret": onboarding_row.siret if onboarding_row else None,
        "proposed_decision": row.proposed_decision,
        "proposed_reason": row.proposed_reason,
        "confidence": confidence,
        "status": row.status,
        "decided_by": row.decided_by,
        "decided_at": _iso(row.decided_at),
        "human_reason": row.human_reason,
        "created_at": _iso(row.created_at),
        "trace_id": row.trace_id,
    }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────────────────────


class DecisionRequest(BaseModel):
    """Body of ``POST /api/approvals/{id}/decide``."""

    decision: Literal["approve", "reject", "override"] = Field(
        ...,
        description=(
            "Human decision. 'approve' validates the agent's proposal; "
            "'reject' confirms a refusal; 'override' flips the agent's "
            "proposal (e.g. agent said reject, admin approves with "
            "regularisation plan)."
        ),
    )
    reason: str = Field(
        ..., min_length=1, max_length=2000,
        description="Human-readable reason — required especially for 'override'.",
    )
    decided_by: str = Field(
        ..., min_length=1, max_length=200,
        description="Admin identity_id (audit).",
    )
    admin: bool = Field(
        False,
        description="Phase 4 admin gate. Must be true (Phase 6 = JWT role).",
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/approvals — list
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/approvals")
async def list_approvals(
    request: Request,
    admin: bool = Query(False, description="Phase 4 admin gate (must be true). IGNORED when Authorization: Bearer is present."),
    status: str = Query(
        "pending",
        description="Filter by approval_requests.status (pending|approved|rejected|overridden|all).",
    ),
    tenant_id: str = Query("dp", description="Tenant id (default 'dp'). IGNORED when Authorization: Bearer is present."),
) -> dict[str, Any]:
    """List approval requests for the tenant (admin only).

    Returns ``[{id, onboarding_id, legal_name, siret, proposed_decision,
    proposed_reason, confidence, status, created_at, agent_analysis}]``.

    The ``agent_analysis`` field is included so the admin UI can render the
    agent's checks + issues inline without a second round-trip to
    ``GET /api/approvals/{id}``.

    Phase 6a — dual auth mode: when an ``Authorization: Bearer <jwt>``
    header is present, the role/tenant_id are extracted from the JWT and
    the query params are ignored.
    """
    is_admin, tenant_id, identity_id = _resolve_admin_context(
        request, admin, tenant_id,
    )
    _require_admin(is_admin)
    t0 = time.monotonic()
    tracer = get_tracer()
    ctx = tracer.start_trace(
        "ops_approval_list",
        {"tenant_id": tenant_id, "role": "admin", "identity_id": identity_id},
    )
    span = tracer.start_span(ctx, "ops_approval_list", tenant_id=tenant_id, status=status)
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            # Join approval_requests + producer_onboardings and split each
            # row by column-name range. We select every column from both
            # tables, then group them back into per-table dicts.
            ar_cols = [c.label(f"ar_{c.name}") for c in approval_requests.c]
            ob_cols = [c.label(f"ob_{c.name}") for c in producer_onboardings.c]
            stmt = (
                select(*ar_cols, *ob_cols)
                .select_from(
                    approval_requests.join(
                        producer_onboardings,
                        producer_onboardings.c.id == approval_requests.c.onboarding_id,
                    )
                )
                .where(approval_requests.c.tenant_id == tenant_id)
            )
            if status and status != "all":
                stmt = stmt.where(approval_requests.c.status == status)
            stmt = stmt.order_by(approval_requests.c.created_at.asc())
            r = await conn.execute(stmt)
            items = []
            for row in r.fetchall():
                mapping = row._mapping
                ar_row = _Namespace({
                    k[len("ar_"):]: mapping[k]
                    for k in mapping
                    if k.startswith("ar_")
                })
                ob_row = _Namespace({
                    k[len("ob_"):]: mapping[k]
                    for k in mapping
                    if k.startswith("ob_")
                })
                summary = _approval_summary(ar_row, ob_row)
                summary["agent_analysis"] = _parse_agent_analysis(ar_row.agent_analysis)
                items.append(jsonable_encoder(summary))
        latency_ms = int((time.monotonic() - t0) * 1000)
        tracer.end_span(
            ctx, span, status="ok", count=len(items), latency_ms=latency_ms,
        )
        await tracer.end_trace(
            ctx,
            {
                "answer": f"approvals list: {len(items)} items",
                "sql": None,
                "intent": "ops_approval_list",
                "refused": False,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": latency_ms,
                "tool_calls": [{"name": "list_approvals", "latency_ms": latency_ms, "success": True}],
                "steps": [],
            },
        )
        return {"count": len(items), "approvals": items}
    except HTTPException as exc:
        tracer.end_span(ctx, span, status="error", error=str(exc.detail))
        await tracer.end_trace(
            ctx,
            {"answer": "", "error": str(exc.detail), "refused": True,
             "tokens_in": 0, "tokens_out": 0,
             "latency_ms": int((time.monotonic() - t0) * 1000)},
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_approvals failed")
        tracer.end_span(ctx, span, status="error", error=str(exc))
        await tracer.end_trace(
            ctx,
            {"answer": "", "error": str(exc), "refused": True,
             "tokens_in": 0, "tokens_out": 0,
             "latency_ms": int((time.monotonic() - t0) * 1000)},
        )
        raise HTTPException(status_code=500, detail=f"list failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/approvals/{id} — detail
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/approvals/{approval_id}")
async def get_approval(
    approval_id: int,
    request: Request,
    admin: bool = Query(False, description="Phase 4 admin gate (must be true). IGNORED when Authorization: Bearer is present."),
) -> dict[str, Any]:
    """Return the full detail of one approval request.

    Includes the parsed ``agent_analysis`` JSON, the proposed_decision, the
    proposed_reason, the human decision (if any), and the onboarding dossier
    itself (so the admin UI can show the source documents + declared fields
    alongside the agent's checks).

    Phase 6a — dual auth mode: when an ``Authorization: Bearer <jwt>``
    header is present, the role is extracted from the JWT and must be
    ``"admin"``; the ``admin`` query param is ignored.
    """
    is_admin, _tenant_id, _identity_id = _resolve_admin_context(request, admin)
    _require_admin(is_admin)
    t0 = time.monotonic()
    tracer = get_tracer()
    ctx = tracer.start_trace(
        "ops_approval_detail",
        {"tenant_id": "dp", "role": "admin", "identity_id": "admin"},
    )
    span = tracer.start_span(ctx, "ops_approval_detail", approval_id=approval_id)
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            ar_cols = [c.label(f"ar_{c.name}") for c in approval_requests.c]
            ob_cols = [c.label(f"ob_{c.name}") for c in producer_onboardings.c]
            r = await conn.execute(
                select(*ar_cols, *ob_cols)
                .select_from(
                    approval_requests.join(
                        producer_onboardings,
                        producer_onboardings.c.id == approval_requests.c.onboarding_id,
                    )
                )
                .where(approval_requests.c.id == approval_id)
            )
            row = r.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"approval request {approval_id} not found",
                )
            mapping = row._mapping
            ar_row = _Namespace({
                k[len("ar_"):]: mapping[k]
                for k in mapping
                if k.startswith("ar_")
            })
            ob_row = _Namespace({
                k[len("ob_"):]: mapping[k]
                for k in mapping
                if k.startswith("ob_")
            })
        out = {
            "approval": _approval_summary(ar_row, ob_row),
            "agent_analysis": _parse_agent_analysis(ar_row.agent_analysis),
            "onboarding": {
                "id": ob_row.id,
                "tenant_id": ob_row.tenant_id,
                "legal_name": ob_row.legal_name,
                "siret": ob_row.siret,
                "siret_valid": ob_row.siret_valid,
                "email": ob_row.email,
                "phone": ob_row.phone,
                "declared_address": ob_row.declared_address,
                "document_address": ob_row.document_address,
                "rib_document_present": ob_row.rib_document_present,
                "id_document_present": ob_row.id_document_present,
                "professional_certificate_present": ob_row.professional_certificate_present,
                "professional_certificate_expiry": ob_row.professional_certificate_expiry,
                "submitted_at": _iso(ob_row.submitted_at),
                "status": ob_row.status,
                "rejection_reason": ob_row.rejection_reason,
            },
        }
        latency_ms = int((time.monotonic() - t0) * 1000)
        tracer.end_span(ctx, span, status="ok", latency_ms=latency_ms)
        await tracer.end_trace(
            ctx,
            {
                "answer": f"approval detail: {approval_id}",
                "sql": None,
                "intent": "ops_approval_detail",
                "refused": False,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": latency_ms,
                "tool_calls": [{"name": "get_approval", "latency_ms": latency_ms, "success": True}],
                "steps": [],
            },
        )
        return jsonable_encoder(out)
    except HTTPException as exc:
        tracer.end_span(ctx, span, status="error", error=str(exc.detail))
        await tracer.end_trace(
            ctx,
            {"answer": "", "error": str(exc.detail), "refused": True,
             "tokens_in": 0, "tokens_out": 0,
             "latency_ms": int((time.monotonic() - t0) * 1000)},
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_approval failed")
        tracer.end_span(ctx, span, status="error", error=str(exc))
        await tracer.end_trace(
            ctx,
            {"answer": "", "error": str(exc), "refused": True,
             "tokens_in": 0, "tokens_out": 0,
             "latency_ms": int((time.monotonic() - t0) * 1000)},
        )
        raise HTTPException(status_code=500, detail=f"get failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/approvals/{id}/decide — human decision (the HITL close-the-loop)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: int,
    request: Request,
    body: DecisionRequest,
) -> dict[str, Any]:
    """Close the loop on an approval request.

    Body:
      - ``decision``: ``approve`` | ``reject`` | ``override``
      - ``reason``: human-readable reason (required, especially for override)
      - ``decided_by``: admin identity_id (audit)
      - ``admin``: must be ``true`` (Phase 4 gate; Phase 6 = JWT role).
        IGNORED when ``Authorization: Bearer <jwt>`` is present.

    The endpoint updates BOTH tables in one transaction:
      - ``approval_requests.status``: approved | rejected | overridden
      - ``producer_onboardings.status``: approved | rejected (no 'overridden'
        status for the dossier — the admin's actual decision wins)
      - ``producer_onboardings.rejection_reason`` (if reject)
      - ``approval_requests.decided_by`` / ``decided_at`` / ``human_reason``

    Tracing: opens a span ``ops_approval_decision`` so the human decision
    appears in Langfuse alongside the agent's original ``ops_onboarding_analysis``
    span (same trace tree if the user re-uses the agent's trace_id, otherwise
    a sibling trace).

    Phase 6a — dual auth mode: when an ``Authorization: Bearer <jwt>``
    header is present, the role is extracted from the JWT and must be
    ``"admin"``; the body's ``admin`` field is ignored. The
    ``decided_by`` field is still required (audit trail) — when using
    JWT, the frontend should set ``decided_by`` to the admin's email.
    """
    is_admin, _tenant_id, _identity_id = _resolve_admin_context(
        request, body.admin,
    )
    _require_admin(is_admin, source="body")
    t0 = time.monotonic()
    tracer = get_tracer()
    ctx = tracer.start_trace(
        f"ops_approval_decision:{approval_id}",
        {
            "tenant_id": "dp",
            "role": "admin",
            "identity_id": body.decided_by,
            "approval_id": approval_id,
            "decision": body.decision,
        },
    )
    span = tracer.start_span(
        ctx, "ops_approval_decision",
        approval_id=approval_id,
        decision=body.decision,
        decided_by=body.decided_by,
    )
    try:
        # Map the human decision to:
        # - approval_requests.status (4 values)
        # - producer_onboardings.status (2 values: approved | rejected)
        if body.decision == "approve":
            ar_status = "approved"
            ob_status = "approved"
            ob_rejection_reason = None
        elif body.decision == "reject":
            ar_status = "rejected"
            ob_status = "rejected"
            ob_rejection_reason = body.reason
        else:  # override
            ar_status = "overridden"
            # When overriding, the admin's intent determines the onboarding
            # status. We infer it from the proposed_decision the agent made:
            # - Agent proposed "reject" + admin overrides → approve the dossier.
            # - Agent proposed "approve" + admin overrides → reject the dossier.
            # - Otherwise keep the dossier in pending (request_info override).
            engine = get_engine()
            async with engine.connect() as conn:
                r = await conn.execute(
                    select(approval_requests.c.proposed_decision)
                    .where(approval_requests.c.id == approval_id)
                )
                row = r.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"approval request {approval_id} not found",
                )
            proposed = row.proposed_decision
            if proposed == "reject":
                ob_status = "approved"
                ob_rejection_reason = None
            elif proposed == "approve":
                ob_status = "rejected"
                ob_rejection_reason = body.reason
            else:  # request_info override → leave dossier pending
                ob_status = "pending"
                ob_rejection_reason = None

        now = datetime.utcnow()
        engine = get_engine()
        async with engine.begin() as conn:
            # 1) Verify the approval request exists + load its onboarding_id.
            r = await conn.execute(
                select(approval_requests).where(approval_requests.c.id == approval_id)
            )
            ar_row = r.fetchone()
            if ar_row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"approval request {approval_id} not found",
                )
            onboarding_id = ar_row.onboarding_id

            # 2) Update the approval_requests row.
            await conn.execute(
                update(approval_requests)
                .where(approval_requests.c.id == approval_id)
                .values(
                    status=ar_status,
                    decided_by=body.decided_by,
                    decided_at=now,
                    human_reason=body.reason,
                )
            )
            # 3) Update the producer_onboardings row (mirror the decision).
            await conn.execute(
                update(producer_onboardings)
                .where(producer_onboardings.c.id == onboarding_id)
                .values(
                    status=ob_status,
                    rejection_reason=ob_rejection_reason,
                )
            )

        # Re-read the updated rows for the response.
        async with engine.connect() as conn:
            ar_cols = [c.label(f"ar_{c.name}") for c in approval_requests.c]
            ob_cols = [c.label(f"ob_{c.name}") for c in producer_onboardings.c]
            r = await conn.execute(
                select(*ar_cols, *ob_cols)
                .select_from(
                    approval_requests.join(
                        producer_onboardings,
                        producer_onboardings.c.id == approval_requests.c.onboarding_id,
                    )
                )
                .where(approval_requests.c.id == approval_id)
            )
            row = r.fetchone()
            if row is None:
                # Shouldn't happen — we just updated it.
                raise HTTPException(status_code=500, detail="re-read failed")
            mapping = row._mapping
            ar_row = _Namespace({
                k[len("ar_"):]: mapping[k]
                for k in mapping
                if k.startswith("ar_")
            })
            ob_row = _Namespace({
                k[len("ob_"):]: mapping[k]
                for k in mapping
                if k.startswith("ob_")
            })

        latency_ms = int((time.monotonic() - t0) * 1000)
        tracer.end_span(
            ctx, span, status="ok",
            ar_status=ar_status, ob_status=ob_status,
            latency_ms=latency_ms,
        )
        await tracer.end_trace(
            ctx,
            {
                "answer": f"approval {approval_id} → {ar_status} (dossier {ob_status})",
                "sql": None,
                "intent": "ops_approval_decision",
                "refused": False,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": latency_ms,
                "tool_calls": [{
                    "name": "decide_approval",
                    "latency_ms": latency_ms,
                    "success": True,
                }],
                "steps": [],
            },
        )
        return jsonable_encoder({
            "approval": _approval_summary(ar_row, ob_row),
            "onboarding": {
                "id": ob_row.id,
                "legal_name": ob_row.legal_name,
                "siret": ob_row.siret,
                "status": ob_row.status,
                "rejection_reason": ob_row.rejection_reason,
            },
            "decision_applied": {
                "approval_status": ar_status,
                "onboarding_status": ob_status,
                "decided_by": body.decided_by,
                "decided_at": _iso(now),
                "human_reason": body.reason,
            },
        })
    except HTTPException as exc:
        tracer.end_span(ctx, span, status="error", error=str(exc.detail))
        await tracer.end_trace(
            ctx,
            {"answer": "", "error": str(exc.detail), "refused": True,
             "tokens_in": 0, "tokens_out": 0,
             "latency_ms": int((time.monotonic() - t0) * 1000)},
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("decide_approval failed")
        tracer.end_span(ctx, span, status="error", error=str(exc))
        await tracer.end_trace(
            ctx,
            {"answer": "", "error": str(exc), "refused": True,
             "tokens_in": 0, "tokens_out": 0,
             "latency_ms": int((time.monotonic() - t0) * 1000)},
        )
        raise HTTPException(status_code=500, detail=f"decide failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/approvals/analyze/{onboarding_id} — re-run the agent analysis
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/approvals/analyze/{onboarding_id}")
async def reanalyze_onboarding(
    onboarding_id: int,
    request: Request,
    admin: bool = Query(False, description="Phase 4 admin gate (must be true). IGNORED when Authorization: Bearer is present."),
) -> dict[str, Any]:
    """Re-run the OpsCopilotAgent pre-analysis on an onboarding dossier.

    Useful when the producer has uploaded new docs (e.g. the missing cert
    was added) — the agent re-runs its 5 checks and produces a fresh
    proposed_decision. Updates the corresponding approval_request's
    ``agent_analysis`` / ``proposed_decision`` / ``proposed_reason`` /
    ``trace_id`` columns.

    Returns the fresh ``OpsAnalysis`` dict + the updated approval_request id.

    Phase 6a — dual auth mode: when an ``Authorization: Bearer <jwt>``
    header is present, the role is extracted from the JWT and must be
    ``"admin"``; the ``admin`` query param is ignored.
    """
    is_admin, _tenant_id, _identity_id = _resolve_admin_context(request, admin)
    _require_admin(is_admin)
    t0 = time.monotonic()
    engine = get_engine()

    # 1) Load the onboarding dossier.
    async with engine.connect() as conn:
        r = await conn.execute(
            select(producer_onboardings).where(producer_onboardings.c.id == onboarding_id)
        )
        ob_row = r.fetchone()
        if ob_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"onboarding {onboarding_id} not found",
            )
        ob_dict = dict(ob_row._mapping)
        # Find the linked approval_request (if any).
        r = await conn.execute(
            select(approval_requests).where(
                approval_requests.c.onboarding_id == onboarding_id
            )
        )
        ar_row = r.fetchone()

    # 2) Run the agent.
    agent = OpsCopilotAgent(tracer=get_tracer())
    analysis = await agent.analyze_onboarding(ob_dict)

    # 3) Persist the fresh analysis on the approval_request row.
    ar_id = None
    if ar_row is not None:
        ar_id = ar_row.id
        async with engine.begin() as conn:
            await conn.execute(
                update(approval_requests)
                .where(approval_requests.c.id == ar_id)
                .values(
                    agent_analysis=json.dumps(analysis.to_dict(), ensure_ascii=False),
                    proposed_decision=analysis.proposed_decision,
                    proposed_reason=analysis.proposed_reason,
                    trace_id=analysis.trace_id,
                )
            )
    else:
        # No existing approval_request — create one.
        async with engine.begin() as conn:
            result = await conn.execute(
                approval_requests.insert()
                .values(
                    tenant_id="dp",
                    onboarding_id=onboarding_id,
                    request_type="onboarding_analysis",
                    agent_analysis=json.dumps(analysis.to_dict(), ensure_ascii=False),
                    proposed_decision=analysis.proposed_decision,
                    proposed_reason=analysis.proposed_reason,
                    status="pending",
                    created_at=datetime.utcnow(),
                    trace_id=analysis.trace_id,
                )
                .returning(approval_requests.c.id)
            )
            ar_id = int(result.scalar_one())

    latency_ms = int((time.monotonic() - t0) * 1000)
    return {
        "approval_id": ar_id,
        "onboarding_id": onboarding_id,
        "analysis": analysis.to_dict(),
        "latency_ms": latency_ms,
    }


@router.get("/approvals/health", include_in_schema=False)
async def approvals_health() -> dict[str, Any]:
    """Lightweight health probe scoped to the approvals router."""
    return {"status": "ok", "router": "approvals"}
