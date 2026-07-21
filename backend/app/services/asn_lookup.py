"""ASN / AS-org lookup for public hop IPs, via Team Cymru's DNS whois service.

Two-stage DNS TXT lookup per IP (see https://team-cymru.com/community-services/ip-asn-mapping/):
  1. reverse-octet query against origin.asn.cymru.com -> "ASN | prefix | registry | allocated | cc"
  2. AS{asn}.asn.cymru.com -> "ASN | cc | registry | allocated | AS Name"

Results (including negative/failed lookups) are cached both in-process and in the
`ip_asn_info` table, keyed by IP, so repeated trace cycles for the same shared hop
IP don't re-query DNS every recompute. IPv4 only for now -- Cymru's IPv6 lookup uses
a different (nibble-reversed) query format that isn't implemented here.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from datetime import datetime, timedelta, timezone

import dns.asyncresolver
import dns.exception
from sqlalchemy import String, cast, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.asn import IpAsnInfo

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[int | None, str | None, datetime]] = {}
_lock = asyncio.Lock()

_LOOKUP_CONCURRENCY = 8


def _is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version != 4:
        # IPv6 ASN lookup uses a different Cymru query format -- not implemented yet.
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _parse_txt(answer) -> str:
    # dnspython TXT records may split long strings into multiple chunks.
    return b"".join(answer.strings).decode("ascii", errors="replace")


async def _cymru_lookup(ip: str, timeout: float) -> tuple[int | None, str | None]:
    resolver = dns.asyncresolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout
    try:
        origin_query = ".".join(reversed(ip.split("."))) + ".origin.asn.cymru.com"
        origin_answer = await asyncio.wait_for(
            resolver.resolve(origin_query, "TXT"), timeout=timeout
        )
        fields = _parse_txt(origin_answer[0]).split("|")
        asn = int(fields[0].strip().split(" ")[0])

        name_answer = await asyncio.wait_for(
            resolver.resolve(f"AS{asn}.asn.cymru.com", "TXT"), timeout=timeout
        )
        name_fields = _parse_txt(name_answer[0]).split("|")
        as_org = name_fields[-1].strip()
        return asn, as_org
    except Exception:
        return None, None


async def get_asn_map(
    session: AsyncSession, ips: set[str], settings: Settings
) -> dict[str, tuple[int | None, str | None]]:
    if not settings.asn_lookup_enabled:
        return {}

    public_ips = {ip for ip in ips if ip and _is_public(ip)}
    if not public_ips:
        return {}

    now = datetime.now(timezone.utc)
    ttl = timedelta(hours=settings.asn_cache_ttl_hours)
    result: dict[str, tuple[int | None, str | None]] = {}
    misses: set[str] = set()

    async with _lock:
        for ip in public_ips:
            cached = _cache.get(ip)
            if cached and now - cached[2] < ttl:
                result[ip] = (cached[0], cached[1])
            else:
                misses.add(ip)

    if misses:
        db_result = await session.execute(
            select(IpAsnInfo).where(cast(IpAsnInfo.ip, String).in_(misses))
        )
        fresh_rows = []
        for row in db_result.scalars().all():
            # asyncpg returns INET columns as ipaddress objects, not plain str.
            row_ip = str(row.ip)
            looked_up_at = row.looked_up_at
            if looked_up_at.tzinfo is None:
                looked_up_at = looked_up_at.replace(tzinfo=timezone.utc)
            if now - looked_up_at < ttl:
                result[row_ip] = (row.asn, row.as_org)
                misses.discard(row_ip)
                fresh_rows.append((row_ip, row.asn, row.as_org, looked_up_at))
        if fresh_rows:
            async with _lock:
                for ip, asn, as_org, looked_up_at in fresh_rows:
                    _cache[ip] = (asn, as_org, looked_up_at)

    if misses:
        semaphore = asyncio.Semaphore(_LOOKUP_CONCURRENCY)

        async def _bounded_lookup(ip: str) -> tuple[str, int | None, str | None]:
            async with semaphore:
                asn, as_org = await _cymru_lookup(ip, settings.asn_lookup_timeout_seconds)
                return ip, asn, as_org

        looked_up = await asyncio.gather(*(_bounded_lookup(ip) for ip in misses))

        async with _lock:
            for ip, asn, as_org in looked_up:
                result[ip] = (asn, as_org)
                _cache[ip] = (asn, as_org, now)

        stmt = insert(IpAsnInfo).values(
            [{"ip": ip, "asn": asn, "as_org": as_org, "looked_up_at": now} for ip, asn, as_org in looked_up]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[IpAsnInfo.ip],
            set_={
                "asn": stmt.excluded.asn,
                "as_org": stmt.excluded.as_org,
                "looked_up_at": stmt.excluded.looked_up_at,
            },
        )
        await session.execute(stmt)
        await session.commit()

    return result
