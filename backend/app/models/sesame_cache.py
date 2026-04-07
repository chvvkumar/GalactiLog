from datetime import datetime

from sqlalchemy import String, Float, DateTime, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SesameCache(Base):
    __tablename__ = "sesame_cache"

    query_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    main_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_aliases: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    ra: Mapped[float | None] = mapped_column(Float, nullable=True)
    dec: Mapped[float | None] = mapped_column(Float, nullable=True)
    object_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolver: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
