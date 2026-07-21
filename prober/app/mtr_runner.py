import asyncio
import json
import logging
import socket
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache

from app.config import Settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _detect_default_gateway() -> str | None:
    """Best-effort detection of this container's own default-route gateway,
    memoized since it can't change during the container's lifetime. Reads
    /proc/net/route (Linux-only, fine since this always runs in a Linux
    container); returns None -- disabling the filter -- if that's not
    available or has no default route, rather than failing the probe.
    """
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                fields = line.split()
                if len(fields) < 3 or fields[1] != "00000000":
                    continue
                return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    except Exception:
        logger.warning("could not determine default gateway; not filtering any hop")
    return None


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


def _parse_mtr_json(raw: dict, gateway_ip: str | None = None) -> list[HopResult]:
    hubs = raw.get("report", {}).get("hubs", [])
    hops: list[HopResult] = []
    for hub in hubs:
        host = hub.get("host")
        is_timeout = host is None or host == "???"
        ip = None if is_timeout else str(host)
        if gateway_ip and ip == gateway_ip:
            # This container's own default-route gateway -- not a real hop
            # past this host, so it's dropped rather than stored. Hops are
            # renumbered sequentially below rather than trusting mtr's own
            # `count` field, so dropping one never leaves a gap.
            continue
        hops.append(
            HopResult(
                hop_number=len(hops) + 1,
                hop_ip=ip,
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
        gateway_ip = _detect_default_gateway() if settings.filter_gateway_hop else None
        hops = _parse_mtr_json(raw, gateway_ip)
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
