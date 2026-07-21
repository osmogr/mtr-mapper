from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_admin
from app.db import get_db
from app.models.target import Target, TargetSource
from app.schemas.target import TargetCreate, TargetOut, TargetUpdate
from app.services.tree_service import tree_service

router = APIRouter(
    prefix="/api/admin/targets", tags=["admin:targets"], dependencies=[Depends(require_admin)]
)


def _source_labels(target: Target) -> list[str]:
    labels = []
    for s in target.sources:
        labels.append("manual" if s.source_type == "manual" else f"list:{s.target_list_id}")
    return labels


@router.get("", response_model=list[TargetOut])
async def list_targets(
    q: str | None = None,
    active: bool | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[TargetOut]:
    stmt = select(Target).options(selectinload(Target.sources)).order_by(Target.address)
    if active is not None:
        stmt = stmt.where(Target.active == active)
    if q:
        stmt = stmt.where(Target.address.ilike(f"%{q}%"))
    result = await db.execute(stmt)
    targets = result.scalars().all()
    return [
        TargetOut(
            id=t.id,
            address=t.address,
            display_name=t.display_name,
            active=t.active,
            last_probed_at=t.last_probed_at,
            last_probe_success=t.last_probe_success,
            sources=_source_labels(t),
        )
        for t in targets
    ]


@router.post("", response_model=TargetOut, status_code=201)
async def create_target(payload: TargetCreate, db: AsyncSession = Depends(get_db)) -> TargetOut:
    result = await db.execute(
        select(Target)
        .options(selectinload(Target.sources))
        .where(Target.address.ilike(payload.address))
    )
    target = result.scalar_one_or_none()
    if target is None:
        # Brand new row: it can't have any sources yet, so skip straight to adding one
        # rather than touching the (not-yet-loaded) `sources` relationship, which would
        # otherwise trigger an implicit lazy-load outside of an awaitable context.
        target = Target(address=payload.address, display_name=payload.display_name, active=True)
        db.add(target)
        await db.flush()
        db.add(TargetSource(target_id=target.id, source_type="manual"))
    else:
        target.active = True
        if payload.display_name:
            target.display_name = payload.display_name
        existing_manual = next((s for s in target.sources if s.source_type == "manual"), None)
        if existing_manual is None:
            db.add(TargetSource(target_id=target.id, source_type="manual"))

    await db.commit()
    await db.refresh(target, attribute_names=["sources"])
    tree_service.request_recompute()
    return TargetOut(
        id=target.id,
        address=target.address,
        display_name=target.display_name,
        active=target.active,
        last_probed_at=target.last_probed_at,
        last_probe_success=target.last_probe_success,
        sources=_source_labels(target),
    )


@router.patch("/{target_id}", response_model=TargetOut)
async def update_target(
    target_id: int, payload: TargetUpdate, db: AsyncSession = Depends(get_db)
) -> TargetOut:
    result = await db.execute(
        select(Target).options(selectinload(Target.sources)).where(Target.id == target_id)
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    if payload.active is not None:
        target.active = payload.active
    if payload.display_name is not None:
        target.display_name = payload.display_name
    await db.commit()
    tree_service.request_recompute()
    return TargetOut(
        id=target.id,
        address=target.address,
        display_name=target.display_name,
        active=target.active,
        last_probed_at=target.last_probed_at,
        last_probe_success=target.last_probe_success,
        sources=_source_labels(target),
    )


@router.delete("/{target_id}", status_code=204)
async def delete_target(target_id: int, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(
        select(Target).options(selectinload(Target.sources)).where(Target.id == target_id)
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")

    manual_source = next((s for s in target.sources if s.source_type == "manual"), None)
    if manual_source is not None:
        await db.delete(manual_source)
        await db.flush()

    remaining = await db.execute(select(TargetSource).where(TargetSource.target_id == target.id))
    if not remaining.scalars().all():
        target.active = False

    await db.commit()
    tree_service.request_recompute()
