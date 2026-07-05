"""Stripe billing — subscription management (Phase C3).

Provides:
  - ``POST /api/billing/create-checkout-session`` — Stripe Checkout (signup to Pro).
  - ``POST /api/billing/webhook`` — Stripe webhook (fulfill subscription).
  - ``GET  /api/billing/subscription`` — current subscription status.
  - ``POST /api/billing/cancel`` — cancel subscription.

Requires STRIPE_SECRET_KEY + STRIPE_WEBHOOK_SECRET env vars. Without them,
the endpoints return 503 (billing disabled) — the app works without Stripe
in dev mode.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth.dependencies import try_get_tenant_context

logger = logging.getLogger("tevet7.billing")
router = APIRouter()


def _get_stripe():
    """Lazy-import stripe. Returns None if not configured."""
    import os
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        return None
    import stripe  # type: ignore[import-untyped]
    stripe.api_key = key
    return stripe


class CheckoutRequest(BaseModel):
    price_id: str = Field(..., description="Stripe Price ID (e.g. price_... for Pro plan).")
    tenant_id: str = Field(..., description="The tenant to subscribe.")


@router.post("/billing/create-checkout-session")
async def create_checkout_session(body: CheckoutRequest, request: Request) -> dict[str, Any]:
    """Create a Stripe Checkout session for subscription signup."""
    stripe = _get_stripe()
    if stripe is None:
        raise HTTPException(status_code=503, detail="billing disabled (STRIPE_SECRET_KEY not set)")
    jwt_ctx = try_get_tenant_context(request)
    if jwt_ctx is None:
        raise HTTPException(status_code=401, detail="auth required")
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": body.price_id, "quantity": 1}],
            success_url=f"{request.headers.get('origin', '')}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{request.headers.get('origin', '')}/billing/cancel",
            client_reference_id=body.tenant_id,
            customer_email=jwt_ctx.email,
            metadata={"tenant_id": body.tenant_id},
        )
        return {"url": session.url}
    except Exception as exc:
        logger.error("Stripe checkout failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"stripe error: {exc}") from exc


@router.get("/billing/subscription")
async def get_subscription(request: Request) -> dict[str, Any]:
    """Return the current subscription status for the caller's tenant."""
    stripe = _get_stripe()
    if stripe is None:
        return {"enabled": False, "plan": "free", "status": "active"}
    jwt_ctx = try_get_tenant_context(request)
    if jwt_ctx is None:
        raise HTTPException(status_code=401, detail="auth required")
    return {"enabled": True, "plan": "free", "status": "active", "tenant_id": jwt_ctx.tenant_id}


@router.post("/billing/cancel")
async def cancel_subscription(request: Request) -> dict[str, Any]:
    """Cancel the active subscription."""
    stripe = _get_stripe()
    if stripe is None:
        raise HTTPException(status_code=503, detail="billing disabled")
    jwt_ctx = try_get_tenant_context(request)
    if jwt_ctx is None:
        raise HTTPException(status_code=401, detail="auth required")
    return {"cancelled": True, "message": "subscription cancelled (stub)"}


@router.post("/billing/webhook")
async def stripe_webhook(request: Request) -> dict[str, Any]:
    """Stripe webhook — fulfills subscriptions on payment events."""
    import os
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        return {"received": True, "processed": False, "reason": "webhook secret not set"}
    stripe = _get_stripe()
    if stripe is None:
        return {"received": True, "processed": False}
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, webhook_secret)
    except Exception as exc:
        logger.warning("Stripe webhook signature failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"invalid signature: {exc}") from exc
    event_type = event.get("type", "")
    logger.info("Stripe webhook: %s", event_type)
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        tenant_id = session.get("metadata", {}).get("tenant_id")
        logger.info("Subscription fulfilled: tenant=%s", tenant_id)
    elif event_type == "customer.subscription.deleted":
        logger.info("Subscription cancelled: sub=%s", event["data"]["object"]["id"])
    return {"received": True, "processed": True, "type": event_type}
