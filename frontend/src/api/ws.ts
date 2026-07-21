import { useTreeStore } from "../hooks/useTreeStore";
import type { TreeWsMessage } from "./types";

const MIN_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 15000;

export function connectTreeSocket(): () => void {
  let socket: WebSocket | null = null;
  let backoff = MIN_BACKOFF_MS;
  let closedByCaller = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const wsUrl = () => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws/tree`;
  };

  const connect = () => {
    if (closedByCaller) return;
    socket = new WebSocket(wsUrl());

    socket.onopen = () => {
      backoff = MIN_BACKOFF_MS;
      useTreeStore.getState().setConnected(true);
    };

    socket.onmessage = (event) => {
      let msg: TreeWsMessage;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      const store = useTreeStore.getState();
      if (msg.type === "tree_snapshot") {
        store.applySnapshot(msg);
      } else if (msg.type === "tree_diff") {
        const ok = store.applyDiff(msg);
        if (!ok) {
          socket?.send(JSON.stringify({ type: "request_snapshot" }));
        }
      }
    };

    socket.onclose = () => {
      useTreeStore.getState().setConnected(false, "disconnected");
      if (closedByCaller) return;
      reconnectTimer = setTimeout(connect, backoff + Math.random() * backoff * 0.25);
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
    };

    socket.onerror = () => {
      socket?.close();
    };
  };

  connect();

  return () => {
    closedByCaller = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    socket?.close();
  };
}
