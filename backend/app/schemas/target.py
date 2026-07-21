from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class TargetCreate(BaseModel):
    address: str = Field(min_length=1, max_length=255)
    display_name: str | None = None

    @field_validator("address")
    @classmethod
    def strip_address(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("address must not be blank")
        return v


class TargetUpdate(BaseModel):
    active: bool | None = None
    display_name: str | None = None


class TargetOut(BaseModel):
    id: int
    address: str
    display_name: str | None
    active: bool
    last_probed_at: datetime | None
    last_probe_success: bool | None
    sources: list[str]  # e.g. ["manual"], ["list:3"], or both

    model_config = {"from_attributes": True}


class HopHistoryPoint(BaseModel):
    run_started_at: datetime
    hop_number: int
    hop_ip: str | None
    hop_hostname: str | None
    is_timeout: bool
    loss_pct: float | None
    avg_ms: float | None
    best_ms: float | None
    worst_ms: float | None
    stddev_ms: float | None


class TargetHistory(BaseModel):
    target_id: int
    address: str
    points: list[HopHistoryPoint]
