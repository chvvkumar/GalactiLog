from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CaldwellEntry(Base):
    __tablename__ = "caldwell_catalog"

    catalog_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    ngc_ic_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    object_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    constellation: Mapped[str | None] = mapped_column(String(5), nullable=True)
    common_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
