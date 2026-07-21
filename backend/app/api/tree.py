from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.target import Target
from app.models.trace import TraceHop
from app.schemas.target import HopHistoryPoint, TargetHistory, TargetOut
from app.schemas.tree import NodeDetail, NodeHistory, NodeHistoryPoint, TreeSnapshotMessage
from app.services import tree_builder
from app.services.dns_cache import resolve_hostname
from app.services.tree_service import tree_service

router = APIRouter(prefix="/api", tags=["public"])


def _source_labels(target: Target) -> list[str]:
    return [
        "manual" if s.source_type == "manual" else f"list:{s.target_list_id}" for s in target.sources
    ]


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/tree", response_model=TreeSnapshotMessage)
async def get_tree() -> TreeSnapshotMessage:
    return await tree_service.snapshot_message()


@router.get("/targets", response_model=list[TargetOut])
async def list_targets_public(
    active: bool | None = None, db: AsyncSession = Depends(get_db)
) -> list[TargetOut]:
    """Lightweight public listing (id/address/display_name/status only) so the
    frontend can label tree leaves with the name an admin actually typed in
    (rather than just the resolved terminal-hop IP) and support search-by-name.
    """
    stmt = select(Target).options(selectinload(Target.sources)).order_by(Target.address)
    if active is not None:
        stmt = stmt.where(Target.active == active)
    result = await db.execute(stmt)
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
        for t in result.scalars().all()
    ]


@router.get("/prober/stats")
async def prober_stats(db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Target).where(Target.active.is_(True)))
    targets = result.scalars().all()
    now = datetime.now(timezone.utc)
    deltas = [
        (now - t.last_probed_at).total_seconds() for t in targets if t.last_probed_at is not None
    ]
    achieved_avg = None
    if len(deltas) >= 2:
        # Approximate achieved cycle time as 2x the average time-since-last-probe
        # across the fleet (a target is on average halfway through its cycle).
        achieved_avg = 2 * (sum(deltas) / len(deltas))
    return {
        "active_target_count": len(targets),
        "probed_at_least_once": len(deltas),
        "achieved_avg_cycle_seconds": achieved_avg,
    }


@router.get("/targets/{target_id}", response_model=TargetOut)
async def get_target(target_id: int, db: AsyncSession = Depends(get_db)) -> TargetOut:
    result = await db.execute(
        select(Target).options(selectinload(Target.sources)).where(Target.id == target_id)
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    return TargetOut(
        id=target.id,
        address=target.address,
        display_name=target.display_name,
        active=target.active,
        last_probed_at=target.last_probed_at,
        last_probe_success=target.last_probe_success,
        sources=_source_labels(target),
    )


@router.get("/targets/{target_id}/history", response_model=TargetHistory)
async def get_target_history(
    target_id: int, hours: int = 24, db: AsyncSession = Depends(get_db)
) -> TargetHistory:
    target_result = await db.execute(select(Target).where(Target.id == target_id))
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    hops_result = await db.execute(
        select(TraceHop)
        .where(TraceHop.target_id == target_id, TraceHop.run_started_at >= cutoff)
        .order_by(TraceHop.run_started_at.asc())
    )
    by_run: dict = defaultdict(list)
    for h in hops_result.scalars().all():
        by_run[h.run_started_at].append(h)

    points = []
    for started_at, run_hops in sorted(by_run.items()):
        last = max(run_hops, key=lambda h: h.hop_number)
        points.append(
            HopHistoryPoint(
                run_started_at=started_at,
                hop_number=last.hop_number,
                hop_ip=str(last.hop_ip) if last.hop_ip is not None else None,
                hop_hostname=last.hop_hostname,
                is_timeout=last.is_timeout,
                loss_pct=float(last.loss_pct) if last.loss_pct is not None else None,
                avg_ms=float(last.avg_ms) if last.avg_ms is not None else None,
                best_ms=float(last.best_ms) if last.best_ms is not None else None,
                worst_ms=float(last.worst_ms) if last.worst_ms is not None else None,
                stddev_ms=float(last.stddev_ms) if last.stddev_ms is not None else None,
            )
        )
    return TargetHistory(target_id=target.id, address=target.address, points=points)


@router.get("/nodes/{node_id}", response_model=NodeDetail)
async def get_node(node_id: str) -> NodeDetail:
    node = await tree_service.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    resolved = None
    if node.hop_ip:
        resolved = node.hop_hostname or await resolve_hostname(node.hop_ip)
    return NodeDetail(node=node, resolved_hostname=resolved)


@router.get("/nodes/{node_id}/history", response_model=NodeHistory)
async def get_node_history(
    node_id: str, hours: int = 24, db: AsyncSession = Depends(get_db)
) -> NodeHistory:
    node = await tree_service.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    if node.is_leaf_target and node.target_ids:
        hops_result = await db.execute(
            select(TraceHop)
            .where(TraceHop.target_id == node.target_ids[0], TraceHop.run_started_at >= cutoff)
            .order_by(TraceHop.run_started_at.asc())
        )
        by_run: dict = defaultdict(list)
        for h in hops_result.scalars().all():
            by_run[h.run_started_at].append(h)
        points = []
        for started_at, run_hops in sorted(by_run.items()):
            last = max(run_hops, key=lambda h: h.hop_number)
            points.append(
                NodeHistoryPoint(
                    run_started_at=started_at.isoformat(),
                    loss_pct=float(last.loss_pct) if last.loss_pct is not None else None,
                    avg_ms=float(last.avg_ms) if last.avg_ms is not None else None,
                    best_ms=float(last.best_ms) if last.best_ms is not None else None,
                    worst_ms=float(last.worst_ms) if last.worst_ms is not None else None,
                    stddev_ms=float(last.stddev_ms) if last.stddev_ms is not None else None,
                    sample_count=last.sent or 0,
                )
            )
        return NodeHistory(node_id=node_id, points=points)

    if not node.hop_ip:
        return NodeHistory(node_id=node_id, points=[])

    # Trunk/shared-hop node: approximate its history as all recorded hops (across
    # any target) at that IP within the window, aggregated per timestamp. This is
    # a reasonable approximation of "this shared hop's health over time" even
    # though strict trie membership is (parent, label), not IP alone.
    hops_result = await db.execute(
        select(TraceHop)
        .where(TraceHop.hop_ip == cast(node.hop_ip, INET), TraceHop.run_started_at >= cutoff)
        .order_by(TraceHop.run_started_at.asc())
    )
    by_time: dict = defaultdict(list)
    for h in hops_result.scalars().all():
        by_time[h.run_started_at].append(h)

    points = []
    for started_at, hops in sorted(by_time.items()):
        stats = tree_builder._aggregate_stats(  # noqa: SLF001 - internal reuse within the app
            [
                {
                    "loss_pct": float(h.loss_pct) if h.loss_pct is not None else None,
                    "avg_ms": float(h.avg_ms) if h.avg_ms is not None else None,
                    "best_ms": float(h.best_ms) if h.best_ms is not None else None,
                    "worst_ms": float(h.worst_ms) if h.worst_ms is not None else None,
                    "stddev_ms": float(h.stddev_ms) if h.stddev_ms is not None else None,
                    "sent": h.sent,
                }
                for h in hops
            ]
        )
        points.append(
            NodeHistoryPoint(
                run_started_at=started_at.isoformat(),
                loss_pct=stats.loss_pct,
                avg_ms=stats.avg_ms,
                best_ms=stats.best_ms,
                worst_ms=stats.worst_ms,
                stddev_ms=stats.stddev_ms,
                sample_count=stats.sample_count,
            )
        )
    return NodeHistory(node_id=node_id, points=points)
