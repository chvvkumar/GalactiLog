"""Create complete GalactiLog schema.

Single migration that creates every table, index, and seed row for a fresh
install.  Existing installs should ``alembic stamp 0001`` instead of running
this migration.
"""
import json
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SETTINGS_ROW_ID = "00000000-0000-4000-8000-000000000001"

DEFAULT_GENERAL = {
    "auto_scan_enabled": True,
    "auto_scan_interval": 240,
    "thumbnail_width": 800,
    "default_page_size": 50,
}

DEFAULT_FILTERS = {
    "Ha": {"color": "#e74c3c", "aliases": ["ha"]},
    "OIII": {"color": "#3498db", "aliases": ["Oiii", "O"]},
    "SII": {"color": "#f39c12", "aliases": ["Sii", "S"]},
    "L": {"color": "#ffffff", "aliases": []},
    "R": {"color": "#e74c3c", "aliases": []},
    "G": {"color": "#2ecc71", "aliases": []},
    "B": {"color": "#3498db", "aliases": []},
    "IR": {"color": "#9b59b6", "aliases": ["ir"]},
}


def upgrade() -> None:
    conn = op.get_bind()

    # -- Extensions -------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # -- Enums (create_type=False prevents duplicate creation in create_table)
    user_role = sa.Enum("admin", "viewer", name="user_role",
                        create_type=False)
    user_role.create(conn, checkfirst=True)

    column_type_enum = sa.Enum("boolean", "text", "dropdown",
                               name="column_type_enum", create_type=False)
    column_type_enum.create(conn, checkfirst=True)

    applies_to_enum = sa.Enum("target", "session", "rig",
                              name="applies_to_enum", create_type=False)
    applies_to_enum.create(conn, checkfirst=True)

    # -- targets ----------------------------------------------------------
    op.create_table(
        "targets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("primary_name", sa.String(255), unique=True, nullable=False),
        sa.Column("catalog_id", sa.String(100), nullable=True),
        sa.Column("common_name", sa.String(255), nullable=True),
        sa.Column("aliases", ARRAY(sa.String), nullable=False,
                  server_default="{}"),
        sa.Column("ra", sa.Float, nullable=True),
        sa.Column("dec", sa.Float, nullable=True),
        sa.Column("object_type", sa.String(100), nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("size_major", sa.Float, nullable=True),
        sa.Column("size_minor", sa.Float, nullable=True),
        sa.Column("position_angle", sa.Float, nullable=True),
        sa.Column("v_mag", sa.Float, nullable=True),
        sa.Column("surface_brightness", sa.Float, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("merged_into_id", UUID(as_uuid=True),
                  sa.ForeignKey("targets.id"), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_targets_aliases ON targets USING GIN (aliases)"
    )
    op.execute(
        "CREATE INDEX ix_targets_primary_name_trgm ON targets "
        "USING GIN (primary_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_targets_catalog_id_trgm ON targets "
        "USING GIN (catalog_id gin_trgm_ops)"
    )

    # -- images -----------------------------------------------------------
    op.create_table(
        "images",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("file_path", sa.String(1024), unique=True, nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("capture_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("thumbnail_path", sa.String(1024), nullable=True),
        sa.Column("resolved_target_id", UUID(as_uuid=True),
                  sa.ForeignKey("targets.id"), nullable=True),
        sa.Column("exposure_time", sa.Float, nullable=True),
        sa.Column("filter_used", sa.String(50), nullable=True),
        sa.Column("sensor_temp", sa.Float, nullable=True),
        sa.Column("camera_gain", sa.Integer, nullable=True),
        sa.Column("image_type", sa.String(20), nullable=True),
        sa.Column("telescope", sa.String(255), nullable=True),
        sa.Column("camera", sa.String(255), nullable=True),
        # Quality metrics
        sa.Column("median_hfr", sa.Float, nullable=True),
        sa.Column("eccentricity", sa.Float, nullable=True),
        sa.Column("hfr_stdev", sa.Float, nullable=True),
        sa.Column("fwhm", sa.Float, nullable=True),
        sa.Column("detected_stars", sa.Integer, nullable=True),
        # Guiding
        sa.Column("guiding_rms_arcsec", sa.Float, nullable=True),
        sa.Column("guiding_rms_ra_arcsec", sa.Float, nullable=True),
        sa.Column("guiding_rms_dec_arcsec", sa.Float, nullable=True),
        # ADU
        sa.Column("adu_stdev", sa.Float, nullable=True),
        sa.Column("adu_mean", sa.Float, nullable=True),
        sa.Column("adu_median", sa.Float, nullable=True),
        sa.Column("adu_min", sa.Integer, nullable=True),
        sa.Column("adu_max", sa.Integer, nullable=True),
        # Focuser
        sa.Column("focuser_position", sa.Integer, nullable=True),
        sa.Column("focuser_temp", sa.Float, nullable=True),
        # Mount
        sa.Column("rotator_position", sa.Float, nullable=True),
        sa.Column("pier_side", sa.String(10), nullable=True),
        sa.Column("airmass", sa.Float, nullable=True),
        # Weather
        sa.Column("ambient_temp", sa.Float, nullable=True),
        sa.Column("dew_point", sa.Float, nullable=True),
        sa.Column("humidity", sa.Float, nullable=True),
        sa.Column("pressure", sa.Float, nullable=True),
        sa.Column("wind_speed", sa.Float, nullable=True),
        sa.Column("wind_direction", sa.Float, nullable=True),
        sa.Column("wind_gust", sa.Float, nullable=True),
        sa.Column("cloud_cover", sa.Float, nullable=True),
        sa.Column("sky_quality", sa.Float, nullable=True),
        # File metadata
        sa.Column("file_size", sa.BigInteger, nullable=True),
        sa.Column("file_mtime", sa.Float, nullable=True),
        sa.Column("raw_headers", JSONB, nullable=True, server_default="{}"),
    )
    op.create_index("ix_images_capture_date", "images", ["capture_date"])
    op.create_index("ix_images_filter_used", "images", ["filter_used"])
    op.create_index("ix_images_resolved_target_id", "images",
                    ["resolved_target_id"])
    op.create_index("ix_images_image_type", "images", ["image_type"])
    op.execute(
        "CREATE INDEX ix_images_raw_headers ON images USING GIN (raw_headers)"
    )
    op.create_index("ix_images_telescope", "images", ["telescope"])
    op.create_index("ix_images_camera", "images", ["camera"])
    op.create_index("ix_images_median_hfr", "images", ["median_hfr"])
    op.create_index("ix_images_fwhm", "images", ["fwhm"])
    op.create_index("ix_images_eccentricity", "images", ["eccentricity"])
    op.create_index("ix_images_detected_stars", "images", ["detected_stars"])
    op.create_index("ix_images_guiding_rms_arcsec", "images",
                    ["guiding_rms_arcsec"])
    op.create_index("ix_images_adu_mean", "images", ["adu_mean"])
    op.create_index("ix_images_focuser_temp", "images", ["focuser_temp"])
    op.create_index("ix_images_ambient_temp", "images", ["ambient_temp"])
    op.create_index("ix_images_humidity", "images", ["humidity"])
    op.create_index("ix_images_airmass", "images", ["airmass"])

    # -- users ------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("username", sa.String(150), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False,
                  server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # -- refresh_tokens ---------------------------------------------------
    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("family_id", UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens",
                    ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens",
                    ["family_id"])

    # -- user_settings ----------------------------------------------------
    op.create_table(
        "user_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("general", JSONB, nullable=False, server_default="{}"),
        sa.Column("filters", JSONB, nullable=False, server_default="{}"),
        sa.Column("equipment", JSONB, nullable=False, server_default="{}"),
        sa.Column("dismissed_suggestions", JSONB, nullable=False,
                  server_default="[]"),
        sa.Column("display", JSONB, nullable=False, server_default="{}"),
        sa.Column("graph", JSONB, nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    # Seed default settings row
    conn.execute(sa.text(
        "INSERT INTO user_settings (id, general, filters, equipment) "
        "VALUES (CAST(:id AS uuid), CAST(:general AS jsonb), "
        "CAST(:filters AS jsonb), CAST(:equipment AS jsonb))"
    ), {
        "id": SETTINGS_ROW_ID,
        "general": json.dumps(DEFAULT_GENERAL),
        "filters": json.dumps(DEFAULT_FILTERS),
        "equipment": json.dumps({"cameras": {}, "telescopes": {}}),
    })

    # -- app_metadata -----------------------------------------------------
    op.create_table(
        "app_metadata",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", JSONB, nullable=False, server_default="{}"),
    )
    op.execute(
        "INSERT INTO app_metadata (key, value) VALUES ('data_version', '0')"
    )

    # -- merge_candidates -------------------------------------------------
    op.create_table(
        "merge_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("source_image_count", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("suggested_target_id", UUID(as_uuid=True),
                  sa.ForeignKey("targets.id"), nullable=False),
        sa.Column("similarity_score", sa.Float, nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    # -- simbad_cache -----------------------------------------------------
    op.create_table(
        "simbad_cache",
        sa.Column("query_name", sa.String(255), primary_key=True),
        sa.Column("main_id", sa.String(255), nullable=True),
        sa.Column("raw_aliases", ARRAY(sa.String), nullable=False,
                  server_default="{}"),
        sa.Column("ra", sa.Float, nullable=True),
        sa.Column("dec", sa.Float, nullable=True),
        sa.Column("object_type", sa.String(100), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )

    # -- sesame_cache -----------------------------------------------------
    op.create_table(
        "sesame_cache",
        sa.Column("query_name", sa.String(255), primary_key=True),
        sa.Column("main_id", sa.String(255), nullable=True),
        sa.Column("raw_aliases", ARRAY(sa.String), nullable=False,
                  server_default="{}"),
        sa.Column("ra", sa.Float, nullable=True),
        sa.Column("dec", sa.Float, nullable=True),
        sa.Column("object_type", sa.String(100), nullable=True),
        sa.Column("resolver", sa.String(50), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )

    # -- vizier_cache -----------------------------------------------------
    op.create_table(
        "vizier_cache",
        sa.Column("catalog_id", sa.String(50), primary_key=True),
        sa.Column("vizier_catalog", sa.String(20), nullable=True),
        sa.Column("size_major", sa.Float, nullable=True),
        sa.Column("size_minor", sa.Float, nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )

    # -- openngc_catalog --------------------------------------------------
    op.create_table(
        "openngc_catalog",
        sa.Column("name", sa.String(20), primary_key=True),
        sa.Column("type", sa.String(10), nullable=True),
        sa.Column("ra", sa.Float, nullable=True),
        sa.Column("dec", sa.Float, nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("major_axis", sa.Float, nullable=True),
        sa.Column("minor_axis", sa.Float, nullable=True),
        sa.Column("position_angle", sa.Float, nullable=True),
        sa.Column("b_mag", sa.Float, nullable=True),
        sa.Column("v_mag", sa.Float, nullable=True),
        sa.Column("surface_brightness", sa.Float, nullable=True),
        sa.Column("common_names", sa.String(500), nullable=True),
        sa.Column("messier", sa.String(10), nullable=True),
    )

    # -- site_dark_hours --------------------------------------------------
    op.create_table(
        "site_dark_hours",
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("dark_hours", sa.Float, nullable=False),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
    )

    # -- session_notes ----------------------------------------------------
    op.create_table(
        "session_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("target_id", UUID(as_uuid=True),
                  sa.ForeignKey("targets.id"), nullable=False),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("target_id", "session_date",
                            name="uq_session_notes_target_date"),
    )

    # -- mosaics ----------------------------------------------------------
    op.create_table(
        "mosaics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # -- mosaic_panels ----------------------------------------------------
    op.create_table(
        "mosaic_panels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mosaic_id", UUID(as_uuid=True),
                  sa.ForeignKey("mosaics.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("target_id", UUID(as_uuid=True),
                  sa.ForeignKey("targets.id"), nullable=False),
        sa.Column("panel_label", sa.String(100), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("object_pattern", sa.String(255), nullable=True),
        sa.UniqueConstraint("mosaic_id", "target_id", "panel_label",
                            name="uq_mosaic_panels_mosaic_target_label"),
    )

    # -- mosaic_suggestions -----------------------------------------------
    op.create_table(
        "mosaic_suggestions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("suggested_name", sa.String(255), nullable=False),
        sa.Column("target_ids", ARRAY(UUID(as_uuid=True)), nullable=False),
        sa.Column("panel_labels", ARRAY(sa.String), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # -- custom_columns ---------------------------------------------------
    op.create_table(
        "custom_columns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False, unique=True),
        sa.Column("column_type", column_type_enum, nullable=False),
        sa.Column("applies_to", applies_to_enum, nullable=False),
        sa.Column("dropdown_options", sa.ARRAY(sa.String), nullable=True),
        sa.Column("display_order", sa.Integer, nullable=False,
                  server_default=sa.text("0")),
        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    # -- custom_column_values ---------------------------------------------
    op.create_table(
        "custom_column_values",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("column_id", UUID(as_uuid=True),
                  sa.ForeignKey("custom_columns.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("target_id", UUID(as_uuid=True),
                  sa.ForeignKey("targets.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("session_date", sa.Date, nullable=True),
        sa.Column("rig_label", sa.String(255), nullable=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("updated_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_custom_column_values_target",
                    "custom_column_values", ["target_id"])
    op.create_index("ix_custom_column_values_column",
                    "custom_column_values", ["column_id"])
    op.execute(sa.text(
        "CREATE UNIQUE INDEX uq_custom_column_value "
        "ON custom_column_values ("
        "column_id, target_id, "
        "COALESCE(session_date, '1970-01-01'), "
        "COALESCE(rig_label, '')"
        ")"
    ))

    # -- filename_candidates ----------------------------------------------
    op.create_table(
        "filename_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("extracted_name", sa.String(255), nullable=True),
        sa.Column("suggested_target_id", UUID(as_uuid=True),
                  sa.ForeignKey("targets.id"), nullable=True),
        sa.Column("method", sa.String(50), nullable=False,
                  server_default="none"),
        sa.Column("confidence", sa.Float, nullable=False,
                  server_default="0.0"),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending"),
        sa.Column("file_count", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("file_paths", JSONB, nullable=False,
                  server_default="'[]'::jsonb"),
        sa.Column("image_ids", ARRAY(UUID(as_uuid=True)), nullable=False,
                  server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("filename_candidates")
    op.drop_table("custom_column_values")
    op.drop_table("custom_columns")
    op.drop_table("mosaic_suggestions")
    op.drop_table("mosaic_panels")
    op.drop_table("mosaics")
    op.drop_table("session_notes")
    op.drop_table("site_dark_hours")
    op.drop_table("openngc_catalog")
    op.drop_table("vizier_cache")
    op.drop_table("sesame_cache")
    op.drop_table("simbad_cache")
    op.drop_table("merge_candidates")
    op.drop_table("app_metadata")
    op.drop_table("user_settings")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.drop_table("images")
    op.drop_table("targets")
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="column_type_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="applies_to_enum").drop(op.get_bind(), checkfirst=True)
