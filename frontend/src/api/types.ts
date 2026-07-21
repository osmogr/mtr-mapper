export type Severity = "ok" | "warn" | "critical" | "unknown";

export interface NodeStats {
  loss_pct: number | null;
  avg_ms: number | null;
  best_ms: number | null;
  worst_ms: number | null;
  stddev_ms: number | null;
  sample_count: number;
}

export interface TreeNode {
  id: string;
  parent_id: string | null;
  depth: number;
  hop_ip: string | null;
  hop_hostname: string | null;
  asn: number | null;
  as_org: string | null;
  is_timeout_node: boolean;
  is_leaf_target: boolean;
  target_ids: number[];
  own_stats: NodeStats;
  severity: Severity;
  worst_descendant_severity: Severity;
  is_current: boolean;
  last_seen_at: string | null;
  children: string[];
}

export interface TreeSnapshotMessage {
  type: "tree_snapshot";
  seq: number;
  nodes: TreeNode[];
}

export interface NodeStatsUpdate {
  id: string;
  own_stats: NodeStats;
  severity: Severity;
  worst_descendant_severity: Severity;
  asn: number | null;
  as_org: string | null;
  is_current: boolean;
  last_seen_at: string | null;
}

export interface TreeDiffMessage {
  type: "tree_diff";
  seq: number;
  added: TreeNode[];
  updated: NodeStatsUpdate[];
  removed: string[];
}

export type TreeWsMessage = TreeSnapshotMessage | TreeDiffMessage;

export interface Target {
  id: number;
  address: string;
  display_name: string | null;
  active: boolean;
  last_probed_at: string | null;
  last_probe_success: boolean | null;
  sources: string[];
}

export interface TargetList {
  id: number;
  name: string;
  url: string;
  fetch_interval_seconds: number;
  active: boolean;
  last_fetched_at: string | null;
  last_fetch_status: "ok" | "error" | null;
  last_fetch_error: string | null;
  last_fetch_target_count: number | null;
}

export interface HopHistoryPoint {
  run_started_at: string;
  hop_number: number;
  hop_ip: string | null;
  hop_hostname: string | null;
  is_timeout: boolean;
  loss_pct: number | null;
  avg_ms: number | null;
  best_ms: number | null;
  worst_ms: number | null;
  stddev_ms: number | null;
}

export interface TargetHistory {
  target_id: number;
  address: string;
  points: HopHistoryPoint[];
}

export interface NodeHistoryPoint {
  run_started_at: string;
  loss_pct: number | null;
  avg_ms: number | null;
  best_ms: number | null;
  worst_ms: number | null;
  stddev_ms: number | null;
  sample_count: number;
}

export interface NodeHistory {
  node_id: string;
  points: NodeHistoryPoint[];
}

export interface NodeDetail {
  node: TreeNode;
  resolved_hostname: string | null;
}

export interface ProberStats {
  active_target_count: number;
  probed_at_least_once: number;
  achieved_avg_cycle_seconds: number | null;
}
