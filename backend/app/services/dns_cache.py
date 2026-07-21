import asyncio
import socket

_cache: dict[str, str | None] = {}
_lock = asyncio.Lock()


async def resolve_hostname(ip: str) -> str | None:
    """Lazily reverse-resolve an IP to a hostname, caching the result
    (including negative results) so repeated clicks don't repeat the lookup.
    """
    async with _lock:
        if ip in _cache:
            return _cache[ip]

    loop = asyncio.get_event_loop()
    try:
        hostname, _, _ = await asyncio.wait_for(
            loop.run_in_executor(None, socket.gethostbyaddr, ip), timeout=2.0
        )
    except Exception:
        hostname = None

    async with _lock:
        _cache[ip] = hostname
    return hostname
