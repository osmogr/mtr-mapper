import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { connectTreeSocket } from "../api/ws";
import type { ProberStats } from "../api/types";
import DetailPanel from "../components/tree/DetailPanel";
import TreeCanvas from "../components/tree/TreeCanvas";
import { useTreeStore } from "../hooks/useTreeStore";

export default function TreeView() {
  const connected = useTreeStore((s) => s.connected);
  const selectedNodeId = useTreeStore((s) => s.selectedNodeId);
  const selectNode = useTreeStore((s) => s.selectNode);
  const setTargets = useTreeStore((s) => s.setTargets);
  const applySnapshot = useTreeStore((s) => s.applySnapshot);
  const [stats, setStats] = useState<ProberStats | null>(null);

  useEffect(() => {
    // Prime with a REST snapshot immediately so the tree isn't blank while the
    // WebSocket handshake completes; the socket then takes over as the live feed.
    api.tree().then(applySnapshot).catch(() => {});
    const disconnect = connectTreeSocket();
    return disconnect;
  }, [applySnapshot]);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      api
        .targets()
        .then((ts) => !cancelled && setTargets(ts))
        .catch(() => {});
      api
        .proberStats()
        .then((s) => !cancelled && setStats(s))
        .catch(() => {});
    };
    refresh();
    const interval = setInterval(refresh, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [setTargets]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>mtr-mapper</h1>
        <div className="header-status">
          <span className={`ws-dot ${connected ? "ws-up" : "ws-down"}`} />
          {connected ? "live" : "reconnecting…"}
          {stats && (
            <span className="stats-summary">
              {stats.active_target_count} targets
              {stats.achieved_avg_cycle_seconds != null &&
                ` · ~${Math.round(stats.achieved_avg_cycle_seconds)}s refresh`}
            </span>
          )}
        </div>
        <Link to="/admin" className="admin-link">
          Admin
        </Link>
      </header>
      <main className="app-main">
        <TreeCanvas onSelectNode={selectNode} />
        {selectedNodeId && <DetailPanel nodeId={selectedNodeId} onClose={() => selectNode(null)} />}
      </main>
    </div>
  );
}
