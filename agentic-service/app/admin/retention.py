"""Data retention policy (#43).

Deletes conversations + messages older than N days. Default: 90 days.
Runs as a daily cron alongside the backup cron.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import delete, select
from app.db_seed import get_engine, conversations, messages, traces_table as traces

logger = logging.getLogger("tevet7.retention")

class DataRetentionCron:
    def __init__(self, retention_days: int = 90, interval_s: int = 86400):
        self._retention_days = retention_days
        self._interval = interval_s
        self._task = None

    async def start(self):
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Data retention cron started - retention=%d days", self._retention_days)

    async def stop(self):
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
        logger.info("Data retention cron stopped.")

    async def _run_loop(self):
        await self._cleanup()
        while True:
            await asyncio.sleep(self._interval)
            await self._cleanup()

    async def _cleanup(self):
        try:
            cutoff = datetime.utcnow() - timedelta(days=self._retention_days)
            engine = get_engine()
            async with engine.begin() as conn:
                # Delete old messages
                old_msgs = await conn.execute(
                    delete(messages).where(messages.c.created_at < cutoff)
                )
                # Delete old conversations (cascade not automatic in SQLite)
                old_convs = await conn.execute(
                    delete(conversations).where(
                        conversations.c.updated_at < cutoff,
                        ~conversations.c.id.in_(
                            select(messages.c.conversation_id).distinct()
                        )
                    )
                )
                # Delete old traces
                old_traces = await conn.execute(
                    delete(traces).where(traces.c.created_at < cutoff)
                )
                total = (old_msgs.rowcount or 0) + (old_convs.rowcount or 0) + (old_traces.rowcount or 0)
                if total > 0:
                    logger.info("Data retention: deleted %d old records (cutoff=%s)", total, cutoff.isoformat())
        except Exception as e:
            logger.error("Data retention cleanup failed: %s", e)
