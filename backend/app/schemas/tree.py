from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Severity = Literal["ok", "warn", "critical", "unknown"]


class NodeStats(BaseModel):
    loss_pct: float | None = None
    avg_ms: float | None = None
    best_ms: float | None = None
    worst_ms: float | None = None
    stddev_ms: float | None = None
    sample_count: int = 0


class TreeNode(BaseModel):
    id: str
    parent_id: str | None
    depth: int
    hop_ip: str | None
    hop_ips: list[str] = []
    hop_hostname: str | None
    asn: int | None = None
    as_org: str | None = None
    is_timeout_node: bool
    is_leaf_target: bool
    target_ids: list[int] = []
    own_stats: NodeStats
    severity: Severity
    worst_descendant_severity: Severity
    is_current: bool = True
    last_seen_at: datetime | None = None
    children: list[str] = []


class TreeSnapshotMessage(BaseModel):
    type: Literal["tree_snapshot"] = "tree_snapshot"
    seq: int
    nodes: list[TreeNode]


class NodeStatsUpdate(BaseModel):
    id: str
    own_stats: NodeStats
    severity: Severity
    worst_descendant_severity: Severity
    hop_hostname: str | None = None
    hop_ips: list[str] = []
    asn: int | None = None
    as_org: str | None = None
    is_current: bool = True
    last_seen_at: datetime | None = None


class TreeDiffMessage(BaseModel):
    type: Literal["tree_diff"] = "tree_diff"
    seq: int
    added: list[TreeNode] = []
    updated: list[NodeStatsUpdate] = []
    removed: list[str] = []


class NodeDetail(BaseModel):
    node: TreeNode


class NodeHistoryPoint(BaseModel):
    run_started_at: str
    loss_pct: float | None
    avg_ms: float | None
    best_ms: float | None
    worst_ms: float | None
    stddev_ms: float | None
    sample_count: int


class NodeHistory(BaseModel):
    node_id: str
    points: list[NodeHistoryPoint]
