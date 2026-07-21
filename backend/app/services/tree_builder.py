"""Server-side merged-tree construction.

Builds a trie keyed by (parent_node_id, hop_label) from each active target's
most recent trace. Node identity is (parent, label) rather than (depth,
label) globally, which is what makes two edge cases behave correctly without
special-casing:

- Simultaneous timeouts ("*") at the same hop depth for different targets
  only merge if the targets' paths were *already identical* up to that hop
  (same parent node) -- targets that diverged earlier never spuriously
  re-merge just because they both show a timeout.
- The same IP recurring at different depths for different targets (e.g.
  asymmetric routing) can't be mis-merged, since a node has exactly one
  parent/depth by construction.

This is a tree, not a DAG: once two targets' paths diverge they never
re-converge into a shared node again even if a later hop happens to match.
That's an accepted simplification -- real-world path reconvergence after
divergence is rare and not worth the added complexity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.target import Target
from app.models.trace import TraceHop, TraceRun
from app.schemas.tree import NodeStats, Severity, TreeNode

ROOT_LABEL = "__root__"
ROOT_ID = hashlib.sha1(f"|{ROOT_LABEL}".encode()).hexdigest()

_SEVERITY_ORDER: list[Severity] = ["unknown", "ok", "warn", "critical"]
_SEVERITY_RANK = {s: i for i, s in enumerate(_SEVERITY_ORDER)}


def _node_id(parent_id: str | None, label: str) -> str:
    h = hashlib.sha1()
    h.update((parent_id or "").encode())
    h.update(b"|")
    h.update(label.encode())
    return h.hexdigest()


def _lookup_asn(
    ip: str | None, asn_map: dict[str, tuple[int | None, str | None]]
) -> tuple[int | None, str | None]:
    return asn_map.get(ip, (None, None)) if ip else (None, None)


@dataclass
class HopRecord:
    hop_number: int
    hop_ip: str | None
    hop_hostname: str | None
    is_timeout: bool
    sent: int | None
    loss_pct: float | None
    last_ms: float | None
    avg_ms: float | None
    best_ms: float | None
    worst_ms: float | None
    stddev_ms: float | None

    def stat_dict(self) -> dict:
        return {
            "sent": self.sent,
            "loss_pct": self.loss_pct,
            "avg_ms": self.avg_ms,
            "best_ms": self.best_ms,
            "worst_ms": self.worst_ms,
            "stddev_ms": self.stddev_ms,
        }


@dataclass
class TargetTraceData:
    target_id: int
    address: str
    hops: list[HopRecord]


@dataclass
class _BuildNode:
    id: str
    parent_id: str | None
    depth: int
    hop_ip: str | None
    hop_hostname: str | None
    is_timeout_node: bool
    asn: int | None = None
    as_org: str | None = None
    is_leaf_target: bool = False
    target_ids: list[int] = field(default_factory=list)
    children: dict[str, "_BuildNode"] = field(default_factory=dict)
    contributions: list[dict] = field(default_factory=list)
    own_stats: NodeStats = field(default_factory=NodeStats)
    severity: Severity = "unknown"
    worst_descendant_severity: Severity = "unknown"


def _severity_for_loss(loss_pct: float | None, settings: Settings) -> Severity:
    if loss_pct is None:
        return "unknown"
    if loss_pct >= settings.loss_critical_threshold:
        return "critical"
    if loss_pct >= settings.loss_warn_threshold:
        return "warn"
    return "ok"


def _aggregate_stats(contributions: list[dict]) -> NodeStats:
    if not contributions:
        return NodeStats(sample_count=0)
    loss_vals = [c["loss_pct"] for c in contributions if c.get("loss_pct") is not None]
    avg_vals = [c["avg_ms"] for c in contributions if c.get("avg_ms") is not None]
    best_vals = [c["best_ms"] for c in contributions if c.get("best_ms") is not None]
    worst_vals = [c["worst_ms"] for c in contributions if c.get("worst_ms") is not None]
    stddev_vals = [c["stddev_ms"] for c in contributions if c.get("stddev_ms") is not None]
    sent_vals = [c["sent"] for c in contributions if c.get("sent") is not None]
    return NodeStats(
        loss_pct=max(loss_vals) if loss_vals else None,
        avg_ms=sum(avg_vals) / len(avg_vals) if avg_vals else None,
        best_ms=min(best_vals) if best_vals else None,
        worst_ms=max(worst_vals) if worst_vals else None,
        stddev_ms=sum(stddev_vals) / len(stddev_vals) if stddev_vals else None,
        sample_count=sum(sent_vals) if sent_vals else len(contributions),
    )


def _finalize(node: _BuildNode, settings: Settings) -> Severity:
    node.own_stats = _aggregate_stats(node.contributions)
    node.severity = _severity_for_loss(node.own_stats.loss_pct, settings)

    worst_rank = _SEVERITY_RANK[node.severity]
    for child in node.children.values():
        child_worst = _finalize(child, settings)
        worst_rank = max(worst_rank, _SEVERITY_RANK[child_worst])
    node.worst_descendant_severity = _SEVERITY_ORDER[worst_rank]
    return node.worst_descendant_severity


def _to_tree_node(node: _BuildNode) -> TreeNode:
    return TreeNode(
        id=node.id,
        parent_id=node.parent_id,
        depth=node.depth,
        hop_ip=node.hop_ip,
        hop_hostname=node.hop_hostname,
        asn=node.asn,
        as_org=node.as_org,
        is_timeout_node=node.is_timeout_node,
        is_leaf_target=node.is_leaf_target,
        target_ids=node.target_ids,
        own_stats=node.own_stats,
        severity=node.severity,
        worst_descendant_severity=node.worst_descendant_severity,
        children=[c.id for c in node.children.values()],
    )


def build_tree(
    target_traces: list[TargetTraceData],
    settings: Settings,
    asn_map: dict[str, tuple[int | None, str | None]] | None = None,
) -> dict[str, TreeNode]:
    asn_map = asn_map or {}
    root = _BuildNode(
        id=ROOT_ID,
        parent_id=None,
        depth=0,
        hop_ip=None,
        hop_hostname=None,
        is_timeout_node=False,
    )
    all_nodes: dict[str, _BuildNode] = {root.id: root}

    for trace in target_traces:
        current = root
        for hop in trace.hops:
            is_timeout = hop.is_timeout or not hop.hop_ip
            label = "*" if is_timeout else hop.hop_ip
            child = current.children.get(label)
            if child is None:
                asn, as_org = _lookup_asn(None if is_timeout else hop.hop_ip, asn_map)
                child = _BuildNode(
                    id=_node_id(current.id, label),
                    parent_id=current.id,
                    depth=current.depth + 1,
                    hop_ip=None if is_timeout else hop.hop_ip,
                    hop_hostname=None if is_timeout else hop.hop_hostname,
                    asn=asn,
                    as_org=as_org,
                    is_timeout_node=is_timeout,
                )
                current.children[label] = child
                all_nodes[child.id] = child
            elif hop.hop_hostname and not child.hop_hostname:
                child.hop_hostname = hop.hop_hostname
            child.contributions.append(hop.stat_dict())
            current = child

        leaf_label = f"target:{trace.target_id}"
        last_hop = trace.hops[-1] if trace.hops else None
        leaf_asn, leaf_as_org = _lookup_asn(
            last_hop.hop_ip if last_hop and not last_hop.is_timeout else None, asn_map
        )
        leaf = _BuildNode(
            id=_node_id(current.id, leaf_label),
            parent_id=current.id,
            depth=current.depth + 1,
            hop_ip=last_hop.hop_ip if last_hop and not last_hop.is_timeout else None,
            hop_hostname=last_hop.hop_hostname if last_hop else None,
            asn=leaf_asn,
            as_org=leaf_as_org,
            is_timeout_node=False,
            is_leaf_target=True,
            target_ids=[trace.target_id],
        )
        if last_hop:
            leaf.contributions.append(last_hop.stat_dict())
        current.children[leaf_label] = leaf
        all_nodes[leaf.id] = leaf

    _finalize(root, settings)

    return {node_id: _to_tree_node(node) for node_id, node in all_nodes.items()}


async def load_target_traces(session: AsyncSession) -> list[TargetTraceData]:
    """Load each active target's most recent completed trace run + hops."""
    targets_result = await session.execute(select(Target).where(Target.active.is_(True)))
    targets = targets_result.scalars().all()
    if not targets:
        return []

    traces: list[TargetTraceData] = []
    for target in targets:
        latest_run_result = await session.execute(
            select(TraceRun)
            .where(TraceRun.target_id == target.id)
            .order_by(TraceRun.started_at.desc())
            .limit(1)
        )
        latest_run = latest_run_result.scalar_one_or_none()

        hops: list[HopRecord] = []
        if latest_run is not None:
            hops_result = await session.execute(
                select(TraceHop)
                .where(TraceHop.trace_run_id == latest_run.id)
                .order_by(TraceHop.hop_number.asc())
            )
            hops = [
                HopRecord(
                    hop_number=h.hop_number,
                    hop_ip=str(h.hop_ip) if h.hop_ip is not None else None,
                    hop_hostname=h.hop_hostname,
                    is_timeout=h.is_timeout,
                    sent=h.sent,
                    loss_pct=float(h.loss_pct) if h.loss_pct is not None else None,
                    last_ms=float(h.last_ms) if h.last_ms is not None else None,
                    avg_ms=float(h.avg_ms) if h.avg_ms is not None else None,
                    best_ms=float(h.best_ms) if h.best_ms is not None else None,
                    worst_ms=float(h.worst_ms) if h.worst_ms is not None else None,
                    stddev_ms=float(h.stddev_ms) if h.stddev_ms is not None else None,
                )
                for h in hops_result.scalars().all()
            ]

        traces.append(TargetTraceData(target_id=target.id, address=target.address, hops=hops))

    return traces
