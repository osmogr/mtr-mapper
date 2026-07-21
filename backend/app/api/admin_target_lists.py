from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.config import get_settings
from app.db import get_db
from app.models.target import Target, TargetSource
from app.models.target_list import TargetList
from app.schemas.target_list import TargetListCreate, TargetListOut, TargetListUpdate
from app.services.target_list_sync import sync_target_list
from app.services.tree_service import tree_service

router = APIRouter(
    prefix="/api/admin/target-lists", tags=["admin:target-lists"], dependencies=[Depends(require_admin)]
)


@router.get("", response_model=list[TargetListOut])
async def list_target_lists(db: AsyncSession = Depends(get_db)) -> list[TargetListOut]:
    result = await db.execute(select(TargetList).order_by(TargetList.name))
    return list(result.scalars().all())


@router.post("", response_model=TargetListOut, status_code=201)
async def create_target_list(payload: TargetListCreate, db: AsyncSession = Depends(get_db)) -> TargetListOut:
    settings = get_settings()
    target_list = TargetList(
        name=payload.name,
        url=payload.url,
        fetch_interval_seconds=payload.fetch_interval_seconds
        or settings.target_list_default_fetch_interval_seconds,
        active=True,
    )
    db.add(target_list)
    await db.commit()
    await db.refresh(target_list)
    # Do the first fetch inline so admins get immediate feedback instead of waiting for the next sweep.
    await sync_target_list(db, target_list)
    tree_service.request_recompute()
    return target_list


@router.patch("/{list_id}", response_model=TargetListOut)
async def update_target_list(
    list_id: int, payload: TargetListUpdate, db: AsyncSession = Depends(get_db)
) -> TargetListOut:
    result = await db.execute(select(TargetList).where(TargetList.id == list_id))
    target_list = result.scalar_one_or_none()
    if target_list is None:
        raise HTTPException(status_code=404, detail="target list not found")
    if payload.name is not None:
        target_list.name = payload.name
    if payload.url is not None:
        target_list.url = payload.url
    if payload.fetch_interval_seconds is not None:
        target_list.fetch_interval_seconds = payload.fetch_interval_seconds
    if payload.active is not None:
        target_list.active = payload.active
    await db.commit()
    await db.refresh(target_list)
    return target_list


async def _deactivate_orphans_for_list(db: AsyncSession, list_id: int) -> None:
    sources_result = await db.execute(select(TargetSource).where(TargetSource.target_list_id == list_id))
    sources = sources_result.scalars().all()
    target_ids = {s.target_id for s in sources}
    for source in sources:
        await db.delete(source)
    await db.flush()
    for target_id in target_ids:
        remaining = await db.execute(select(TargetSource).where(TargetSource.target_id == target_id))
        if not remaining.scalars().all():
            target_result = await db.execute(select(Target).where(Target.id == target_id))
            target = target_result.scalar_one_or_none()
            if target is not None:
                target.active = False


@router.delete("/{list_id}", status_code=204)
async def delete_target_list(list_id: int, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(select(TargetList).where(TargetList.id == list_id))
    target_list = result.scalar_one_or_none()
    if target_list is None:
        raise HTTPException(status_code=404, detail="target list not found")
    await _deactivate_orphans_for_list(db, list_id)
    await db.delete(target_list)
    await db.commit()
    tree_service.request_recompute()


@router.post("/{list_id}/sync-now", response_model=TargetListOut)
async def sync_now(list_id: int, db: AsyncSession = Depends(get_db)) -> TargetListOut:
    result = await db.execute(select(TargetList).where(TargetList.id == list_id))
    target_list = result.scalar_one_or_none()
    if target_list is None:
        raise HTTPException(status_code=404, detail="target list not found")
    await sync_target_list(db, target_list)
    await db.refresh(target_list)
    tree_service.request_recompute()
    return target_list
