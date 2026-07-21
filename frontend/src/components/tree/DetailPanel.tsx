import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { NodeHistoryPoint } from "../../api/types";
import { useTreeStore } from "../../hooks/useTreeStore";
import HistoryChart from "./HistoryChart";
import { formatLoss, formatMs, SEVERITY_COLOR } from "./severity";

interface Props {
  nodeId: string;
  onClose: () => void;
}

function formatRelativeTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(ms / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export default function DetailPanel({ nodeId, onClose }: Props) {
  const node = useTreeStore((s) => s.nodes[nodeId]);
  const targetsById = useTreeStore((s) => s.targetsById);
  const [history, setHistory] = useState<NodeHistoryPoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .nodeHistory(nodeId, 24)
      .then((h) => {
        if (!cancelled) setHistory(h.points);
      })
      .catch(() => {
        if (!cancelled) setHistory([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [nodeId]);

  if (!node) {
    return (
      <aside className="detail-panel">
        <button className="detail-close" onClick={onClose}>
          ×
        </button>
        <p>This node is no longer in the tree.</p>
      </aside>
    );
  }

  const hostname = node.hop_hostname;
  const targets = node.target_ids.map((id) => targetsById[id]).filter(Boolean);

  return (
    <aside className="detail-panel">
      <button className="detail-close" onClick={onClose}>
        ×
      </button>
      <h3>
        {node.is_leaf_target
          ? targets[0]?.display_name || hostname || targets[0]?.address || "Target"
          : node.is_timeout_node
            ? "Unresponsive hop (*)"
            : hostname || node.hop_ip || "Hop"}
      </h3>
      <span
        className="severity-badge"
        style={{ background: SEVERITY_COLOR[node.severity] }}
      >
        {node.severity}
      </span>

      <dl className="detail-fields">
        {!node.is_current && (
          <>
            <dt>Status</dt>
            <dd>
              No longer on the active path
              {node.last_seen_at ? ` — last active ${formatRelativeTime(node.last_seen_at)}` : ""}
            </dd>
          </>
        )}
        {node.hop_ip && (
          <>
            <dt>IP{node.hop_ips.length > 1 ? "s" : ""}</dt>
            <dd>{node.hop_ips.length > 1 ? node.hop_ips.join(", ") : node.hop_ip}</dd>
          </>
        )}
        {hostname && (
          <>
            <dt>Hostname</dt>
            <dd>{hostname}</dd>
          </>
        )}
        {node.asn && (
          <>
            <dt>ASN</dt>
            <dd>
              AS{node.asn}
              {node.as_org ? ` — ${node.as_org}` : ""}
            </dd>
          </>
        )}
        <dt>Loss</dt>
        <dd>{formatLoss(node.own_stats.loss_pct)}</dd>
        <dt>Avg / Best / Worst</dt>
        <dd>
          {formatMs(node.own_stats.avg_ms)} / {formatMs(node.own_stats.best_ms)} /{" "}
          {formatMs(node.own_stats.worst_ms)}
        </dd>
        <dt>Stddev</dt>
        <dd>{formatMs(node.own_stats.stddev_ms)}</dd>
        <dt>Samples</dt>
        <dd>{node.own_stats.sample_count}</dd>
        {targets.length > 0 && (
          <>
            <dt>Target{targets.length > 1 ? "s" : ""}</dt>
            <dd>{targets.map((t) => t.address).join(", ")}</dd>
          </>
        )}
      </dl>

      <h4>History (last 24h)</h4>
      {loading ? <p>Loading…</p> : <HistoryChart points={history} />}
    </aside>
  );
}
