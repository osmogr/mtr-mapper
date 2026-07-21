"""ip asn info cache table

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ip_asn_info",
        sa.Column("ip", postgresql.INET(), primary_key=True),
        sa.Column("asn", sa.Integer(), nullable=True),
        sa.Column("as_org", sa.String(), nullable=True),
        sa.Column(
            "looked_up_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("ip_asn_info")
