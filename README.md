# mtr-mapper

A self-hosted dashboard that continuously traces routes to a fleet of network
targets (hostnames or IPs) and renders them as a live-updating, merged
hierarchical tree — hops shared by many targets' paths (a common gateway, a
shared ISP router, etc.) collapse into a single node, so the map stays
readable even with hundreds of targets. Click any node for its current stats
and recent history.

## Services

- **`db`** — Postgres, source of truth for targets, target lists, and trace history.
- **`backend`** — FastAPI app: REST API, `/ws/tree` WebSocket push, server-side tree-merge computation, target-list URL sync, history retention/pruning, admin auth.
- **`prober`** — Standalone worker that runs Paris-consistent traces (`scamper`, or `mtr` as a fallback) against active targets on a self-throttling schedule (refresh cadence backs off automatically as the target count grows, so total probe traffic stays bounded) and reports results to `backend`.
- **`frontend`** — React SPA (served via nginx, which also reverse-proxies `/api` and `/ws` to `backend`).

See `docs/architecture.md` for the full design and `docs/ws-protocol.md` for the WebSocket message contract.

## Running it

```bash
cp .env.example .env
# edit .env: set ADMIN_PASSWORD, ADMIN_SESSION_SECRET, PROBER_API_TOKEN, POSTGRES_PASSWORD to real values

docker compose build
docker compose up -d db
docker compose run --rm backend alembic upgrade head
docker compose up -d
```

Then open http://localhost:8080 (default `FRONTEND_PORT`). Log into `/admin`
with `ADMIN_PASSWORD` to add targets or target-list URLs.

`docker-compose.override.yml` is applied automatically in this checkout and
adds hot-reload + exposed `db`/`backend` ports for local development; drop it
(`docker compose -f docker-compose.yml up`) for a production-style run.

### Sanity-checking the prober's raw-socket permissions

The default prober method, `scamper`-based `icmp-paris`, needs `CAP_NET_RAW`
plus `CAP_SYS_CHROOT`/`CAP_SETGID`/`CAP_SETUID` for its privilege-separation
step (opens a raw socket as root, then chroots and drops to an unprivileged
user) — all granted in `docker-compose.yml` without `--privileged`. Confirm
it actually works on your Docker setup:

```bash
docker compose exec prober scamper -O json -o - -I 'trace -P icmp-paris -q1 1.1.1.1'
```

If that fails on your platform, set `PROBE_METHOD=udp-paris` or `tcp` (see
`.env.example`) — TCP mode is the most likely to get through firewalls that
block/deprioritize ICMP — or fall back to `PROBE_METHOD=mtr`, which only
needs `CAP_NET_RAW`.

## Configuration

All tuning knobs are environment variables — see `.env.example` for the full
list and defaults, including probe concurrency/interval/packet-count, history
retention window, and severity (loss%) thresholds.
