import type {
  NodeDetail,
  NodeHistory,
  ProberStats,
  Target,
  TargetHistory,
  TargetList,
  TreeSnapshotMessage,
} from "./types";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(res.status, body || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  // auth
  login: (password: string) =>
    request<{ authenticated: boolean }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  logout: () => request<{ authenticated: boolean }>("/api/auth/logout", { method: "POST" }),
  session: () => request<{ authenticated: boolean }>("/api/auth/session"),

  // public reads
  tree: () => request<TreeSnapshotMessage>("/api/tree"),
  targets: (params?: { active?: boolean }) => {
    const qs = params?.active !== undefined ? `?active=${params.active}` : "";
    return request<Target[]>(`/api/targets${qs}`);
  },
  targetHistory: (id: number, hours = 24) =>
    request<TargetHistory>(`/api/targets/${id}/history?hours=${hours}`),
  nodeDetail: (nodeId: string) => request<NodeDetail>(`/api/nodes/${nodeId}`),
  nodeHistory: (nodeId: string, hours = 24) =>
    request<NodeHistory>(`/api/nodes/${nodeId}/history?hours=${hours}`),
  proberStats: () => request<ProberStats>("/api/prober/stats"),

  // admin: targets
  adminListTargets: (params?: { q?: string; active?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.q) qs.set("q", params.q);
    if (params?.active !== undefined) qs.set("active", String(params.active));
    const suffix = qs.toString() ? `?${qs}` : "";
    return request<Target[]>(`/api/admin/targets${suffix}`);
  },
  adminCreateTarget: (address: string, display_name?: string) =>
    request<Target>("/api/admin/targets", {
      method: "POST",
      body: JSON.stringify({ address, display_name }),
    }),
  adminUpdateTarget: (id: number, patch: { active?: boolean; display_name?: string }) =>
    request<Target>(`/api/admin/targets/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  adminDeleteTarget: (id: number) =>
    request<void>(`/api/admin/targets/${id}`, { method: "DELETE" }),

  // admin: target lists
  adminListTargetLists: () => request<TargetList[]>("/api/admin/target-lists"),
  adminCreateTargetList: (payload: { name: string; url: string; fetch_interval_seconds?: number }) =>
    request<TargetList>("/api/admin/target-lists", { method: "POST", body: JSON.stringify(payload) }),
  adminUpdateTargetList: (
    id: number,
    patch: Partial<{ name: string; url: string; fetch_interval_seconds: number; active: boolean }>,
  ) =>
    request<TargetList>(`/api/admin/target-lists/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  adminDeleteTargetList: (id: number) =>
    request<void>(`/api/admin/target-lists/${id}`, { method: "DELETE" }),
  adminSyncTargetListNow: (id: number) =>
    request<TargetList>(`/api/admin/target-lists/${id}/sync-now`, { method: "POST" }),
};

export { ApiError };
