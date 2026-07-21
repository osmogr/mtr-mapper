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

One exception to "positional identity": an mtr hop that got zero replies
across an entire run (`is_timeout`) is common noise from routers that
deprioritize ICMP TTL-exceeded replies under load, not necessarily a real
routing change -- so it does NOT always get its own "*" node, and a
dropped hop also makes every later raw hop-number in that one trace
unreliable relative to a trace that got a reply at that position (a
timeout could be swallowing more than one physical hop). `build_tree` seeds
the trie with every trace's real leading hop chain first, then, when a
trace hits a timeout (or run of them), searches the *entire* already-known
real subtree hanging off the last confirmed position for a node whose
label matches the next hop this trace did get a reply from (see
`_find_unambiguous_real_descendant`) -- not just its direct children. If
exactly one such node exists, the timeout(s) are skipped entirely and the
trace rejoins the known real path there, rather than forking a duplicate
subtree. Only when no unambiguous match exists does a timeout get its own
"*" node, same as before -- so this still can't reconverge genuinely
diverged paths, it only resolves positional uncertainty within a path
that's already shared.
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


def _find_unambiguous_real_descendant(node: "_BuildNode", label: str) -> "_BuildNode | None":
    """Search every already-known real (non-timeout) descendant of `node`
    for the one whose label matches, without trusting how many hops away it
    actually is -- a hop timing out doesn't just hide its own identity, it
    also makes every subsequent raw hop-number in that one trace off by an
    unknowable amount relative to a trace that got a reply at that same
    position. Scoped to `node`'s own subtree (never searches siblings or
    unrelated branches), so this can't reconverge genuinely diverged paths
    -- it only corrects for positional uncertainty on what's otherwise
    already an established shared trunk. Timeout nodes and their descendants
    are excluded from the search (bridging shouldn't chain through another
    trace's own unresolved timeout). Returns None -- no bridge -- unless
    exactly one descendant matches, so a coincidental same-label repeat
    elsewhere in the subtree safely falls back to the old behavior instead
    of risking a wrong merge.
    """
    matches: list[_BuildNode] = []

    def visit(n: "_BuildNode") -> None:
        for child in n.children.values():
            if child.is_timeout_node:
                continue
            if (child.hop_hostname or child.hop_ip) == label:
                matches.append(child)
            visit(child)

    visit(node)
    return matches[0] if len(matches) == 1 else None


