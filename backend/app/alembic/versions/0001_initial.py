"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "targets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_probed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_probe_success", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "targets_address_lower_uidx", "targets", [sa.text("lower(address)")], unique=True
    )

    op.create_table(
        "target_lists",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("fetch_interval_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fetch_status", sa.String(), nullable=True),
        sa.Column("last_fetch_error", sa.String(), nullable=True),
        sa.Column("last_fetch_target_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "target_sources",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "target_id",
            sa.BigInteger(),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column(
            "target_list_id",
            sa.BigInteger(),
            sa.ForeignKey("target_lists.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source_type in ('manual', 'list')", name="ck_target_source_type"),
        sa.UniqueConstraint(
            "target_id", "source_type", "target_list_id", name="uq_target_source"
        ),
    )

    op.create_table(
        "trace_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "target_id",
            sa.BigInteger(),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("trace_runs_target_started_idx", "trace_runs", ["target_id", "started_at"])

    op.create_table(
        "trace_hops",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "trace_run_id",
            sa.BigInteger(),
            sa.ForeignKey("trace_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.BigInteger(),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hop_number", sa.SmallInteger(), nullable=False),
        sa.Column("hop_ip", postgresql.INET(), nullable=True),
        sa.Column("hop_hostname", sa.String(), nullable=True),
        sa.Column("is_timeout", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sent", sa.SmallInteger(), nullable=True),
        sa.Column("loss_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("last_ms", sa.Numeric(8, 2), nullable=True),
        sa.Column("avg_ms", sa.Numeric(8, 2), nullable=True),
        sa.Column("best_ms", sa.Numeric(8, 2), nullable=True),
        sa.Column("worst_ms", sa.Numeric(8, 2), nullable=True),
        sa.Column("stddev_ms", sa.Numeric(8, 2), nullable=True),
    )
    op.create_index("trace_hops_target_time_idx", "trace_hops", ["target_id", "run_started_at"])
    op.create_index("trace_hops_run_idx", "trace_hops", ["trace_run_id"])


def downgrade() -> None:
    op.drop_table("trace_hops")
    op.drop_table("trace_runs")
    op.drop_table("target_sources")
    op.drop_table("target_lists")
    op.drop_index("targets_address_lower_uidx", table_name="targets")
    op.drop_table("targets")
