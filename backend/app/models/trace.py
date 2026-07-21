from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TraceRun(Base):
    __tablename__ = "trace_runs"
    __table_args__ = (Index("trace_runs_target_started_idx", "target_id", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String)
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TraceHop(Base):
    __tablename__ = "trace_hops"
    __table_args__ = (
        Index("trace_hops_target_time_idx", "target_id", "run_started_at"),
        Index("trace_hops_run_idx", "trace_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trace_run_id: Mapped[int] = mapped_column(
        ForeignKey("trace_runs.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), nullable=False)
    run_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hop_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    hop_ip: Mapped[str | None] = mapped_column(INET)
    hop_hostname: Mapped[str | None] = mapped_column(String)
    is_timeout: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent: Mapped[int | None] = mapped_column(SmallInteger)
    loss_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    last_ms: Mapped[float | None] = mapped_column(Numeric(8, 2))
    avg_ms: Mapped[float | None] = mapped_column(Numeric(8, 2))
    best_ms: Mapped[float | None] = mapped_column(Numeric(8, 2))
    worst_ms: Mapped[float | None] = mapped_column(Numeric(8, 2))
    stddev_ms: Mapped[float | None] = mapped_column(Numeric(8, 2))
