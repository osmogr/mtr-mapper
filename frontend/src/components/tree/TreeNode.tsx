import { memo } from "react";

import type { Target, TreeNode as TreeNodeData } from "../../api/types";
import { asnColorVar } from "./asnColor";
import { SEVERITY_COLOR } from "./severity";

interface Props {
  x: number;
  y: number;
  node: TreeNodeData | undefined;
  isSummary: boolean;
  summarizedLeafCount: number;
  isSelected: boolean;
  isRoot: boolean;
  opacity: number;
  target: Target | undefined;
  onClick: () => void;
}

function labelFor(node: TreeNodeData | undefined, isSummary: boolean, count: number, target: Target | undefined): string {
  if (isSummary) return `${count} target${count === 1 ? "" : "s"}`;
  if (!node) return "";
  if (node.is_leaf_target) {
    // A leaf-target node whose final hop actually responded (the common
    // case) carries that hop's own resolved hostname -- prefer it over the
    // target's raw configured address (e.g. show "dns.google" rather than
    // the "8.8.8.8" the admin typed in), same preference order used for
    // every other node's label. An explicit display_name still wins.
    return target?.display_name || node.hop_hostname || target?.address || node.hop_ip || "target";
  }
  if (node.is_timeout_node) return "*";
  return node.hop_hostname || node.hop_ip || "";
}

// Long FQDNs (e.g. "be-36421-cs02.losangeles.ca.ibone.comcast.net") otherwise
// overlap the next depth column, since NODE_SPACING_DEPTH is fixed and can't
// grow to fit every possible hostname without wasting space on the (much
// more common) short IP/short-name labels. Truncate with an ellipsis and
// rely on a native SVG tooltip for the full value.
const MAX_LABEL_CHARS = 26;

function truncateLabel(label: string): string {
  if (label.length <= MAX_LABEL_CHARS) return label;
  return `${label.slice(0, MAX_LABEL_CHARS - 1)}…`;
}

function TreeNodeComponent({ x, y, node, isSummary, summarizedLeafCount, isSelected, isRoot, opacity, target, onClick }: Props) {
  const severity = node?.severity ?? "unknown";
  const worst = node?.worst_descendant_severity ?? "unknown";
  const color = isRoot ? "#495057" : SEVERITY_COLOR[isSummary ? worst : severity];
  const radius = isRoot ? 8 : isSummary ? 10 : node?.is_leaf_target ? 6 : 5;
  const label = isRoot ? "you" : labelFor(node, isSummary, summarizedLeafCount, target);
  const displayLabel = truncateLabel(label);
  const asnLabel = !isSummary && node?.asn ? `AS${node.asn}` : null;
  const asnRingColor = !isSummary && node?.asn ? asnColorVar(node.asn) : null;

  return (
    <g
      transform={`translate(${y},${x})`}
      onClick={onClick}
      style={{ cursor: "pointer", opacity }}
      data-node-id={node?.id}
    >
      {asnRingColor && (
        <circle r={radius + 3} fill="none" stroke={asnRingColor} strokeWidth={2} />
      )}
      <circle
        r={radius}
        fill={color}
        stroke={isSelected ? "#1c7ed6" : "#fff"}
        strokeWidth={isSelected ? 3 : 1.5}
      />
      {isSummary && (
        <text textAnchor="middle" dy="0.35em" fontSize={9} fill="#fff" fontWeight={600}>
          {summarizedLeafCount}
        </text>
      )}
      <text x={0} y={radius + 13} textAnchor="middle" fontSize={11} fill="var(--tree-label-color, #212529)">
        {displayLabel}
        {displayLabel !== label && <title>{label}</title>}
      </text>
      {asnLabel && (
        <text x={0} y={radius + 25} textAnchor="middle" fontSize={9} fill="var(--text-muted, #868e96)">
          {asnLabel}
        </text>
      )}
    </g>
  );
}

export default memo(TreeNodeComponent);
