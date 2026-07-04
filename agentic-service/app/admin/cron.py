"""Scheduled demo-reset cron.

Phase 6c uses a simple ``asyncio.create_task`` + sleep loop instead of a
real scheduler. This is dev-friendly (no extra dependencies) and good
enough for the demo: every ``demo_reset_interval_seconds`` (default 24h)
we wipe + reseed the demo tenant's business data so visitors can't
permanently break it.

In production you should use a real scheduler (celery beat, kubernetes
cronjob, AWS EventBridge) — this background task is fine for the dev
demo but won't survive a multi-process deployment.

Contract::

    cron = DemoResetCron()
    await cron.start()    # call from FastAPI lifespan startup
    ...
    await cron.stop()     # call from FastAPI lifespan shutdown
"""

from __future__ import annotations

import asyncio
import logging

from app.admin.demo_reset import reset_demo_data
from app.config import get_settings

logger = logging.getLogger("opspilot.admin.cron")


class DemoResetCron:
    """Background task that reseeds the demo tenant every N seconds."""

    def __init__(self, interval_seconds: int | None = None) -> None:
        settings = get_settings()
        self._interval = interval_seconds or settings.demo_reset_interval_seconds
        self._enabled = settings.demo_reset_enabled
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the cron loop. Idempotent — calling twice is a no-op."""
        if not self._enabled:
            logger.info("Demo reset cron disabled by config — not starting.")
            return
        if self._task is not None and not self._task.done():
            logger.warning("DemoResetCron.start() called twice — ignoring.")
            return
        self._task = asyncio.create_task(self._run(), name="demo-reset-cron")
        logger.info("Demo reset cron started — interval=%ss", self._interval)

    async def stop(self) -> None:
        """Cancel the cron loop. Safe to call multiple times."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Demo reset cron stopped.")

    async def _run(self) -> None:
        """Sleep → reset → repeat. Logs every cycle."""
        # Run one cycle immediately on startup so a fresh dev.db has data.
        try:
            await self._cycle()
        except Exception as exc:  # noqa: BLE001 — cron must not die
            logger.exception("Demo reset cycle failed: %s", exc)

        while True:
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                logger.info("Demo reset cron cancelled — exiting loop.")
                return
            try:
                await self._cycle()
            except Exception as exc:  # noqa: BLE001 — cron must not die
                logger.exception("Demo reset cycle failed: %s", exc)

    async def _cycle(self) -> None:
        """Run one reset cycle + log."""
        logger.info("Demo reset cron: starting cycle")
        result = await reset_demo_data()
        logger.info("Demo reset cron: cycle done — %s", result)
