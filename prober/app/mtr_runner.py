import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class HopResult:
    hop_number: int
    hop_ip: str | None
    hop_hostname: str | None
    is_timeout: bool
    sent: int | None
    loss_pct: float | None
    last_ms: float | None
    avg_ms: float | None
    best_ms: float | None
    worst_ms: float | None
    stddev_ms: float | None


@dataclass
class TraceResult:
    target_id: int
    started_at: datetime
    completed_at: datetime
    success: bool
    error_message: str | None = None
    raw_json: dict | None = None
    hops: list[HopResult] = field(default_factory=list)


def _parse_mtr_json(raw: dict) -> list[HopResult]:
    hubs = raw.get("report", {}).get("hubs", [])
    hops: list[HopResult] = []
    for hub in hubs:
        host = hub.get("host")
        is_timeout = host is None or host == "???"
        hops.append(
            HopResult(
                hop_number=int(hub.get("count", len(hops) + 1)),
                hop_ip=None if is_timeout else str(host),
                hop_hostname=None,  # --no-dns: mtr never resolves; resolved lazily by the backend
                is_timeout=is_timeout,
                sent=hub.get("Snt"),
                loss_pct=hub.get("Loss%"),
                last_ms=hub.get("Last"),
                avg_ms=hub.get("Avg"),
                best_ms=hub.get("Best"),
                worst_ms=hub.get("Wrst"),
                stddev_ms=hub.get("StDev"),
            )
        )
    return hops


async def run_mtr(target_id: int, address: str, settings: Settings) -> TraceResult:
    started_at = datetime.now(timezone.utc)
    cmd = [
        "mtr",
        "--report",
        "--json",
        "--no-dns",
        "-c",
        str(settings.mtr_probe_count),
        "-i",
        str(settings.mtr_probe_interval),
        "-Z",
        str(settings.mtr_timeout_seconds),
        "-m",
        str(settings.mtr_max_hops),
        "-G",
        str(settings.mtr_gracetime),
        address,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=settings.prober_run_timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return TraceResult(
                target_id=target_id,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                success=False,
                error_message=f"mtr timed out after {settings.prober_run_timeout_seconds}s",
            )

        completed_at = datetime.now(timezone.utc)

        if proc.returncode != 0 and not stdout:
            return TraceResult(
                target_id=target_id,
                started_at=started_at,
                completed_at=completed_at,
                success=False,
                error_message=(stderr or b"").decode(errors="replace")[:2000] or "mtr exited non-zero",
            )

        raw = json.loads(stdout.decode(errors="replace"))
        hops = _parse_mtr_json(raw)
        return TraceResult(
            target_id=target_id,
            started_at=started_at,
            completed_at=completed_at,
            success=True,
            raw_json=raw,
            hops=hops,
        )
    except Exception as exc:  # noqa: BLE001 - report any failure as a failed run, keep the worker alive
        logger.warning("mtr run failed for target %s (%s): %s", target_id, address, exc)
        return TraceResult(
            target_id=target_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            success=False,
            error_message=str(exc)[:2000],
        )
