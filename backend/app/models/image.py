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

    # Panel membership: which mosaic panel (if any) this frame's OBJECT token
    # resolves to. panel_label is the parsed token (e.g. "Panel 3") in the
    # same format as MosaicPanel.panel_label, set independent of whether a
    # MosaicPanel row exists yet. panel_id links to an existing MosaicPanel
    # once one matches (resolved_target_id, panel_label), or via the simple
    # one-target-one-panel fallback when the OBJECT carries no panel token.
    panel_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    panel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mosaic_panels.id", ondelete="SET NULL"), nullable=True
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
    # FWHM parsed from FITS/XISF headers (FWHM/MEANFWHM keywords). Kept separate
    # from median_hfr because HFR and FWHM are different metrics on different
    # scales, and separate from the CSV-sourced `fwhm` column below.
    median_fwhm: Mapped[float | None] = mapped_column(Float, nullable=True)
    eccentricity: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Which of three non-comparable origins produced `eccentricity`:
    #   "header"      -- native ECCENTRICITY keyword
    #   "ellipticity" -- derived from ELLIPTICITY via e = sqrt(1 - (1 - E)^2)
    #   "csv"         -- N.I.N.A. Session Metadata CSV
    # Each application measures eccentricity by its own method, so values from
    # different sources are not interchangeable and must not be pooled blindly.
    # NULL means unknown: rows ingested before this column existed whose
    # provenance could not be recovered from raw_headers (see data migration
    # v14). No index -- three values plus NULL is too low-cardinality for a
    # btree to help, and nothing filters on it yet.
    eccentricity_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Altitude of the frame centre in degrees (OBJCTALT, else CENTALT).
    # Eccentricity is contaminated by atmospheric dispersion, which scales with
    # tan(zenith distance), so altitude is needed to read an eccentricity
    # fairly: the same rig measures a markedly rounder star field near zenith
    # than near the horizon. NULL when neither keyword is present; it is NOT
    # derived from RA/Dec + time + site.
    altitude_deg: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Plate scale in arcseconds per pixel, materialized at ingest from the
    # XPIXSZ/FOCALLEN headers via units.arcsec_per_pixel (206.265 * um / mm).
    # Stored as a column because deriving it per-row from raw_headers JSONB
    # (regex-guarded text casts, see units.sql_arcsec_per_pixel) is what made
    # cold /api/stats aggregations take tens of seconds. NULL when the headers
    # carry no usable pixel size or focal length.
    arcsec_per_pixel: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- CSV metrics (N.I.N.A. ImageMetaData) ---
    # Quality
    hfr_stdev: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Arcseconds. From NINA Session Metadata CSV (Hocus Focus). Never multiply
    # by plate scale.
    fwhm: Mapped[float | None] = mapped_column(Float, nullable=True)
    detected_stars: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Guiding
    guiding_rms_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    guiding_rms_ra_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    guiding_rms_dec_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Which measurement produced the three guiding_rms_* values above:
    #   "csv"  -- N.I.N.A. Session Metadata CSV, written at ingest
    #   "phd2" -- computed from the PHD2 guide log's raw sample stream over
    #             this frame's exposure interval (services/phd2_correlation)
    # NULL means unknown: rows written before this column existed, or rows
    # with no guiding data at all. The two sources are close but are not the
    # same measurement - N.I.N.A. reports what its guider integration saw,
    # PHD2's own numbers come off the 0.5 s sample series - so a frame table
    # has to be able to say which one it is showing. The CSV always wins:
    # correlation only ever writes rows where guiding_rms_arcsec is NULL.
    # No index -- two values plus NULL is too low-cardinality for a btree to
    # help, exactly as for eccentricity_source above.
    guiding_rms_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

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
    panel: Mapped["MosaicPanel | None"] = relationship(foreign_keys=[panel_id])

    __table_args__ = (
        Index("ix_images_capture_date", "capture_date"),
        Index("ix_images_panel_id", "panel_id"),
        Index("ix_images_target_panel_label", "resolved_target_id", "panel_label"),
        Index("ix_images_session_date", "session_date"),
        Index("ix_images_filter_used", "filter_used"),
        Index("ix_images_resolved_target_id", "resolved_target_id"),
        Index("ix_images_image_type", "image_type"),
        Index("ix_images_type_session_date", "image_type", "session_date"),
        Index("ix_images_raw_headers", "raw_headers", postgresql_using="gin"),
        Index("ix_images_telescope", "telescope"),
        Index("ix_images_camera", "camera"),
        Index("ix_images_median_hfr", "median_hfr"),
        Index("ix_images_fwhm", "fwhm"),
        Index("ix_images_eccentricity", "eccentricity"),
        Index("ix_images_detected_stars", "detected_stars"),
        Index("ix_images_guiding_rms_arcsec", "guiding_rms_arcsec"),
        Index("ix_images_focuser_temp", "focuser_temp"),
        Index("ix_images_ambient_temp", "ambient_temp"),
        Index("ix_images_humidity", "humidity"),
        Index("ix_images_airmass", "airmass"),
    )
