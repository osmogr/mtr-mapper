import asyncio
import ipaddress
import json
import logging
import socket
from datetime import datetime, timezone

from app.config import Settings
from app.gateway import detect_default_gateway
from app.models import HopResult, TraceResult

logger = logging.getLogger(__name__)


async def _resolve_address(address: str) -> str:
    # Unlike mtr, scamper's -I driver takes no hostname argument -- it's not
    # itself a resolver, so a bare hostname target (e.g. one configured by
    # address rather than IP) makes the whole `trace` sub-command fail with
    # no output at all. Resolve here first, preferring an IPv4 result to
    # match mtr's implicit default (no -4/-6 flag was ever passed to mtr).
    try:
        ipaddress.ip_address(address)
        return address
    except ValueError:
        pass

    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(address, None, family=socket.AF_UNSPEC, type=socket.SOCK_DGRAM)
    if not infos:
        raise socket.gaierror(f"no addresses found for {address}")
    for family in (socket.AF_INET, socket.AF_INET6):
        for info in infos:
            if info[0] == family:
                return info[4][0]
    return infos[0][4][0]


def _build_scamper_cmd(address: str, settings: Settings) -> list[str]:
    # The whole "trace ..." string is scamper's own mini command line, parsed
    # and tokenized by scamper itself (not a shell) -- run_scamper() rejects
    # any address containing whitespace before this is called, so a crafted
    # target address can't inject extra flags into it.
    trace_cmd = (
        f"trace -P {settings.probe_method} -q {settings.scamper_probe_count} -Q "
        f"-g {settings.scamper_gap_limit} -m {settings.mtr_max_hops} "
        f"-w {settings.scamper_probe_timeout_seconds} {address}"
    )
    return ["scamper", "-O", "json", "-o", "-", "-I", trace_cmd]


def _parse_scamper_trace(trace: dict, gateway_ip: str | None = None) -> list[HopResult]:
    # scamper's JSON (unlike mtr's) only contains an entry for a probe_ttl
    # that got at least one reply -- a ttl with zero replies across all
    # attempts is simply absent from `hops`, not represented by a
    # placeholder. hop_count is the highest ttl the run actually probed
    # (whether or not it got a reply), so every ttl in [1, hop_count] was
    # attempted and a gap must be synthesized as a timeout hop.
    groups: dict[int, list[dict]] = {}
    for probe in trace.get("hops", []):
        groups.setdefault(probe["probe_ttl"], []).append(probe)

    hop_count = trace.get("hop_count", 0)
    attempts = trace.get("attempts", 1)

    hops: list[HopResult] = []
    for ttl in range(1, hop_count + 1):
        group = groups.get(ttl)
        is_timeout = not group
        ip = None if is_timeout else group[-1]["addr"]

        if not is_timeout:
            addrs = {p["addr"] for p in group}
            if len(addrs) > 1:
                # True flow-consistent probing should keep every attempt at a
                # given ttl on the same path -- seeing more than one addr here
                # means the route itself changed mid-run, not per-packet ECMP
                # noise. Resolve deterministically rather than drop the hop.
                logger.warning(
                    "scamper hop ttl=%d saw multiple addrs %s within one run; using most recent",
                    ttl,
                    sorted(addrs),
                )

        if gateway_ip and ip == gateway_ip:
            # This container's own default-route gateway -- not a real hop
            # past this host. Hops are renumbered sequentially below rather
            # than trusting scamper's ttl positions, so dropping one never
            # leaves a gap.
            continue

        if group:
            rtts = [p["rtt"] for p in group if "rtt" in p]
            replies = len(group)
            loss_pct = 100.0 * (1 - replies / attempts) if attempts else 0.0
            last_ms = rtts[-1] if rtts else None
            avg_ms = sum(rtts) / len(rtts) if rtts else None
            best_ms = min(rtts) if rtts else None
            worst_ms = max(rtts) if rtts else None
            stddev_ms = (
                (sum((r - avg_ms) ** 2 for r in rtts) / len(rtts)) ** 0.5 if len(rtts) > 1 else 0.0
            )
        else:
            loss_pct = 100.0
            last_ms = avg_ms = best_ms = worst_ms = stddev_ms = None

        hops.append(
            HopResult(
                hop_number=len(hops) + 1,
                hop_ip=ip,
                hop_hostname=None,
                is_timeout=is_timeout,
                sent=attempts,
                loss_pct=loss_pct,
                last_ms=last_ms,
                avg_ms=avg_ms,
                best_ms=best_ms,
                worst_ms=worst_ms,
                stddev_ms=stddev_ms,
            )
        )
    return hops


def _extract_trace_record(stdout: bytes) -> dict | None:
    for line in stdout.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "trace":
            return obj
    return None


async def run_scamper(target_id: int, address: str, settings: Settings) -> TraceResult:
    started_at = datetime.now(timezone.utc)

    if not address or any(c.isspace() for c in address):
        return TraceResult(
            target_id=target_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            success=False,
            error_message="address must not contain whitespace",
        )

    try:
        resolved_address = await _resolve_address(address)
    except (socket.gaierror, OSError) as exc:
        return TraceResult(
            target_id=target_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            success=False,
            error_message=f"could not resolve {address}: {exc}"[:2000],
        )

    cmd = _build_scamper_cmd(resolved_address, settings)

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
                error_message=f"scamper timed out after {settings.prober_run_timeout_seconds}s",
            )

        completed_at = datetime.now(timezone.utc)

        if proc.returncode != 0 and not stdout:
            return TraceResult(
                target_id=target_id,
                started_at=started_at,
                completed_at=completed_at,
                success=False,
                error_message=(stderr or b"").decode(errors="replace")[:2000] or "scamper exited non-zero",
            )

        trace = _extract_trace_record(stdout)
        if trace is None:
            detail = (stderr or b"").decode(errors="replace")[:1000]
            return TraceResult(
                target_id=target_id,
                started_at=started_at,
                completed_at=completed_at,
                success=False,
                error_message="scamper produced no trace record" + (f": {detail}" if detail else ""),
            )

        gateway_ip = detect_default_gateway() if settings.filter_gateway_hop else None
        hops = _parse_scamper_trace(trace, gateway_ip)
        return TraceResult(
            target_id=target_id,
            started_at=started_at,
            completed_at=completed_at,
            success=True,
            raw_json=trace,
            hops=hops,
        )
    except Exception as exc:  # noqa: BLE001 - report any failure as a failed run, keep the worker alive
        logger.warning("scamper run failed for target %s (%s): %s", target_id, address, exc)
        return TraceResult(
            target_id=target_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            success=False,
            error_message=str(exc)[:2000],
        )
