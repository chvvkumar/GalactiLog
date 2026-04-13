from sqlalchemy import String, Float, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SACEntry(Base):
    __tablename__ = "sac_catalog"

    object_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    constellation: Mapped[str | None] = mapped_column(String(5), nullable=True)
    magnitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    size: Mapped[str | None] = mapped_column(String(30), nullable=True)
