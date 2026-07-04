"""API routers package.

Currently exposes:

- ``chat`` — the ``POST /chat`` endpoint (Phase 1: rule-based agent on
  SQLite), the ``GET /schema`` endpoint, and (Phase 2 / Task 18) the
  ``GET /traces`` + ``GET /traces/{trace_id}`` observability endpoints.
- ``documents`` — Phase 3 documentary RAG management endpoints:
  ``POST /documents``, ``GET /documents``, ``GET /documents/{id}``,
  ``DELETE /documents/{id}``.

Planned routers (not yet implemented):

- ``admin`` — tenant onboarding, quota dashboards, audit log viewer.
- ``onboarding`` — Phase 5 self-serve tenant onboarding.
- ``webhooks`` — inbound webhooks from tenant systems (e.g. DP order events).
- ``evals`` — Phase 7 eval harness endpoints.
"""

from app.api.chat import router as chat_router
from app.api.documents import router as documents_router

router = chat_router
__all__ = ["chat_router", "documents_router", "router"]

