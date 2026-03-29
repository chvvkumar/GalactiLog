import uuid
from datetime import datetime

from sqlalchemy import String, Float, Index, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    primary_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    catalog_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    common_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    ra: Mapped[float | None] = mapped_column(Float, nullable=True)
    dec: Mapped[float | None] = mapped_column(Float, nullable=True)
    object_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("targets.id"), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    images: Mapped[list["Image"]] = relationship(back_populates="target")

    __table_args__ = (
        Index("ix_targets_aliases", "aliases", postgresql_using="gin"),
    )
