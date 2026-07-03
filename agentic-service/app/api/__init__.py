"""API routers package.

Currently exposes:

- ``chat`` — the ``POST /chat`` endpoint (Phase 0: returns HTTP 501).

Planned routers (not in Phase 0):

- ``admin`` — tenant onboarding, quota dashboards, audit log viewer.
- ``onboarding`` — Phase 5 self-serve tenant onboarding.
- ``webhooks`` — inbound webhooks from tenant systems (e.g. DP order events).
- ``evals`` — Phase 7 eval harness endpoints.
"""

from app.api.chat import router

__all__ = ["router"]
