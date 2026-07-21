import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)

_BATCH_SIZE = 5000

_DELETE_BATCH_SQL = text(
    """
    DELETE FROM trace_runs
    WHERE id IN (
        SELECT id FROM trace_runs WHERE started_at < :cutoff LIMIT :batch_size
    )
    """
)


async def prune_old_traces(session_maker: async_sessionmaker, retention_hours: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
    total_deleted = 0
    while True:
        async with session_maker() as session:
            result = await session.execute(_DELETE_BATCH_SQL, {"cutoff": cutoff, "batch_size": _BATCH_SIZE})
            await session.commit()
            deleted = result.rowcount or 0
            total_deleted += deleted
        if deleted < _BATCH_SIZE:
            break
    if total_deleted:
        logger.info("retention: pruned %d trace_runs older than %sh", total_deleted, retention_hours)
    return total_deleted


async def retention_loop(
    session_maker: async_sessionmaker, retention_hours: int, sweep_interval_seconds: int
) -> None:
    while True:
        try:
            await prune_old_traces(session_maker, retention_hours)
        except Exception:
            logger.exception("retention sweep failed")
        await asyncio.sleep(sweep_interval_seconds)
