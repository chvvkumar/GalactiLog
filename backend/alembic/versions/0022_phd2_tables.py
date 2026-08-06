"""Create the four PHD2 guide-log tables.

GalactiLog already stores per-frame guiding RMS when N.I.N.A. wrote a sidecar
CSV, but that is one number per sub-exposure with no provenance and no time
series. PHD2's own guide log carries the full 0.5-second sample stream, the
per-session configuration that produced it, and the calibration geometry, so
it is worth its own storage rather than being folded into images.

Four tables, one per grain:
  phd2_logs          one row per file on disk (delta detection, parse status)
  phd2_sessions      one row per "Guiding Begins .. Guiding Ends" block
  phd2_frames        one row per CSV sample
  phd2_calibrations  one row per calibration block

phd2_frames is BIGSERIAL-keyed rather than keyed on (session_id, frame_index):
PHD2 frame numbers skip across star-loss gaps and are not guaranteed unique in
a file truncated mid-write, so a natural key would let one malformed tail
abort a whole night's ingest. The (session_id, frame_index) index is
non-unique for the same reason.

Frames store pixels only. Arcsec is derived at read time from the owning
session's pixel_scale_arcsec, because one file in the reference corpus carries
a wrong pixel scale in a single section header; storing arcsec would bake that
error into 390k rows and require a data migration to fix.

Indexes:
  phd2_logs.file_path unique       - the ingest lookup key, one row per file
  phd2_sessions.session_date       - the calendar/session-card lookup
  (telescope, session_date)        - the session-detail night+rig lookup
  started_at_utc                   - time-range queries and the phase-2
                                     per-image correlation window join
  log_id / calibration log_id      - cascade deletes and per-file re-parse
  (session_id, frame_index)        - ordered frame fetch for the guide graph
  (session_id, time_offset)        - time-window slicing of the same series

Schema only. There is nothing to backfill: rows appear when the scanner first
finds a guide log. Plain create_table with no existence guards, per the
project rule that guards need a specific stated reason.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "phd2_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=False, unique=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("file_mtime", sa.Float(), nullable=True),
        sa.Column("parse_status", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("phd2_version", sa.String(50), nullable=True),
        sa.Column("log_version", sa.String(20), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("session_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("calibration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    op.create_table(
        "phd2_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("log_id", UUID(as_uuid=True),
                  sa.ForeignKey("phd2_logs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("section_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at_local", sa.DateTime(timezone=False), nullable=False),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=False, server_default="0"),
        sa.Column("session_date", sa.Date(), nullable=True),
        sa.Column("equipment_profile", sa.String(255), nullable=True),
        sa.Column("telescope", sa.String(255), nullable=True),
        sa.Column("pixel_scale_arcsec", sa.Float(), nullable=True),
        sa.Column("focal_length_mm", sa.Float(), nullable=True),
        sa.Column("guide_camera", sa.String(255), nullable=True),
        sa.Column("exposure_ms", sa.Float(), nullable=True),
        sa.Column("mount_name", sa.String(255), nullable=True),
        sa.Column("dec_guide_mode", sa.String(20), nullable=True),
        sa.Column("algo_ra", sa.String(50), nullable=True),
        sa.Column("algo_dec", sa.String(50), nullable=True),
        sa.Column("min_move_ra", sa.Float(), nullable=True),
        sa.Column("min_move_dec", sa.Float(), nullable=True),
        sa.Column("aggression_ra", sa.Float(), nullable=True),
        sa.Column("ortho_error_deg", sa.Float(), nullable=True),
        sa.Column("last_cal_issue", sa.String(255), nullable=True),
        sa.Column("pier_side", sa.String(10), nullable=True),
        sa.Column("alt_deg", sa.Float(), nullable=True),
        sa.Column("az_deg", sa.Float(), nullable=True),
        sa.Column("dec_deg", sa.Float(), nullable=True),
        sa.Column("hour_angle_hr", sa.Float(), nullable=True),
        sa.Column("frame_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("drop_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_drop_run", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unguided_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rms_ra_arcsec", sa.Float(), nullable=True),
        sa.Column("rms_dec_arcsec", sa.Float(), nullable=True),
        sa.Column("rms_total_arcsec", sa.Float(), nullable=True),
        sa.Column("rms_ra_filtered_arcsec", sa.Float(), nullable=True),
        sa.Column("rms_dec_filtered_arcsec", sa.Float(), nullable=True),
        sa.Column("rms_total_filtered_arcsec", sa.Float(), nullable=True),
        sa.Column("peak_ra_arcsec", sa.Float(), nullable=True),
        sa.Column("peak_dec_arcsec", sa.Float(), nullable=True),
        sa.Column("snr_mean", sa.Float(), nullable=True),
        sa.Column("snr_min", sa.Float(), nullable=True),
        sa.Column("star_mass_mean", sa.Float(), nullable=True),
        sa.Column("pulse_count_ra_west", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pulse_count_ra_east", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pulse_count_dec_north", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pulse_count_dec_south", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pulse_total_ms_ra", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("pulse_total_ms_dec", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("dither_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("settle_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("settle_failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("settle_median_s", sa.Float(), nullable=True),
        sa.Column("star_lost_reasons", JSONB(), nullable=False, server_default="{}"),
        sa.Column("events", JSONB(), nullable=False, server_default="[]"),
        sa.Column("insights", JSONB(), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_phd2_sessions_session_date", "phd2_sessions", ["session_date"])
    op.create_index(
        "ix_phd2_sessions_telescope_session_date",
        "phd2_sessions", ["telescope", "session_date"],
    )
    op.create_index("ix_phd2_sessions_started_at_utc", "phd2_sessions", ["started_at_utc"])
    op.create_index("ix_phd2_sessions_log_id", "phd2_sessions", ["log_id"])

    op.create_table(
        "phd2_frames",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True, nullable=False),
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("phd2_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("time_offset", sa.Float(), nullable=False),
        sa.Column("dx", sa.Float(), nullable=True),
        sa.Column("dy", sa.Float(), nullable=True),
        sa.Column("ra_raw", sa.Float(), nullable=True),
        sa.Column("dec_raw", sa.Float(), nullable=True),
        sa.Column("ra_guide", sa.Float(), nullable=True),
        sa.Column("dec_guide", sa.Float(), nullable=True),
        sa.Column("ra_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ra_direction", sa.String(2), nullable=False, server_default=""),
        sa.Column("dec_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dec_direction", sa.String(2), nullable=False, server_default=""),
        sa.Column("star_mass", sa.Float(), nullable=True),
        sa.Column("snr", sa.Float(), nullable=True),
        sa.Column("error_code", sa.Integer(), nullable=True),
        sa.Column("dropped", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_phd2_frames_session_frame", "phd2_frames", ["session_id", "frame_index"])
    op.create_index("ix_phd2_frames_session_time", "phd2_frames", ["session_id", "time_offset"])

    op.create_table(
        "phd2_calibrations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("log_id", UUID(as_uuid=True),
                  sa.ForeignKey("phd2_logs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at_local", sa.DateTime(timezone=False), nullable=False),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=True),
        sa.Column("equipment_profile", sa.String(255), nullable=True),
        sa.Column("telescope", sa.String(255), nullable=True),
        sa.Column("pixel_scale_arcsec", sa.Float(), nullable=True),
        sa.Column("focal_length_mm", sa.Float(), nullable=True),
        sa.Column("guide_camera", sa.String(255), nullable=True),
        sa.Column("mount_name", sa.String(255), nullable=True),
        sa.Column("ra_guide_speed", sa.Float(), nullable=True),
        sa.Column("dec_guide_speed", sa.Float(), nullable=True),
        sa.Column("dec_deg", sa.Float(), nullable=True),
        sa.Column("hour_angle_hr", sa.Float(), nullable=True),
        sa.Column("pier_side", sa.String(10), nullable=True),
        sa.Column("alt_deg", sa.Float(), nullable=True),
        sa.Column("az_deg", sa.Float(), nullable=True),
        sa.Column("west_angle_deg", sa.Float(), nullable=True),
        sa.Column("west_rate_px_s", sa.Float(), nullable=True),
        sa.Column("west_parity", sa.String(10), nullable=True),
        sa.Column("north_angle_deg", sa.Float(), nullable=True),
        sa.Column("north_rate_px_s", sa.Float(), nullable=True),
        sa.Column("north_parity", sa.String(10), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("steps", JSONB(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_phd2_calibrations_log_id", "phd2_calibrations", ["log_id"])
    op.create_index("ix_phd2_calibrations_session_date", "phd2_calibrations", ["session_date"])
    op.create_index("ix_phd2_calibrations_started_at_utc", "phd2_calibrations", ["started_at_utc"])


def downgrade() -> None:
    op.drop_table("phd2_calibrations")
    op.drop_table("phd2_frames")
    op.drop_table("phd2_sessions")
    op.drop_table("phd2_logs")
