import type { Severity } from "../../api/types";

export const SEVERITY_COLOR: Record<Severity, string> = {
  ok: "#2f9e44",
  warn: "#f08c00",
  critical: "#e03131",
  unknown: "#868e96",
};

export function formatMs(v: number | null | undefined): string {
  if (v === null || v === undefined) return "-";
  return `${v.toFixed(1)}ms`;
}

export function formatLoss(v: number | null | undefined): string {
  if (v === null || v === undefined) return "-";
  return `${v.toFixed(1)}%`;
}
