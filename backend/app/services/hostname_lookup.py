"""Reverse-DNS (PTR) hostname lookup for hop IPs.

Mirrors `asn_lookup.py`'s shape: results (including negative/failed
lookups) are cached both in-process and in the `ip_hostname_info` table,
keyed by IP, so repeated trace cycles for the same hop IP don't re-query
DNS every recompute. Unlike ASN lookup, this isn't restricted to public
IPv4 -- PTR records exist for private/CGNAT space too (most useful for
the first hop, a home router), and PTR lookups work the same way for
IPv6, so there's no address-class gate here.

This has to run *before* `tree_builder.build_tree`, not lazily after --
the resulting `{ip: hostname}` map is what lets two different IPs at the
same trie position collapse into one node when they share a hostname.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import dns.asyncresolver
import dns.exception

from sqlalchemy import String, cast, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.hostname import IpHostnameInfo

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[str | None, datetime]] = {}
_lock = asyncio.Lock()

_LOOKUP_CONCURRENCY = 8


async def _ptr_lookup(ip: str, timeout: float) -> str | None:
    resolver = dns.asyncresolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout
    try:
        answer = await asyncio.wait_for(resolver.resolve_address(ip), timeout=timeout)
        return str(answer[0].target).rstrip(".")
    except Exception:
        return None


async def get_hostname_map(
    session: AsyncSession, ips: set[str], settings: Settings
) -> dict[str, str | None]:
    if not settings.hostname_lookup_enabled:
        return {}

    ips = {ip for ip in ips if ip}
    if not ips:
        return {}

    now = datetime.now(timezone.utc)
    ttl = timedelta(hours=settings.hostname_cache_ttl_hours)
    result: dict[str, str | None] = {}
    misses: set[str] = set()

    async with _lock:
        for ip in ips:
            cached = _cache.get(ip)
            if cached and now - cached[1] < ttl:
                result[ip] = cached[0]
            else:
                misses.add(ip)

    if misses:
        db_result = await session.execute(
            select(IpHostnameInfo).where(cast(IpHostnameInfo.ip, String).in_(misses))
        )
        fresh_rows = []
        for row in db_result.scalars().all():
            # asyncpg returns INET columns as ipaddress objects, not plain str.
            row_ip = str(row.ip)
            looked_up_at = row.looked_up_at
            if looked_up_at.tzinfo is None:
                looked_up_at = looked_up_at.replace(tzinfo=timezone.utc)
            if now - looked_up_at < ttl:
                result[row_ip] = row.hostname
                misses.discard(row_ip)
                fresh_rows.append((row_ip, row.hostname, looked_up_at))
        if fresh_rows:
            async with _lock:
                for ip, hostname, looked_up_at in fresh_rows:
                    _cache[ip] = (hostname, looked_up_at)

    if misses:
        semaphore = asyncio.Semaphore(_LOOKUP_CONCURRENCY)

        async def _bounded_lookup(ip: str) -> tuple[str, str | None]:
            async with semaphore:
                hostname = await _ptr_lookup(ip, settings.hostname_lookup_timeout_seconds)
                return ip, hostname

        looked_up = await asyncio.gather(*(_bounded_lookup(ip) for ip in misses))

        async with _lock:
            for ip, hostname in looked_up:
                result[ip] = hostname
                _cache[ip] = (hostname, now)

        stmt = insert(IpHostnameInfo).values(
            [{"ip": ip, "hostname": hostname, "looked_up_at": now} for ip, hostname in looked_up]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[IpHostnameInfo.ip],
            set_={
                "hostname": stmt.excluded.hostname,
                "looked_up_at": stmt.excluded.looked_up_at,
            },
        )
        await session.execute(stmt)
        await session.commit()

    return result
