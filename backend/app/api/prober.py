from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_prober_token
from app.db import get_db
from app.models.target import Target
from app.models.trace import TraceHop, TraceRun
from app.schemas.prober import ProberTarget, TraceResultSubmit
from app.services.tree_service import tree_service

router = APIRouter(
    prefix="/api/prober", tags=["prober"], dependencies=[Depends(require_prober_token)]
)


@router.get("/targets", response_model=list[ProberTarget])
async def get_prober_targets(db: AsyncSession = Depends(get_db)) -> list[ProberTarget]:
    result = await db.execute(select(Target).where(Target.active.is_(True)))
    return [ProberTarget(id=t.id, address=t.address) for t in result.scalars().all()]


@router.post("/results", status_code=204)
async def submit_result(payload: TraceResultSubmit, db: AsyncSession = Depends(get_db)) -> None:
    target_result = await db.execute(select(Target).where(Target.id == payload.target_id))
    target = target_result.scalar_one_or_none()
    if target is None or not target.active:
        # Target was deleted/deactivated after the prober picked it up for this cycle; drop silently.
        raise HTTPException(status_code=404, detail="target not found or inactive")

    run = TraceRun(
        target_id=target.id,
        started_at=payload.started_at,
        completed_at=payload.completed_at,
        success=payload.success,
        error_message=payload.error_message,
        raw_json=payload.raw_json,
    )
    db.add(run)
    await db.flush()

    for hop in payload.hops:
        db.add(
            TraceHop(
                trace_run_id=run.id,
                target_id=target.id,
                run_started_at=payload.started_at,
                hop_number=hop.hop_number,
                hop_ip=hop.hop_ip,
                hop_hostname=hop.hop_hostname,
                is_timeout=hop.is_timeout,
                sent=hop.sent,
                loss_pct=hop.loss_pct,
                last_ms=hop.last_ms,
                avg_ms=hop.avg_ms,
                best_ms=hop.best_ms,
                worst_ms=hop.worst_ms,
                stddev_ms=hop.stddev_ms,
            )
        )

    target.last_probed_at = datetime.now(timezone.utc)
    target.last_probe_success = payload.success
    await db.commit()

    tree_service.request_recompute()
