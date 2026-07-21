"""Self-throttling probe scheduler.

A fixed-size pool of workers drains a min-heap of (eligible_at, target_id)
pairs. When a worker finishes probing a target, it re-enqueues that target
with eligible_at = now + PROBER_MIN_CYCLE_SECONDS. The achieved per-target
cycle time is therefore approximately
    max(PROBER_MIN_CYCLE_SECONDS, (active_targets / PROBER_CONCURRENCY) * avg_run_seconds)
which backs off automatically as the fleet grows -- total outbound probe
traffic is bounded by concurrency, not by how many targets are configured.
"""

import asyncio
import heapq
import logging
import time

from app.backend_client import BackendClient
from app.config import Settings
from app.mtr_runner import run_mtr

logger = logging.getLogger(__name__)

_IDLE_POLL_SECONDS = 0.5


class Scheduler:
    def __init__(self, settings: Settings, backend: BackendClient) -> None:
        self._settings = settings
        self._backend = backend
        self._lock = asyncio.Lock()
        self._heap: list[tuple[float, int]] = []  # (eligible_at_monotonic, target_id)
        self._targets: dict[int, str] = {}  # target_id -> address, current active set
        self._queued: set[int] = set()  # target_ids currently sitting in the heap

    async def _refresh_targets_once(self) -> None:
        remote = await self._backend.get_targets()
        remote_map = {t["id"]: t["address"] for t in remote}
        async with self._lock:
            new_ids = set(remote_map) - set(self._targets)
            removed_ids = set(self._targets) - set(remote_map)
            self._targets = remote_map
            for tid in removed_ids:
                self._queued.discard(tid)
            now = time.monotonic()
            for tid in new_ids:
                heapq.heappush(self._heap, (now, tid))
                self._queued.add(tid)
        if new_ids or removed_ids:
            logger.info(
                "target sync: +%d -%d (active=%d)", len(new_ids), len(removed_ids), len(remote_map)
            )

    async def _refresh_targets_loop(self) -> None:
        while True:
            try:
                await self._refresh_targets_once()
            except Exception:
                logger.exception("failed to refresh target list from backend")
            await asyncio.sleep(self._settings.prober_target_refresh_seconds)

    async def _next_ready(self) -> tuple[int, str] | None:
        async with self._lock:
            while self._heap:
                eligible_at, tid = self._heap[0]
                if tid not in self._targets:
                    heapq.heappop(self._heap)
                    self._queued.discard(tid)
                    continue
                if eligible_at > time.monotonic():
                    return None
                heapq.heappop(self._heap)
                self._queued.discard(tid)
                return tid, self._targets[tid]
            return None

    async def _reschedule(self, target_id: int) -> None:
        async with self._lock:
            if target_id in self._targets and target_id not in self._queued:
                eligible_at = time.monotonic() + self._settings.prober_min_cycle_seconds
                heapq.heappush(self._heap, (eligible_at, target_id))
                self._queued.add(target_id)

    async def _worker(self, worker_id: int) -> None:
        while True:
            item = await self._next_ready()
            if item is None:
                await asyncio.sleep(_IDLE_POLL_SECONDS)
                continue
            target_id, address = item
            result = await run_mtr(target_id, address, self._settings)
            try:
                await self._backend.submit_result(result)
            except Exception:
                logger.exception("failed submitting result for target %s (%s)", target_id, address)
            await self._reschedule(target_id)

    async def run(self) -> None:
        await self._refresh_targets_once()
        tasks = [asyncio.create_task(self._refresh_targets_loop())]
        tasks += [
            asyncio.create_task(self._worker(i)) for i in range(self._settings.prober_concurrency)
        ]
        await asyncio.gather(*tasks)
