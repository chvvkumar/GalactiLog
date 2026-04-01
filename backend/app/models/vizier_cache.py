from datetime import datetime

from sqlalchemy import String, Float, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class VizierCache(Base):
    __tablename__ = "vizier_cache"

    catalog_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    vizier_catalog: Mapped[str | None] = mapped_column(String(20), nullable=True)
    size_major: Mapped[float | None] = mapped_column(Float, nullable=True)
    size_minor: Mapped[float | None] = mapped_column(Float, nullable=True)
    constellation: Mapped[str | None] = mapped_column(String(5), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
