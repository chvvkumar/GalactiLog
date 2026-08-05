"""PHD2 guide-log storage: logs -> sessions -> frames / calibrations.

Four tables rather than one because the grains are genuinely different: a
file, a guiding run, a 0.5-second sample, and a calibration. Frames dominate
by volume (roughly 390k rows for a six-month corpus), so that table is kept
deliberately narrow and stores pixels only - arcsec is derived at read time
from the owning session's pixel scale, which means a corrected pixel scale
never requires rewriting frame rows.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Phd2Log(Base):
    """One row per guide-log file on disk.

    file_size/file_mtime mirror the images table's delta-detection columns so
    an unchanged log is skipped on every subsequent scan. A data-free file
    still gets a row (parse_status="empty", zero sessions) so it is not
    re-read on every scan forever.
    """

    __tablename__ = "phd2_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_mtime: Mapped[float | None] = mapped_column(Float, nullable=True)
    # "ok" | "empty" | "failed"
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    phd2_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    log_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calibration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parsed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Phd2Session(Base):
    """One guiding section (Guiding Begins .. Guiding Ends) with its aggregates.

    Sessions are stored raw and never merged at ingest: two PHD2 instances can
    run at once on two rigs with overlapping wall-clock and different pixel
    scales, so merging would silently mix incomparable data. Night-level
    rollups are frame-count weighted at query time instead.
    """

    __tablename__ = "phd2_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phd2_logs.id", ondelete="CASCADE"), nullable=False
    )
    run_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # PHD2 writes local wall-clock with no zone. The naive local value is kept
    # alongside the converted UTC one so a later timezone correction can be
    # applied without re-reading the file.
    started_at_local: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    session_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    equipment_profile: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telescope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pixel_scale_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    focal_length_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    guide_camera: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exposure_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    mount_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dec_guide_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    algo_ra: Mapped[str | None] = mapped_column(String(50), nullable=True)
    algo_dec: Mapped[str | None] = mapped_column(String(50), nullable=True)
    min_move_ra: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_move_dec: Mapped[float | None] = mapped_column(Float, nullable=True)
    aggression_ra: Mapped[float | None] = mapped_column(Float, nullable=True)
    ortho_error_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_cal_issue: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pier_side: Mapped[str | None] = mapped_column(String(10), nullable=True)
    alt_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    az_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    dec_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    hour_angle_hr: Mapped[float | None] = mapped_column(Float, nullable=True)

    frame_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    drop_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_drop_run: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unguided_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    rms_ra_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    rms_dec_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    rms_total_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    rms_ra_filtered_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    rms_dec_filtered_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    rms_total_filtered_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_ra_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_dec_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)

    snr_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    snr_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    star_mass_mean: Mapped[float | None] = mapped_column(Float, nullable=True)

    pulse_count_ra_west: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pulse_count_ra_east: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pulse_count_dec_north: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pulse_count_dec_south: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pulse_total_ms_ra: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    pulse_total_ms_dec: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    dither_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settle_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settle_median_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    # {reason string: count}
    star_lost_reasons: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # [{"type": ..., "t": ..., "detail": ...}] - the same shape the frames
    # endpoint returns, so no translation layer is needed on read.
    events: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Filled by the phase-3 insight detectors; nullable so phase 1 can leave
    # it alone without a second migration.
    insights: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_phd2_sessions_session_date", "session_date"),
        Index("ix_phd2_sessions_telescope_session_date", "telescope", "session_date"),
        Index("ix_phd2_sessions_started_at_utc", "started_at_utc"),
        Index("ix_phd2_sessions_log_id", "log_id"),
    )


class Phd2Frame(Base):
    """One guiding CSV row. Pixels only - arcsec is derived from the session.

    BIGSERIAL id rather than a composite key: frame numbers skip across DROP
    gaps and are not guaranteed unique inside a truncated section, so a
    natural key would make a malformed tail abort the whole file's ingest.
    """

    __tablename__ = "phd2_frames"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phd2_sessions.id", ondelete="CASCADE"), nullable=False
    )
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    time_offset: Mapped[float] = mapped_column(Float, nullable=False)
    dx: Mapped[float | None] = mapped_column(Float, nullable=True)
    dy: Mapped[float | None] = mapped_column(Float, nullable=True)
    ra_raw: Mapped[float | None] = mapped_column(Float, nullable=True)
    dec_raw: Mapped[float | None] = mapped_column(Float, nullable=True)
    ra_guide: Mapped[float | None] = mapped_column(Float, nullable=True)
    dec_guide: Mapped[float | None] = mapped_column(Float, nullable=True)
    ra_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ra_direction: Mapped[str] = mapped_column(String(2), nullable=False, default="")
    dec_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dec_direction: Mapped[str] = mapped_column(String(2), nullable=False, default="")
    star_mass: Mapped[float | None] = mapped_column(Float, nullable=True)
    snr: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dropped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_phd2_frames_session_frame", "session_id", "frame_index"),
        Index("ix_phd2_frames_session_time", "session_id", "time_offset"),
    )


class Phd2Calibration(Base):
    """One calibration block, with its per-step series stored as JSONB.

    Steps are a bounded, always-read-together series (tens of rows per
    calibration) that is only ever rendered as one plot, so a JSONB array
    beats a fifth table.
    """

    __tablename__ = "phd2_calibrations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phd2_logs.id", ondelete="CASCADE"), nullable=False
    )
    started_at_local: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    session_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    equipment_profile: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telescope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pixel_scale_arcsec: Mapped[float | None] = mapped_column(Float, nullable=True)
    focal_length_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    guide_camera: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mount_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ra_guide_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    dec_guide_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    dec_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    hour_angle_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    pier_side: Mapped[str | None] = mapped_column(String(10), nullable=True)
    alt_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    az_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    west_angle_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    west_rate_px_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    west_parity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    north_angle_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    north_rate_px_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    north_parity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        Index("ix_phd2_calibrations_log_id", "log_id"),
        Index("ix_phd2_calibrations_session_date", "session_date"),
        Index("ix_phd2_calibrations_started_at_utc", "started_at_utc"),
    )
