from datetime import datetime

from pydantic import BaseModel


class ProberTarget(BaseModel):
    id: int
    address: str


class HopResult(BaseModel):
    hop_number: int
    hop_ip: str | None = None
    hop_hostname: str | None = None
    is_timeout: bool = False
    sent: int | None = None
    loss_pct: float | None = None
    last_ms: float | None = None
    avg_ms: float | None = None
    best_ms: float | None = None
    worst_ms: float | None = None
    stddev_ms: float | None = None


class TraceResultSubmit(BaseModel):
    target_id: int
    started_at: datetime
    completed_at: datetime
    success: bool
    error_message: str | None = None
    raw_json: dict | None = None
    hops: list[HopResult] = []


class ProberStats(BaseModel):
    active_target_count: int
    achieved_avg_cycle_seconds: float | None
