import { select } from "d3-selection";
import { zoom, zoomIdentity, type D3ZoomEvent, type ZoomBehavior } from "d3-zoom";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { useTreeStore } from "../../hooks/useTreeStore";
import {
  buildVisibleTree,
  computeLayout,
  computeLeafCounts,
  filterToCurrent,
  groupChildrenByParentId,
  serializeStructure,
  type LayoutNode,
} from "./layout";
import TreeNodeComponent from "./TreeNode";

const COLLAPSE_THRESHOLD = 15;

// Keep in sync with the backend's `path_fade_hours` setting (default 24h,
// backend/app/config.py) -- how long a rerouted/stale hop stays visible
// before fully fading out.
const FADE_DURATION_MS = 24 * 60 * 60 * 1000;

function fadeOpacity(isCurrent: boolean, lastSeenAt: string | null, now: number): number {
  if (isCurrent || !lastSeenAt) return 1;
  const age = now - new Date(lastSeenAt).getTime();
  return Math.max(0, 1 - age / FADE_DURATION_MS);
}

interface Props {
  onSelectNode: (id: string) => void;
}

export default function TreeCanvas({ onSelectNode }: Props) {
  const nodes = useTreeStore((s) => s.nodes);
  const manualState = useTreeStore((s) => s.manualState);
  const selectedNodeId = useTreeStore((s) => s.selectedNodeId);
  const targetsById = useTreeStore((s) => s.targetsById);
  const toggleManual = useTreeStore((s) => s.toggleManual);
  const expandAll = useTreeStore((s) => s.expandAll);
  const collapseAll = useTreeStore((s) => s.collapseAll);

  const [showHistorical, setShowHistorical] = useState(true);

  const rootId = useMemo(() => {
    for (const n of Object.values(nodes)) if (n.parent_id === null) return n.id;
    return null;
  }, [nodes]);

  const effectiveNodes = useMemo(
    () => (showHistorical ? nodes : filterToCurrent(nodes)),
    [nodes, showHistorical],
  );

  const childrenByParentId = useMemo(() => groupChildrenByParentId(effectiveNodes), [effectiveNodes]);

  const leafCounts = useMemo(
    () => (rootId ? computeLeafCounts(effectiveNodes, rootId, childrenByParentId) : {}),
    [effectiveNodes, rootId, childrenByParentId],
  );

  const visibleTree = useMemo(
    () =>
      rootId
        ? buildVisibleTree(
            effectiveNodes,
            rootId,
            leafCounts,
            manualState,
            COLLAPSE_THRESHOLD,
            childrenByParentId,
          )
        : null,
    [effectiveNodes, rootId, leafCounts, manualState, childrenByParentId],
  );

  const structureSignature = useMemo(() => serializeStructure(visibleTree), [visibleTree]);

  const layoutCache = useRef<{ signature: string; layout: LayoutNode[] } | null>(null);
  const layout = useMemo(() => {
    if (layoutCache.current && layoutCache.current.signature === structureSignature) {
      return layoutCache.current.layout;
    }
    const computed = computeLayout(visibleTree);
    layoutCache.current = { signature: structureSignature, layout: computed };
    return computed;
  }, [structureSignature, visibleTree]);

  // State (not refs) for the svg/g DOM nodes: the component can render the
  // "waiting for data" placeholder (no <svg> at all) before the tree exists,
  // so effects that set up d3-zoom must re-run once these nodes actually
  // mount rather than only once on the component's first-ever render.
  const [svgEl, setSvgEl] = useState<SVGSVGElement | null>(null);
  const [gEl, setGEl] = useState<SVGGElement | null>(null);
  const zoomBehaviorRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const hasFitRef = useRef(false);
  const hasInteractedRef = useRef(false);
  const [search, setSearch] = useState("");

  // Forces a re-render periodically so stale-path opacity keeps fading even
  // when no new websocket data arrives (fade is purely a function of elapsed
  // wall-clock time since a node's last_seen_at, computed at render time).
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);

  // Computed once per render (not once per node per render-pass) since the
  // same fade value is needed for both the link and the node in each row.
  const opacityById = useMemo(() => {
    const map: Record<string, number> = {};
    for (const d of layout) map[d.data.id] = fadeOpacity(d.data.isCurrent, d.data.lastSeenAt, now);
    return map;
  }, [layout, now]);

  const fitView = useCallback(
    (animate: boolean): boolean => {
      const zoomBehavior = zoomBehaviorRef.current;
      if (!svgEl || !zoomBehavior || layout.length === 0) return false;
      const { width, height } = svgEl.getBoundingClientRect();
      if (width === 0 || height === 0) return false;

      // Screen-x comes from depth (d.y), screen-y comes from sibling offset (d.x).
      let minScreenX = Infinity;
      let maxScreenX = -Infinity;
      let minScreenY = Infinity;
      let maxScreenY = -Infinity;
      for (const d of layout) {
        if (d.y < minScreenX) minScreenX = d.y;
        if (d.y > maxScreenX) maxScreenX = d.y;
        if (d.x < minScreenY) minScreenY = d.x;
        if (d.x > maxScreenY) maxScreenY = d.x;
      }
      const padLeft = 24;
      const padRight = 160; // labels extend to the right of each node
      const padVert = 24;
      const contentWidth = maxScreenX - minScreenX + padLeft + padRight;
      const contentHeight = maxScreenY - minScreenY + padVert * 2;

      const scale = Math.max(0.1, Math.min(1, width / contentWidth, height / contentHeight));
      const centerScreenX = (minScreenX + maxScreenX) / 2;
      const centerScreenY = (minScreenY + maxScreenY) / 2;
      const tx = width / 2 - scale * centerScreenX;
      const ty = height / 2 - scale * centerScreenY;
      const transform = zoomIdentity.translate(tx, ty).scale(scale);

      const svgSel = select(svgEl);
      if (animate) {
        svgSel.transition().duration(300).call(zoomBehavior.transform, transform);
      } else {
        svgSel.call(zoomBehavior.transform, transform);
      }
      return true;
    },
    [svgEl, layout],
  );

  useEffect(() => {
    if (!svgEl || !gEl) return;
    const svgSel = select(svgEl);
    const gSel = select(gEl);
    const zoomBehavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 3])
      .on("zoom", (event: D3ZoomEvent<SVGSVGElement, unknown>) => {
        gSel.attr("transform", event.transform.toString());
        if (event.sourceEvent) hasInteractedRef.current = true;
      });
    zoomBehaviorRef.current = zoomBehavior;
    svgSel.call(zoomBehavior);
    return () => {
      svgSel.on(".zoom", null);
      zoomBehaviorRef.current = null;
    };
  }, [svgEl, gEl]);

  // Fit the view once the svg has mounted and the first layout is available,
  // so the initial view is centered and scaled to the actual tree instead of
  // a hardcoded offset. Guarded so it only actually happens once; if it can't
  // (e.g. zero-size container on this pass) it stays unset and retries on the
  // next layout/svg change rather than silently giving up forever.
  useEffect(() => {
    if (hasFitRef.current) return;
    if (fitView(false)) hasFitRef.current = true;
  }, [layout, fitView]);

  // Re-fit on container resize (e.g. detail panel opening/closing), but only
  // until the user manually pans/zooms -- after that, respect their view.
  useEffect(() => {
    const wrapEl = svgEl?.parentElement;
    if (!wrapEl) return;
    const observer = new ResizeObserver(() => {
      if (!hasInteractedRef.current) fitView(false);
    });
    observer.observe(wrapEl);
    return () => observer.disconnect();
  }, [svgEl, fitView]);

  function handleSearch(e: FormEvent) {
    e.preventDefault();
    const q = search.trim().toLowerCase();
    if (!q) return;
    const match = Object.values(nodes).find((n) => {
      if (n.hop_ip?.toLowerCase().includes(q)) return true;
      if (n.hop_hostname?.toLowerCase().includes(q)) return true;
      if (n.is_leaf_target) {
        for (const tid of n.target_ids) {
          const t = targetsById[tid];
          if (t && (t.address.toLowerCase().includes(q) || t.display_name?.toLowerCase().includes(q))) {
            return true;
          }
        }
      }
      return false;
    });
    if (!match) return;

    // Expand every ancestor so the match becomes visible.
    const ancestors: string[] = [];
    let cur: string | null = match.parent_id;
    while (cur) {
      ancestors.push(cur);
      cur = nodes[cur]?.parent_id ?? null;
    }
    const next = { ...manualState };
    for (const id of ancestors) next[id] = "expanded";
    useTreeStore.setState({ manualState: next, selectedNodeId: match.id });
    onSelectNode(match.id);
  }

  if (!rootId) {
    return <div className="tree-empty">Waiting for the first trace results…</div>;
  }

  return (
    <div className="tree-canvas-wrap">
      <div className="tree-toolbar">
        <form onSubmit={handleSearch}>
          <input
            type="text"
            placeholder="Search by hostname/IP…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>
        <button onClick={() => expandAll()}>Expand all</button>
        <button onClick={() => collapseAll(childrenByParentId[rootId] ?? [], leafCounts)}>Collapse all</button>
        <button onClick={() => fitView(true)}>Fit view</button>
        <label className="tree-path-toggle">
          <input
            type="checkbox"
            checked={showHistorical}
            onChange={(e) => setShowHistorical(e.target.checked)}
          />
          Show historical paths
        </label>
        <span className="tree-count">{Object.keys(effectiveNodes).length} nodes</span>
      </div>
      <svg ref={setSvgEl} className="tree-svg">
        <g ref={setGEl}>
          <g className="tree-links">
            {layout.map((d) => {
              if (!d.parent) return null;
              const path = `M${d.parent.y},${d.parent.x} C${(d.parent.y + d.y) / 2},${d.parent.x} ${
                (d.parent.y + d.y) / 2
              },${d.x} ${d.y},${d.x}`;
              return (
                <path
                  key={d.data.id}
                  d={path}
                  className="tree-link"
                  style={{
                    stroke: d.data.isCurrent ? "var(--accent)" : "var(--border)",
                    opacity: opacityById[d.data.id],
                  }}
                />
              );
            })}
          </g>
          <g className="tree-nodes">
            {layout.map((d) => {
              const node = nodes[d.data.id];
              const isRoot = d.data.id === rootId;
              return (
                <TreeNodeComponent
                  key={d.data.id}
                  x={d.x}
                  y={d.y}
                  node={node}
                  isSummary={d.data.isSummary}
                  summarizedLeafCount={d.data.summarizedLeafCount}
                  isSelected={selectedNodeId === d.data.id}
                  isRoot={isRoot}
                  opacity={isRoot ? 1 : opacityById[d.data.id]}
                  target={
                    node?.is_leaf_target && node.target_ids.length > 0
                      ? targetsById[node.target_ids[0]]
                      : undefined
                  }
                  onClick={() => {
                    if (d.data.isSummary) {
                      toggleManual(d.data.id, true);
                    } else {
                      onSelectNode(d.data.id);
                    }
                  }}
                />
              );
            })}
          </g>
        </g>
      </svg>
    </div>
  );
}
