from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ArpEntry(Base):
    __tablename__ = "arp_catalog"

    arp_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    ngc_ic_ids: Mapped[str | None] = mapped_column(String(200), nullable=True)
    peculiarity_class: Mapped[str | None] = mapped_column(String(100), nullable=True)
    peculiarity_description: Mapped[str | None] = mapped_column(Text, nullable=True)
