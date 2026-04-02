import uuid

from sqlalchemy import String, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class MosaicPanel(Base):
    __tablename__ = "mosaic_panels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mosaic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mosaics.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("targets.id"), nullable=False)
    panel_label: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    object_pattern: Mapped[str | None] = mapped_column(String(255), nullable=True)

    mosaic: Mapped["Mosaic"] = relationship(back_populates="panels")
    target: Mapped["Target"] = relationship()

    __table_args__ = (
        UniqueConstraint("mosaic_id", "target_id", "panel_label", name="uq_mosaic_panels_mosaic_target_label"),
    )
