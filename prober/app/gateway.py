import logging
import socket
import struct
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def detect_default_gateway() -> str | None:
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
