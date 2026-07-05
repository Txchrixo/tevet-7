"""Automated SQLite DB backup cron (#30).

Creates a timestamped copy of dev.db every 24h. Keeps the last 7 backups.
"""
import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("tevet7.backup_cron")

class DbBackupCron:
    def __init__(self, db_path: str = "dev.db", backup_dir: str = "backups", interval_s: int = 86400, max_backups: int = 7):
        self._db_path = db_path
        self._backup_dir = Path(backup_dir)
        self._interval = interval_s
        self._max_backups = max_backups
        self._task = None

    async def start(self):
        self._backup_dir.mkdir(exist_ok=True)
        self._task = asyncio.create_task(self._run_loop())
        logger.info("DB backup cron started - interval=%ds max_backups=%d", self._interval, self._max_backups)

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DB backup cron stopped.")

    async def _run_loop(self):
        # Run once immediately, then on interval
        await self._backup()
        while True:
            await asyncio.sleep(self._interval)
            await self._backup()

    async def _backup(self):
        try:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            dest = self._backup_dir / f"dev_{ts}.db"
            shutil.copy2(self._db_path, dest)
            logger.info("DB backup created: %s (%d bytes)", dest.name, dest.stat().st_size)
            # Prune old backups
            backups = sorted(self._backup_dir.glob("dev_*.db"))
            if len(backups) > self._max_backups:
                for old in backups[:-self._max_backups]:
                    old.unlink()
                    logger.info("Old backup pruned: %s", old.name)
        except Exception as e:
            logger.error("DB backup failed: %s", e)
