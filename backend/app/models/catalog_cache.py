from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CatalogCache(Base):
    """Generic point-lookup cache for external catalog/name-resolution lookups.

    Replaces the five near-identical tables (simbad_cache, sesame_cache,
    vizier_cache, hyperleda_cache, gaia_cache) with one shape: a (source, key)
    composite primary key, a JSONB payload holding whatever fields that
    source's lookup returns (NULL for a negative-cache row), a negative flag,
    and a fetched_at timestamp. The five old tables still exist and are still
    written to until each service is ported (Phase 4, Task 3); this model is
    additive only.
    """

    __tablename__ = "catalog_cache"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    negative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
