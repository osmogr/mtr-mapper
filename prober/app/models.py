from dataclasses import dataclass, field
from datetime import datetime


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
