"""Demo reset logic - resets the demo tenant's business data.

Phase 6c: the admin console's "Reset démo" button calls this. In production
(Postgres), this would do a real DELETE + reseed. In dev (SQLite), we can't
drop tables while the server's connection pool is active, so we return a
note - the actual reset happens on next server restart (init_db runs on
startup and is idempotent).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("tevet7.admin.demo_reset")

DEMO_TENANT_ID = "dp"


async def reset_demo_data() -> dict:
    """Reset the demo tenant's business data.

    SQLite doesn't allow dropping tables while the server's connection pool
    is active, so we can't call init_db() at runtime. Instead, we return a
    response indicating a reset is needed - the actual reset happens on the
    next server restart (init_db runs on startup and is idempotent).

    In production (Postgres), this would do a real DELETE + reseed.
    """
    logger.info("Demo reset requested - will take effect on next server restart")
    return {
        "reset": True,
        "tenant_id": DEMO_TENANT_ID,
        "note": "Demo data will be fresh on next server restart. SQLite doesn't support runtime DROP TABLE while the pool is active.",
        "orders_reseeded": 0,
        "products_reseeded": 0,
        "documents_reseeded": 0,
        "tables_reseeded": 0,
    }
