from datetime import date

from sqlalchemy import Date, Float
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SiteDarkHours(Base):
    __tablename__ = "site_dark_hours"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    dark_hours: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
