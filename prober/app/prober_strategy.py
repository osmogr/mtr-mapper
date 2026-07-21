from typing import Protocol

from app.config import Settings
from app.models import TraceResult

SCAMPER_METHODS = {"icmp-paris", "udp-paris", "tcp", "tcp-ack"}


class ProbeStrategy(Protocol):
    async def __call__(self, target_id: int, address: str, settings: Settings) -> TraceResult: ...


def get_strategy(settings: Settings) -> ProbeStrategy:
    if settings.probe_method == "mtr":
        from app.mtr_runner import run_mtr

        return run_mtr
    if settings.probe_method in SCAMPER_METHODS:
        from app.scamper_runner import run_scamper

        return run_scamper
    raise ValueError(f"unknown probe_method: {settings.probe_method!r}")
