from datetime import datetime

from pydantic import BaseModel, Field


class TargetListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1)
    fetch_interval_seconds: int | None = None


class TargetListUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    fetch_interval_seconds: int | None = None
    active: bool | None = None


class TargetListOut(BaseModel):
    id: int
    name: str
    url: str
    fetch_interval_seconds: int
    active: bool
    last_fetched_at: datetime | None
    last_fetch_status: str | None
    last_fetch_error: str | None
    last_fetch_target_count: int | None

    model_config = {"from_attributes": True}
