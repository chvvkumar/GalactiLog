import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
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
    session_dates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Name+position hybrid detection metadata (migration 0010).
    # confidence: 'high' | 'low'; discovery_source: 'name' | 'position' | 'both'.
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    discovery_source: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # geometry: {panels: [{target_id,label,ra,dec}], pitches: [arcmin], fov_arcmin}
    geometry: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # flags: array of human-readable low-confidence reasons.
    flags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
