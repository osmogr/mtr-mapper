# Architecture

## Services and data flow

```
            ┌──────────┐   mtr subprocess    ┌────────────┐
            │ prober   │ ───────────────────▶ │ (network)  │
            │          │                      └────────────┘
            │  worker  │  GET  /api/prober/targets
            │  pool    │◀──────────────────────────┐
            │          │  POST /api/prober/results  │
            └──────────┘─────────────────────────▶  │
                                                      ▼
┌──────────┐  proxies /api,/ws   ┌──────────────────────────┐      ┌────────┐
│ frontend │ ───────────────────▶│ backend (FastAPI)         │─────▶│   db   │
│ (nginx + │                     │  - REST API               │      │(postgres)│
│  React)  │◀─── WS /ws/tree ────│  - WebSocket broadcast     │◀─────└────────┘
└──────────┘   tree_snapshot/    │  - tree_builder (trie)     │
                tree_diff        │  - target_list_sync        │
                                  │  - retention pruning        │
                                  └──────────────────────────┘
```

`prober` never touches Postgres directly — it only calls `backend`'s HTTP
API. This keeps `backend` the single DB writer/schema owner, and lets it
trigger a debounced tree recompute the instant new results land, without
needing `LISTEN/NOTIFY` or polling the DB for changes.

## Self-throttling probe scheduler

`prober` runs a fixed-size pool of `PROBER_CONCURRENCY` async workers
draining a round-robin queue of active target IDs (min-heap keyed by
"eligible not before" time, refreshed from `PROBER_MIN_CYCLE_SECONDS` each
time a target finishes a run). The achieved per-target cycle time is
therefore approximately:

```
max(PROBER_MIN_CYCLE_SECONDS, (active_targets / PROBER_CONCURRENCY) * avg_mtr_run_seconds)
```

As the target count grows, the achieved interval grows with it automatically
— there's no per-target cron entry to multiply. Total outbound probe
traffic is bounded by concurrency, not by target count. The backend exposes
the *achieved* average interval (derived from `targets.last_probed_at`
deltas) via `GET /api/prober/stats` and the admin UI, so this is observable
rather than just assumed.

## Tree-merge algorithm

`backend/app/services/tree_builder.py` builds a trie keyed by
`(parent_node_id, hop_label)` from each active target's latest completed
run's ordered hops. Node identity is `(parent, label)`, not `(depth, label)`
globally, which is what makes two edge cases behave correctly:

- **Simultaneous timeouts (`*`)**: two targets' timeout hops only merge if
  their paths were already identical up to that point (same parent node).
  Targets that already diverged never spuriously re-merge just because they
  both show `*` at the same hop count.
- **Same IP at different depths** (asymmetric routing): a node has exactly
  one parent/depth by construction, so this can't be mis-merged.

This is a tree, not a DAG: once two targets' paths diverge they never
re-converge into a shared node again even if a later hop happens to match.
That's an accepted simplification — real-world path reconvergence after
divergence is rare and not worth the added complexity.

Node IDs are deterministic (`sha1(parent_id + "|" + hop_label)`), which lets
the backend diff each recompute against the last-broadcast tree (kept in
memory; Postgres remains the real source of truth) and push only
`added`/`updated`/`removed` over the WebSocket instead of the whole tree
every cycle. Recomputation is debounced (`TREE_RECOMPUTE_INTERVAL_SECONDS`)
so a burst of incoming results from many targets coalesces into one
recompute+broadcast.

## Severity

`ok` / `warn` / `critical` per node is loss-percentage based
(`LOSS_WARN_THRESHOLD`, `LOSS_CRITICAL_THRESHOLD`, both configurable) — loss
is a cleaner near-binary "something's wrong" signal than latency, whose
healthy baseline varies a lot per target. Each node also carries
`worst_descendant_severity` (computed bottom-up) so a collapsed/summarized
branch still visually flags a downstream problem.