def _get_or_create_real_child(
    parent: "_BuildNode",
    hop_ip: str,
    hostname_map: dict[str, str | None],
    asn_map: dict[str, tuple[int | None, str | None]],
    all_nodes: dict[str, "_BuildNode"],
) -> "_BuildNode":
    hostname = hostname_map.get(hop_ip)
    label = hostname or hop_ip
    child = parent.children.get(label)
    if child is None:
        asn, as_org = _lookup_asn(hop_ip, asn_map)
        child = _BuildNode(
            id=_node_id(parent.id, label),
            parent_id=parent.id,
            depth=parent.depth + 1,
            hop_ip=hop_ip,
            hop_ips=[hop_ip],
            hop_hostname=hostname,
            asn=asn,
            as_org=as_org,
            is_timeout_node=False,
        )
        parent.children[label] = child
        all_nodes[child.id] = child
    elif hop_ip not in child.hop_ips:
        child.hop_ips.append(hop_ip)
    return child


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
    hop_ips: list[str] = field(default_factory=list)
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
        hop_ips=node.hop_ips,
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
    hostname_map: dict[str, str | None] | None = None,
) -> dict[str, TreeNode]:
    asn_map = asn_map or {}
    hostname_map = hostname_map or {}
    root = _BuildNode(
        id=ROOT_ID,
        parent_id=None,
        depth=0,
        hop_ip=None,
        hop_hostname=None,
        is_timeout_node=False,
    )
    all_nodes: dict[str, _BuildNode] = {root.id: root}

    # First pass: seed the trie with every trace's leading run of real
    # (non-timeout) hops, stopping at that trace's first timeout. Real-hop
    # merging (by parent+label) is already order-independent on its own, so
    # this pass' only purpose is making sure a responding hop's canonical
    # node exists *before* the second pass below runs -- otherwise whichever
    # trace happens to iterate first would decide, arbitrarily, whether a
    # later trace's isolated timeout can rejoin the real path it belongs to.
    for trace in target_traces:
        current = root
        for hop in trace.hops:
            if hop.is_timeout or not hop.hop_ip:
                break
            current = _get_or_create_real_child(current, hop.hop_ip, hostname_map, asn_map, all_nodes)

    for trace in target_traces:
        current = root
        hops = trace.hops
        i = 0
        n = len(hops)
        while i < n:
            hop = hops[i]
            is_timeout = hop.is_timeout or not hop.hop_ip
            if is_timeout:
                # A router failing to reply to some TTL-exceeded probes while
                # forwarding traffic fine is common and doesn't mean the path
                # actually changed. If the next hop this trace *did* get a
                # reply from already matches a real node some other trace
                # reached on this same shared trunk (seeded above, or built
                # by an earlier trace in this very pass), treat the run of
                # timeout(s) as a probe artifact: skip them rather than
                # forking a duplicate "*" subtree, and rejoin the known real
                # path. This intentionally drops the timeout hop(s)' own
                # loss stat from the tree in that case -- there's no node
                # left to attach it to once the fork is elided.
                j = i + 1
                while j < n and (hops[j].is_timeout or not hops[j].hop_ip):
                    j += 1
                if j < n:
                    next_hop = hops[j]
                    label = hostname_map.get(next_hop.hop_ip) or next_hop.hop_ip
                    rejoin = _find_unambiguous_real_descendant(current, label)
                    if rejoin is not None:
                        current = rejoin
                        if next_hop.hop_ip not in current.hop_ips:
                            current.hop_ips.append(next_hop.hop_ip)
                        current.contributions.append(next_hop.stat_dict())
                        i = j + 1
                        continue

                # No known real path to rejoin -- fall back to a real "*"
                # node, merged with any other trace whose timeout landed on
                # this same trie position.
                child = current.children.get("*")
                if child is None:
                    child = _BuildNode(
                        id=_node_id(current.id, "*"),
                        parent_id=current.id,
                        depth=current.depth + 1,
                        hop_ip=None,
                        hop_hostname=None,
                        is_timeout_node=True,
                    )
                    current.children["*"] = child
                    all_nodes[child.id] = child
                child.contributions.append(hop.stat_dict())
                current = child
                i += 1
                continue

            current = _get_or_create_real_child(current, hop.hop_ip, hostname_map, asn_map, all_nodes)
            current.contributions.append(hop.stat_dict())
            i += 1

        last_hop = trace.hops[-1] if trace.hops else None
        leaf_ip = last_hop.hop_ip if last_hop and not last_hop.is_timeout else None

        if leaf_ip is not None:
            # `current` already IS the node for this final hop -- the loop
            # above just finished processing it, including merging it with
            # any other target that shares the same trie position (whether
            # by identical IP or, via hostname_map, a different IP that
            # resolves to the same name). Fold the "destination reached"
            # marker onto it directly instead of adding a redundant sibling
            # carrying the identical IP/hostname, which is what produced a
            # visually duplicated pair (e.g. "dns.google" -> "8.8.8.8" for
            # the exact same physical endpoint) whenever the destination
            # actually responds -- the common/success case. A trace that
            # ends in a timeout has no real final-hop node to fold onto, so
            # it keeps the separate synthetic leaf below.
            current.is_leaf_target = True
            if trace.target_id not in current.target_ids:
                current.target_ids.append(trace.target_id)
        else:
            leaf_label = f"target:{trace.target_id}"
            leaf = _BuildNode(
                id=_node_id(current.id, leaf_label),
                parent_id=current.id,
                depth=current.depth + 1,
                hop_ip=None,
                hop_hostname=None,
                asn=None,
                as_org=None,
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
