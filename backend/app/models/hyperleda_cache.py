from datetime import datetime

from sqlalchemy import String, Float, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class HyperLEDACache(Base):
    __tablename__ = "hyperleda_cache"

    catalog_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    t_type: Mapped[float | None] = mapped_column(Float, nullable=True)
    inclination: Mapped[float | None] = mapped_column(Float, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
