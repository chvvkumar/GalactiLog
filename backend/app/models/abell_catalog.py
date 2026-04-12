from sqlalchemy import String, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AbellEntry(Base):
    __tablename__ = "abell_catalog"

    abell_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    ra: Mapped[float | None] = mapped_column(Float, nullable=True)
    dec: Mapped[float | None] = mapped_column(Float, nullable=True)
    richness_class: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_class: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bm_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    redshift: Mapped[float | None] = mapped_column(Float, nullable=True)
