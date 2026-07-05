"""Admin package - tenant admin + platform owner surfaces.

Exposes:
  - ``admin_router`` - FastAPI router mounted at ``/api/admin`` by main.py.
  - ``service``       - business logic (pure-async, no FastAPI deps).
  - ``demo_reset``    - reseed the demo tenant's business data.
  - ``cron``          - ``DemoResetCron`` background task.
"""

from __future__ import annotations

from app.admin.routes import router as admin_router
from app.admin.cron import DemoResetCron

__all__ = ["admin_router", "DemoResetCron"]
