from datetime import datetime

from sqlalchemy import String, Float, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class NEDCache(Base):
    __tablename__ = "ned_cache"

    catalog_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    ned_morphology: Mapped[str | None] = mapped_column(String(50), nullable=True)
    redshift: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_mpc: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
