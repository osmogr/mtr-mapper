import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.target import Target, TargetSource
from app.models.target_list import TargetList

logger = logging.getLogger(__name__)


def _parse_target_list_body(body: str) -> list[str]:
    addresses = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        addresses.append(line)
    return addresses


async def _get_or_create_target(session: AsyncSession, address: str) -> Target:
    result = await session.execute(select(Target).where(Target.address.ilike(address)))
    target = result.scalar_one_or_none()
    if target is None:
        target = Target(address=address, active=True)
        session.add(target)
        await session.flush()
    elif not target.active:
        target.active = True
    return target


async def _deactivate_if_orphaned(session: AsyncSession, target: Target) -> None:
    result = await session.execute(select(TargetSource).where(TargetSource.target_id == target.id))
    remaining = result.scalars().all()
    if not remaining:
        target.active = False


async def sync_target_list(session: AsyncSession, target_list: TargetList) -> None:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(target_list.url)
            resp.raise_for_status()
            addresses = _parse_target_list_body(resp.text)
    except Exception as exc:
        target_list.last_fetched_at = datetime.now(timezone.utc)
        target_list.last_fetch_status = "error"
        target_list.last_fetch_error = str(exc)[:2000]
        await session.commit()
        logger.warning("target list %s fetch failed: %s", target_list.id, exc)
        return

    seen_addresses = {a.lower() for a in addresses}

    # Ensure a Target + 'list' source row exists for every address currently in the list.
    for address in addresses:
        target = await _get_or_create_target(session, address)
        existing_source = await session.execute(
            select(TargetSource).where(
                TargetSource.target_id == target.id,
                TargetSource.source_type == "list",
                TargetSource.target_list_id == target_list.id,
            )
        )
        if existing_source.scalar_one_or_none() is None:
            session.add(
                TargetSource(target_id=target.id, source_type="list", target_list_id=target_list.id)
            )

    # Remove 'list' source rows for addresses no longer present in the fetched list.
    prior_sources_result = await session.execute(
        select(TargetSource).where(TargetSource.target_list_id == target_list.id)
    )
    prior_sources = prior_sources_result.scalars().all()
    for source in prior_sources:
        target_result = await session.execute(select(Target).where(Target.id == source.target_id))
        target = target_result.scalar_one()
        if target.address.lower() not in seen_addresses:
            await session.delete(source)
            await session.flush()
            await _deactivate_if_orphaned(session, target)

    target_list.last_fetched_at = datetime.now(timezone.utc)
    target_list.last_fetch_status = "ok"
    target_list.last_fetch_error = None
    target_list.last_fetch_target_count = len(addresses)
    await session.commit()


async def sync_due_target_lists(session_maker: async_sessionmaker) -> None:
    async with session_maker() as session:
        result = await session.execute(select(TargetList).where(TargetList.active.is_(True)))
        lists = result.scalars().all()
        now = datetime.now(timezone.utc)
        due = [
            tl
            for tl in lists
            if tl.last_fetched_at is None
            or (now - tl.last_fetched_at).total_seconds() >= tl.fetch_interval_seconds
        ]
    for tl in due:
        async with session_maker() as session:
            tl_result = await session.execute(select(TargetList).where(TargetList.id == tl.id))
            fresh = tl_result.scalar_one_or_none()
            if fresh is not None:
                await sync_target_list(session, fresh)


async def sync_loop(session_maker: async_sessionmaker, check_interval_seconds: int = 30) -> None:
    while True:
        try:
            await sync_due_target_lists(session_maker)
        except Exception:
            logger.exception("target list sync loop iteration failed")
        await asyncio.sleep(check_interval_seconds)
