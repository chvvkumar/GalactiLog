import uuid
from datetime import date, datetime

from sqlalchemy import String, Float, Integer, BigInteger, Date, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Image(Base):
    __tablename__ = "images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    capture_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    session_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    resolved_target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("targets.id"), nullable=True
    )

    # Extracted structured metadata for fast filtering
    exposure_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    filter_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sensor_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    camera_gain: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Equipment identification
    telescope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    camera: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Quality metrics
    median_hfr: Mapped[float | None] = mapped_column(Float, nullable=True)
    eccentricity: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- CSV metrics (N.I.N.A. ImageMetaData) ---
    # Quality
    hfr_stdev: Mapped[float | None] = mapped_column(Float, nullable=True)
    fwhm: Mapped[float | None] = mapped_column(Float, nullable=True)
    detected_stars: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Guiding
    guiding_rms_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    guiding_rms_ra_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    guiding_rms_dec_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ADU
    adu_stdev: Mapped[float | None] = mapped_column(Float, nullable=True)
    adu_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    adu_median: Mapped[float | None] = mapped_column(Float, nullable=True)
    adu_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adu_max: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Focuser
    focuser_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    focuser_temp: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Mount
    rotator_position: Mapped[float | None] = mapped_column(Float, nullable=True)
    pier_side: Mapped[str | None] = mapped_column(String(10), nullable=True)
    airmass: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Weather
    ambient_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    dew_point: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    pressure: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_gust: Mapped[float | None] = mapped_column(Float, nullable=True)
    cloud_cover: Mapped[float | None] = mapped_column(Float, nullable=True)
    sky_quality: Mapped[float | None] = mapped_column(Float, nullable=True)

    # File system metadata for delta rescans (skip unchanged files)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_mtime: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Complete raw FITS headers as JSONB
    raw_headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)

    target: Mapped["Target | None"] = relationship(back_populates="images")

    __table_args__ = (
        Index("ix_images_capture_date", "capture_date"),
        Index("ix_images_session_date", "session_date"),
        Index("ix_images_filter_used", "filter_used"),
        Index("ix_images_resolved_target_id", "resolved_target_id"),
        Index("ix_images_image_type", "image_type"),
        Index("ix_images_raw_headers", "raw_headers", postgresql_using="gin"),
        Index("ix_images_telescope", "telescope"),
        Index("ix_images_camera", "camera"),
    )
