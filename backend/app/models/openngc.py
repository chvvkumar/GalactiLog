from sqlalchemy import String, Float
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class OpenNGCEntry(Base):
    __tablename__ = "openngc_catalog"

    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ra: Mapped[float | None] = mapped_column(Float, nullable=True)
    dec: Mapped[float | None] = mapped_column(Float, nullable=True)
    constellation: Mapped[str | None] = mapped_column(String(5), nullable=True)
    major_axis: Mapped[float | None] = mapped_column(Float, nullable=True)
    minor_axis: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_angle: Mapped[float | None] = mapped_column(Float, nullable=True)
    b_mag: Mapped[float | None] = mapped_column(Float, nullable=True)
    v_mag: Mapped[float | None] = mapped_column(Float, nullable=True)
    surface_brightness: Mapped[float | None] = mapped_column(Float, nullable=True)
    common_names: Mapped[str | None] = mapped_column(String(500), nullable=True)
    messier: Mapped[str | None] = mapped_column(String(10), nullable=True)
