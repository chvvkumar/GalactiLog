import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MosaicSuggestion(Base):
    __tablename__ = "mosaic_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suggested_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    panel_labels: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    panel_patterns: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
