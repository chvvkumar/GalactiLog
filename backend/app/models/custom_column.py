import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String, Integer, DateTime, Date, Enum, ForeignKey, Index, Text, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ColumnType(str, enum.Enum):
    boolean = "boolean"
    text = "text"
    dropdown = "dropdown"


class AppliesTo(str, enum.Enum):
    target = "target"
    session = "session"
    rig = "rig"


class CustomColumn(Base):
    __tablename__ = "custom_columns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    column_type: Mapped[ColumnType] = mapped_column(Enum(ColumnType, name="column_type_enum"), nullable=False)
    applies_to: Mapped[AppliesTo] = mapped_column(Enum(AppliesTo, name="applies_to_enum"), nullable=False)
    dropdown_options: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    values: Mapped[list["CustomColumnValue"]] = relationship(
        back_populates="column", cascade="all, delete-orphan",
    )


class CustomColumnValue(Base):
    __tablename__ = "custom_column_values"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    column_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("custom_columns.id", ondelete="CASCADE"), nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("targets.id", ondelete="CASCADE"), nullable=False,
    )
    session_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    rig_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    column: Mapped["CustomColumn"] = relationship(back_populates="values")

    __table_args__ = (
        Index(
            "uq_custom_column_value",
            "column_id", "target_id",
            func.coalesce(session_date, "1970-01-01"),
            func.coalesce(rig_label, ""),
            unique=True,
        ),
        Index("ix_custom_column_values_target", "target_id"),
        Index("ix_custom_column_values_column", "column_id"),
    )
