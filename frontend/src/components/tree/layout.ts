import { hierarchy, tree as d3tree, type HierarchyPointNode } from "d3-hierarchy";

import type { TreeNode } from "../../api/types";

export interface VisibleNodeMeta {
  id: string;
  isSummary: boolean;
  summarizedLeafCount: number;
  isCurrent: boolean;
  lastSeenAt: string | null;
  children: VisibleNodeMeta[];
}

/** Parent -> children index derived purely from every known node's own
 * `parent_id`, rather than each node's backend-provided `children` list.
 * The backend's `children` array only lists currently-live children (it's
 * rebuilt fresh from the current merged tree every cycle), so a node kept
 * around as a fading "ghost" after its path rerouted would otherwise be
 * silently orphaned from traversal even though it's still in `nodes`. */
export function groupChildrenByParentId(nodes: Record<string, TreeNode>): Record<string, string[]> {
  const map: Record<string, string[]> = {};
  for (const n of Object.values(nodes)) {
    if (n.parent_id === null) continue;
    (map[n.parent_id] ??= []).push(n.id);
  }
  return map;
}

/** Drop faded/historical (non-current) nodes entirely -- used for the
 * "Current Path only" view toggle. Keeping only current nodes means their
 * parent_id chains stay intact back to the root (a node's ancestors are
 * always current whenever it is), so no additional reachability fixup is
 * needed beyond a simple filter. */
export function filterToCurrent(nodes: Record<string, TreeNode>): Record<string, TreeNode> {
  const filtered: Record<string, TreeNode> = {};
  for (const [id, n] of Object.entries(nodes)) {
    if (n.is_current) filtered[id] = n;
  }
  return filtered;
}

function aggregateFade(
  id: string,
  nodes: Record<string, TreeNode>,
  childrenByParentId: Record<string, string[]>,
): { isCurrent: boolean; lastSeenAt: string | null } {
  const node = nodes[id];
  if (!node) return { isCurrent: false, lastSeenAt: null };
  let isCurrent = node.is_current;
  let lastSeenAt = node.last_seen_at;
  for (const childId of childrenByParentId[id] ?? []) {
    const child = aggregateFade(childId, nodes, childrenByParentId);
    if (child.isCurrent) isCurrent = true;
    if (child.lastSeenAt && (!lastSeenAt || child.lastSeenAt > lastSeenAt)) {
      lastSeenAt = child.lastSeenAt;
    }
  }
  return { isCurrent, lastSeenAt };
}

const NODE_SPACING_ACROSS = 36; // px between sibling nodes (room for the ASN line below each label)
const NODE_SPACING_DEPTH = 190; // px between depth levels

/** Bottom-up count of *currently active* leaf targets under every node, from
 * the full node set (not just the visible/collapsed one) -- used both to
 * decide default auto-collapse and to label collapsed summary nodes with "N
 * targets". A rerouted path leaves its old leaf node around as a fading
 * ghost (see path-fade feature) with the same target_id as its new, current
 * leaf -- that's the same target, not an additional one, so stale leaves
 * count as 0 here rather than double-counting history as more targets. */
export function computeLeafCounts(
  nodes: Record<string, TreeNode>,
  rootId: string,
  childrenByParentId: Record<string, string[]>,
): Record<string, number> {
  const counts: Record<string, number> = {};
  function visit(id: string): number {
    if (counts[id] !== undefined) return counts[id];
    const node = nodes[id];
    if (!node) return 0;
    if (node.is_leaf_target) {
      counts[id] = node.is_current ? 1 : 0;
      return counts[id];
    }
    let sum = 0;
    for (const childId of childrenByParentId[id] ?? []) sum += visit(childId);
    counts[id] = sum;
    return sum;
  }
  visit(rootId);
  return counts;
}

export function buildVisibleTree(
  nodes: Record<string, TreeNode>,
  rootId: string,
  leafCounts: Record<string, number>,
  manualState: Record<string, "expanded" | "collapsed">,
  collapseThreshold: number,
  childrenByParentId: Record<string, string[]>,
): VisibleNodeMeta | null {
  const root = nodes[rootId];
  if (!root) return null;

  function isCollapsed(id: string): boolean {
    const manual = manualState[id];
    if (manual) return manual === "collapsed";
    return (leafCounts[id] ?? 0) > collapseThreshold;
  }

  function build(id: string): VisibleNodeMeta {
    const node = nodes[id];
    const collapsed = id !== rootId && !node.is_leaf_target && isCollapsed(id);
    if (collapsed) {
      const fade = aggregateFade(id, nodes, childrenByParentId);
      return {
        id,
        isSummary: true,
        summarizedLeafCount: leafCounts[id] ?? 0,
        isCurrent: fade.isCurrent,
        lastSeenAt: fade.lastSeenAt,
        children: [],
      };
    }
    return {
      id,
      isSummary: false,
      summarizedLeafCount: leafCounts[id] ?? 0,
      isCurrent: node.is_current,
      lastSeenAt: node.last_seen_at,
      children: (childrenByParentId[id] ?? []).filter((cid) => nodes[cid] !== undefined).map(build),
    };
  }

  return build(rootId);
}

/** Stable serialization of just the visible topology (ids + summary flags),
 * independent of stat/severity fields, so layout recompute can be skipped
 * when only stats changed between two tree_diff messages. */
export function serializeStructure(tree: VisibleNodeMeta | null): string {
  if (!tree) return "";
  const parts: string[] = [];
  function visit(n: VisibleNodeMeta) {
    parts.push(n.isSummary ? `${n.id}!` : n.id);
    for (const c of n.children) visit(c);
  }
  visit(tree);
  return parts.join(",");
}

export type LayoutNode = HierarchyPointNode<VisibleNodeMeta>;

export function computeLayout(tree: VisibleNodeMeta | null): LayoutNode[] {
  if (!tree) return [];
  const root = hierarchy(tree, (d) => d.children);
  const layoutFn = d3tree<VisibleNodeMeta>().nodeSize([NODE_SPACING_ACROSS, NODE_SPACING_DEPTH]);
  const laidOut = layoutFn(root);
  return laidOut.descendants();
}
