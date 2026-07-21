import { create } from "zustand";

import type { Target, TreeDiffMessage, TreeNode, TreeSnapshotMessage } from "../api/types";

export const ROOT_ID_PLACEHOLDER = "__pending_root__";

interface TreeState {
  nodes: Record<string, TreeNode>;
  seq: number | null;
  connected: boolean;
  lastError: string | null;
  selectedNodeId: string | null;
  manualState: Record<string, "expanded" | "collapsed">;
  targetsById: Record<number, Target>;

  applySnapshot: (msg: TreeSnapshotMessage) => void;
  applyDiff: (msg: TreeDiffMessage) => boolean; // returns false if a gap was detected
  setConnected: (connected: boolean, error?: string | null) => void;
  selectNode: (id: string | null) => void;
  toggleManual: (id: string, defaultCollapsed: boolean) => void;
  setTargets: (targets: Target[]) => void;
  expandAll: () => void;
  collapseAll: (rootChildren: string[], leafCounts: Record<string, number>) => void;
}

export const useTreeStore = create<TreeState>((set, get) => ({
  nodes: {},
  seq: null,
  connected: false,
  lastError: null,
  selectedNodeId: null,
  manualState: {},
  targetsById: {},

  applySnapshot: (msg) => {
    const nodes: Record<string, TreeNode> = {};
    for (const n of msg.nodes) nodes[n.id] = n;
    set({ nodes, seq: msg.seq });
  },

  applyDiff: (msg) => {
    const { seq, nodes } = get();
    if (seq !== null && msg.seq !== seq + 1) {
      // Gap detected (missed message(s), e.g. brief disconnect) -- caller should request a fresh snapshot.
      return false;
    }
    const next = { ...nodes };
    for (const id of msg.removed) delete next[id];
    for (const n of msg.added) next[n.id] = n;
    for (const u of msg.updated) {
      const existing = next[u.id];
      if (existing) {
        next[u.id] = {
          ...existing,
          own_stats: u.own_stats,
          severity: u.severity,
          worst_descendant_severity: u.worst_descendant_severity,
          hop_hostname: u.hop_hostname,
          hop_ips: u.hop_ips,
          asn: u.asn,
          as_org: u.as_org,
          is_current: u.is_current,
          last_seen_at: u.last_seen_at,
        };
      }
    }
    set({ nodes: next, seq: msg.seq });
    return true;
  },

  setConnected: (connected, error = null) => set({ connected, lastError: error }),
  selectNode: (id) => set({ selectedNodeId: id }),

  toggleManual: (id, defaultCollapsed) =>
    set((state) => {
      const current = state.manualState[id];
      const currentlyCollapsed = current ? current === "collapsed" : defaultCollapsed;
      return {
        manualState: { ...state.manualState, [id]: currentlyCollapsed ? "expanded" : "collapsed" },
      };
    }),

  setTargets: (targets) => {
    const byId: Record<number, Target> = {};
    for (const t of targets) byId[t.id] = t;
    set({ targetsById: byId });
  },

  expandAll: () => set({ manualState: {} }),

  collapseAll: (rootChildren, leafCounts) => {
    const manual: Record<string, "expanded" | "collapsed"> = {};
    // Collapse every node directly under the root (and anything with >1 leaf) so the
    // whole tree starts fully summarized; user can drill in from there.
    for (const childId of rootChildren) {
      if ((leafCounts[childId] ?? 1) > 1) manual[childId] = "collapsed";
    }
    set({ manualState: manual });
  },
}));
