import uuid

from datetime import datetime

from sqlalchemy import Float, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GaiaCache(Base):
    __tablename__ = "gaia_cache"

    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    distance_pc: Mapped[float | None] = mapped_column(Float, nullable=True)
    parallax_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
