from sqlalchemy import String, Float
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Herschel400Entry(Base):
    __tablename__ = "herschel400_catalog"

    ngc_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    object_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    constellation: Mapped[str | None] = mapped_column(String(5), nullable=True)
    magnitude: Mapped[float | None] = mapped_column(Float, nullable=True)
