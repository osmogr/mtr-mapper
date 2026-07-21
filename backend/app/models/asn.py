from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IpAsnInfo(Base):
    __tablename__ = "ip_asn_info"

    ip: Mapped[str] = mapped_column(INET, primary_key=True)
    asn: Mapped[int | None] = mapped_column(Integer)
    as_org: Mapped[str | None] = mapped_column(String)
    looked_up_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
