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
  if (node.is_leaf_target) return target?.display_name || target?.address || node.hop_ip || "target";
  if (node.is_timeout_node) return "*";
  return node.hop_hostname || node.hop_ip || "";
}

function TreeNodeComponent({ x, y, node, isSummary, summarizedLeafCount, isSelected, isRoot, opacity, target, onClick }: Props) {
  const severity = node?.severity ?? "unknown";
  const worst = node?.worst_descendant_severity ?? "unknown";
  const color = isRoot ? "#495057" : SEVERITY_COLOR[isSummary ? worst : severity];
  const radius = isRoot ? 8 : isSummary ? 10 : node?.is_leaf_target ? 6 : 5;
  const label = isRoot ? "you" : labelFor(node, isSummary, summarizedLeafCount, target);
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
      <text x={radius + 6} dy="0.32em" fontSize={11} fill="var(--tree-label-color, #212529)">
        {label}
      </text>
      {asnLabel && (
        <text x={radius + 6} y={12} fontSize={9} fill="var(--text-muted, #868e96)">
          {asnLabel}
        </text>
      )}
    </g>
  );
}

export default memo(TreeNodeComponent);
