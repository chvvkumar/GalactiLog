import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class MosaicPanelSession(Base):
    __tablename__ = "mosaic_panel_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    panel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mosaic_panels.id", ondelete="CASCADE"), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    panel: Mapped["MosaicPanel"] = relationship(back_populates="sessions")

    __table_args__ = (
        UniqueConstraint("panel_id", "session_date", name="uq_mosaic_panel_sessions_panel_date"),
    )
