# WebSocket protocol — `/ws/tree`

Not covered by the OpenAPI schema, so documented by hand here. All messages
are JSON text frames.

## Node shape (`TreeNode`)

```jsonc
{
  "id": "3f9a1c...",                 // sha1(parent_id + "|" + hop_label), stable across recomputes
  "parent_id": "a01e77..." ,         // null for the root
  "depth": 3,
  "hop_ip": "203.0.113.1",           // null when is_timeout_node
  "hop_hostname": null,              // lazily resolved/cached, may be null
  "is_timeout_node": false,
  "is_leaf_target": false,
  "target_ids": [],                  // populated on leaf nodes; >1 if targets share a terminal hop
  "own_stats": {
    "loss_pct": 0.0,
    "avg_ms": 12.4,
    "best_ms": 11.9,
    "worst_ms": 13.1,
    "stddev_ms": 0.4,
    "sample_count": 5
  },
  "severity": "ok",                  // "ok" | "warn" | "critical"
  "worst_descendant_severity": "warn",
  "children": ["b7e2f0...", "c81d44..."]
}
```

## Server → client messages

**On connect**, the server sends a full snapshot:

```jsonc
{"type": "tree_snapshot", "seq": 1042, "nodes": [TreeNode, ...]}
```

**On each debounced recompute** (default every `TREE_RECOMPUTE_INTERVAL_SECONDS`,
only sent if something actually changed), a diff:

```jsonc
{
  "type": "tree_diff",
  "seq": 1043,
  "added": [TreeNode, ...],
  "updated": [
    {"id": "3f9a1c...", "own_stats": {...}, "severity": "warn", "worst_descendant_severity": "warn"}
  ],
  "removed": ["node-id-1", "node-id-2"]
}
```

`seq` increases by exactly 1 per message on a given connection. If a client
detects a gap (e.g. after a reconnect, or a dropped frame), it should send:

```jsonc
{"type": "request_snapshot"}
```

and the server responds with a fresh `tree_snapshot` (with a new `seq`
baseline).

## Client → server messages

- `{"type": "request_snapshot"}` — ask for a full resync.
- `{"type": "ping"}` — optional keepalive; server replies `{"type": "pong"}`.

## Reconnection

The frontend WS client should reconnect with jittered exponential backoff and
always send `request_snapshot` immediately after a reconnect, since any
diffs broadcast while disconnected were missed.
