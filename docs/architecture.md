# Architecture

## Services and data flow

```
            ┌──────────┐   scamper/mtr       ┌────────────┐
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
max(PROBER_MIN_CYCLE_SECONDS, (active_targets / PROBER_CONCURRENCY) * avg_probe_run_seconds)
```

As the target count grows, the achieved interval grows with it automatically
— there's no per-target cron entry to multiply. Total outbound probe
traffic is bounded by concurrency, not by target count. The backend exposes
the *achieved* average interval (derived from `targets.last_probed_at`
deltas) via `GET /api/prober/stats` and the admin UI, so this is observable
rather than just assumed.

## Probe method: scamper (Paris-consistent) vs mtr

`prober` shells out to either `mtr` or `scamper` per run, selected globally
by `PROBE_METHOD` (`app/prober_strategy.py` picks the runner; `app/mtr_runner.py`
and `app/scamper_runner.py` both produce the same `TraceResult`/`HopResult`
shape consumed by `backend_client.py`, so nothing downstream — the API,
schemas, ORM, or `tree_builder.py` — needs to know which tool ran).

The default, `icmp-paris`, runs scamper's Paris-traceroute-consistent trace
method instead of plain mtr. Plain ICMP mtr sends each probe with a fresh
identifier, so a router doing ECMP load-balancing can hash successive probes
onto different physical next-hops — observed in practice as phantom extra
branches and multi-IP nodes (large `hop_ips` lists) at ECMP points in the
merged tree, on top of the genuine same-hostname-different-IP cases
`tree_builder.py`'s hostname merge already handles. scamper's Paris methods
pin the flow identifier so every attempt in a run takes the same path;
`-q <SCAMPER_PROBE_COUNT> -Q` still sends multiple attempts per hop for
loss/RTT stats, matching mtr's `-c` behavior. `udp-paris`/`tcp`/`tcp-ack` are
available as alternative methods (`PROBE_METHOD`) for networks that
deprioritize ICMP; `mtr` itself remains selectable as a fallback.

Unlike mtr's `--json`, scamper's `-O json` output only contains an entry for
a `probe_ttl` that got at least one reply — `_parse_scamper_trace` walks
`1..hop_count` and synthesizes a timeout `HopResult` for any gap, so the
"real hop vs `*`" contract `tree_builder.py` depends on is preserved.

scamper's raw-socket + privilege-separation model (opens its socket as root,
then chroots to `/var/empty` and drops to an unprivileged user) needs
`SYS_CHROOT`/`SETGID`/`SETUID` in addition to `NET_RAW` under the
`cap_drop: ALL` prober container — confirmed empirically; `NET_RAW` alone
(sufficient for mtr) leaves scamper failing at startup.

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
