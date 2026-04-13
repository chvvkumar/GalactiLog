import uuid

from sqlalchemy import String, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TargetCatalogMembership(Base):
    __tablename__ = "target_catalog_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("targets.id"), nullable=False, index=True)
    catalog_name: Mapped[str] = mapped_column(String(30), nullable=False)
    catalog_number: Mapped[str] = mapped_column(String(20), nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("target_id", "catalog_name", name="uq_target_catalog"),
    )
