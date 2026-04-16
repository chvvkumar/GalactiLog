import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Mosaic(Base):
    __tablename__ = "mosaics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    rotation_angle: Mapped[float | None] = mapped_column(Float, nullable=True, server_default="0.0")
    pixel_coords: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    panels: Mapped[list["MosaicPanel"]] = relationship(back_populates="mosaic", cascade="all, delete-orphan")
