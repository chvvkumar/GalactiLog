"""v2.0 baseline: full schema in one migration.

Replaces the fifteen historical migrations (0001-0015) that built up the
schema incrementally, most with defensive create_all-compatibility guards.
This single migration creates the complete current schema with no guards.

Keeps revision id "0015" (the old chain's head) with down_revision None, so:
  - installs that already upgraded through checkpoint v2.0 are stamped at
    0015 and are already at head -- this migration never runs for them.
  - fresh installs run this single migration and land on the same schema
    the old chain produced.
  - installs stamped at any revision this tree does not know about (i.e.
    pre-checkpoint installs) are refused by the entrypoint's upgrade gate
    before alembic ever runs.

Schema equivalence with the old 0001-0015 chain was verified by diffing
`pg_dump --schema-only` output of a database built by each path.

downgrade() is intentionally unimplemented: there is no prior baseline to
revert to.
"""
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, UUID

# revision identifiers, used by Alembic.
revision = "0015"
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

    # -- Extensions -----------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # -- Tables -----------------------------------------------------------------

    op.create_table(
        "targets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("primary_name", sa.String(255), unique=True, nullable=False),
        sa.Column("catalog_id", sa.String(100), nullable=True),
        sa.Column("catalog_id_normalized", sa.String(100), nullable=True),
        sa.Column("common_name", sa.String(255), nullable=True),
        sa.Column("aliases", ARRAY(sa.String), nullable=False, server_default="{}"),
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
        sa.Column("merged_into_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sac_description", sa.Text, nullable=True),
        sa.Column("sac_notes", sa.Text, nullable=True),
        sa.Column("reference_thumbnail_path", sa.String(1024), nullable=True),
        sa.Column("distance_pc", sa.Float, nullable=True),
        sa.Column("hubble_t_type", sa.Float, nullable=True),
        sa.Column("inclination", sa.Float, nullable=True),
        sa.Column("name_locked", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("user_defined", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.execute("CREATE INDEX ix_targets_aliases ON targets USING GIN (aliases)")
    op.execute("CREATE INDEX ix_targets_primary_name_trgm ON targets USING GIN (primary_name gin_trgm_ops)")
    op.execute("CREATE INDEX ix_targets_catalog_id_trgm ON targets USING GIN (catalog_id gin_trgm_ops)")
    op.execute("CREATE UNIQUE INDEX uq_targets_catalog_id_normalized ON targets (catalog_id_normalized)")
    op.execute("CREATE INDEX ix_targets_merged_into_id ON targets (merged_into_id)")
    op.execute("CREATE INDEX ix_targets_active ON targets (id) WHERE merged_into_id IS NULL")

    op.create_table(
        "images",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("file_path", sa.String(1024), unique=True, nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("capture_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_date", sa.Date, nullable=True),
        sa.Column("thumbnail_path", sa.String(1024), nullable=True),
        sa.Column("resolved_target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=True),
        sa.Column("exposure_time", sa.Float, nullable=True),
        sa.Column("filter_used", sa.String(50), nullable=True),
        sa.Column("sensor_temp", sa.Float, nullable=True),
        sa.Column("camera_gain", sa.Integer, nullable=True),
        sa.Column("image_type", sa.String(20), nullable=True),
        sa.Column("telescope", sa.String(255), nullable=True),
        sa.Column("camera", sa.String(255), nullable=True),
        # Quality metrics
        sa.Column("median_hfr", sa.Float, nullable=True),
        sa.Column("median_fwhm", sa.Float, nullable=True),
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
    op.create_index("ix_images_session_date", "images", ["session_date"])
    op.create_index("ix_images_filter_used", "images", ["filter_used"])
    op.create_index("ix_images_resolved_target_id", "images", ["resolved_target_id"])
    op.create_index("ix_images_image_type", "images", ["image_type"])
    op.execute("CREATE INDEX ix_images_raw_headers ON images USING GIN (raw_headers)")
    op.create_index("ix_images_telescope", "images", ["telescope"])
    op.create_index("ix_images_camera", "images", ["camera"])
    op.create_index("ix_images_median_hfr", "images", ["median_hfr"])
    op.create_index("ix_images_fwhm", "images", ["fwhm"])
    op.create_index("ix_images_eccentricity", "images", ["eccentricity"])
    op.create_index("ix_images_detected_stars", "images", ["detected_stars"])
    op.create_index("ix_images_guiding_rms_arcsec", "images", ["guiding_rms_arcsec"])
    op.create_index("ix_images_focuser_temp", "images", ["focuser_temp"])
    op.create_index("ix_images_ambient_temp", "images", ["ambient_temp"])
    op.create_index("ix_images_humidity", "images", ["humidity"])
    op.create_index("ix_images_airmass", "images", ["airmass"])
    op.create_index("ix_images_image_type_capture_date", "images", ["image_type", "capture_date"])
    op.create_index("ix_images_resolved_target_id_image_type", "images", ["resolved_target_id", "image_type"])
    op.create_index("ix_images_resolved_target_session", "images", ["resolved_target_id", "session_date"])
    op.create_index("ix_images_type_session_date", "images", ["image_type", "session_date"])
    op.execute("CREATE INDEX ix_images_object_name ON images ((raw_headers->>'OBJECT'))")
    op.execute("CREATE INDEX ix_images_object_name_trgm ON images USING GIN ((raw_headers->>'OBJECT') gin_trgm_ops)")
    op.execute("CREATE INDEX ix_images_raw_headers_object ON images ((raw_headers->>'OBJECT'))")

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("username", sa.String(150), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", ENUM("admin", "viewer", name="user_role"), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("family_id", UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("persistent", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])

    op.create_table(
        "user_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("general", JSONB, nullable=False, server_default="{}"),
        sa.Column("filters", JSONB, nullable=False, server_default="{}"),
        sa.Column("equipment", JSONB, nullable=False, server_default="{}"),
        sa.Column("dismissed_suggestions", JSONB, nullable=False, server_default="[]"),
        sa.Column("display", JSONB, nullable=False, server_default="{}"),
        sa.Column("graph", JSONB, nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    conn.execute(
        sa.text(
            "INSERT INTO user_settings (id, general, filters, equipment) "
            "VALUES (CAST(:id AS uuid), CAST(:general AS jsonb), "
            "CAST(:filters AS jsonb), CAST(:equipment AS jsonb))"
        ),
        {
            "id": SETTINGS_ROW_ID,
            "general": json.dumps(DEFAULT_GENERAL),
            "filters": json.dumps(DEFAULT_FILTERS),
            "equipment": json.dumps({"cameras": {}, "telescopes": {}}),
        },
    )

    op.create_table(
        "app_metadata",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", JSONB, nullable=False, server_default="{}"),
    )
    op.execute("INSERT INTO app_metadata (key, value) VALUES ('data_version', '13')")

    op.create_table(
        "merge_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("source_image_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("suggested_target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=True),
        sa.Column("similarity_score", sa.Float, nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason_text", sa.String(500), nullable=True),
    )

    op.create_table(
        "merge_manifests",
        # NB: no server-side gen_random_uuid() default on id -- the app
        # generates this id client-side, matching the original 0013 migration.
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("winner_id", UUID(as_uuid=True), sa.ForeignKey("targets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("loser_id", UUID(as_uuid=True), sa.ForeignKey("targets.id", ondelete="CASCADE"), nullable=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_merge_manifests_winner", "merge_manifests", ["winner_id"])
    op.create_index("ix_merge_manifests_loser", "merge_manifests", ["loser_id"])

    op.create_table(
        "simbad_cache",
        sa.Column("query_name", sa.String(255), primary_key=True),
        sa.Column("main_id", sa.String(255), nullable=True),
        sa.Column("raw_aliases", ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("ra", sa.Float, nullable=True),
        sa.Column("dec", sa.Float, nullable=True),
        sa.Column("object_type", sa.String(100), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "sesame_cache",
        sa.Column("query_name", sa.String(255), primary_key=True),
        sa.Column("main_id", sa.String(255), nullable=True),
        sa.Column("raw_aliases", ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("ra", sa.Float, nullable=True),
        sa.Column("dec", sa.Float, nullable=True),
        sa.Column("object_type", sa.String(100), nullable=True),
        sa.Column("resolver", sa.String(50), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "vizier_cache",
        sa.Column("catalog_id", sa.String(50), primary_key=True),
        sa.Column("vizier_catalog", sa.String(20), nullable=True),
        sa.Column("size_major", sa.Float, nullable=True),
        sa.Column("size_minor", sa.Float, nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "hyperleda_cache",
        sa.Column("catalog_id", sa.String(50), primary_key=True),
        sa.Column("t_type", sa.Float, nullable=True),
        sa.Column("inclination", sa.Float, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "gaia_cache",
        sa.Column("target_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("distance_pc", sa.Float, nullable=True),
        sa.Column("parallax_count", sa.Integer, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "sac_catalog",
        sa.Column("object_name", sa.String(50), primary_key=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("object_type", sa.String(20), nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("magnitude", sa.Float, nullable=True),
        sa.Column("size", sa.String(30), nullable=True),
    )

    op.create_table(
        "caldwell_catalog",
        sa.Column("catalog_id", sa.String(10), primary_key=True),
        sa.Column("ngc_ic_id", sa.String(20), nullable=True),
        sa.Column("object_type", sa.String(20), nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("common_name", sa.String(100), nullable=True),
    )

    op.create_table(
        "herschel400_catalog",
        sa.Column("ngc_id", sa.String(20), primary_key=True),
        sa.Column("object_type", sa.String(20), nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("magnitude", sa.Float, nullable=True),
    )

    op.create_table(
        "arp_catalog",
        sa.Column("arp_id", sa.String(10), primary_key=True),
        sa.Column("ngc_ic_ids", sa.String(200), nullable=True),
        sa.Column("peculiarity_class", sa.String(100), nullable=True),
        sa.Column("peculiarity_description", sa.Text, nullable=True),
    )

    op.create_table(
        "abell_catalog",
        sa.Column("abell_id", sa.String(20), primary_key=True),
        sa.Column("ra", sa.Float, nullable=True),
        sa.Column("dec", sa.Float, nullable=True),
        sa.Column("richness_class", sa.Integer, nullable=True),
        sa.Column("distance_class", sa.Integer, nullable=True),
        sa.Column("bm_type", sa.String(10), nullable=True),
        sa.Column("redshift", sa.Float, nullable=True),
    )

    op.create_table(
        "target_catalog_memberships",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=False),
        sa.Column("catalog_name", sa.String(30), nullable=False),
        sa.Column("catalog_number", sa.String(20), nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
        sa.UniqueConstraint("target_id", "catalog_name", name="uq_target_catalog"),
    )
    op.create_index("ix_target_catalog_memberships_target_id", "target_catalog_memberships", ["target_id"])
    op.create_index("ix_tcm_catalog_name", "target_catalog_memberships", ["catalog_name"])

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

    op.create_table(
        "site_dark_hours",
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("dark_hours", sa.Float, nullable=False),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
    )
    op.create_index("ix_site_dark_hours_lat_lon", "site_dark_hours", ["latitude", "longitude"])

    op.create_table(
        "session_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=False),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("target_id", "session_date", name="uq_session_notes_target_date"),
    )

    op.create_table(
        "mosaics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("rotation_angle", sa.Float, nullable=True, server_default="0.0"),
        sa.Column("pixel_coords", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("needs_review", sa.Boolean, nullable=False, server_default="false"),
    )

    op.create_table(
        "mosaic_panels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("mosaic_id", UUID(as_uuid=True), sa.ForeignKey("mosaics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=False),
        sa.Column("panel_label", sa.String(100), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("object_pattern", sa.String(255), nullable=True),
        sa.Column("grid_row", sa.Integer, nullable=True),
        sa.Column("grid_col", sa.Integer, nullable=True),
        sa.Column("rotation", sa.Integer, nullable=False, server_default="0"),
        sa.Column("flip_h", sa.Boolean, nullable=False, server_default="false"),
        sa.UniqueConstraint("mosaic_id", "target_id", "panel_label", name="uq_mosaic_panels_mosaic_target_label"),
    )

    op.create_table(
        "mosaic_panel_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("panel_id", UUID(as_uuid=True), sa.ForeignKey("mosaic_panels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="available"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("panel_id", "session_date", name="uq_mosaic_panel_sessions_panel_date"),
    )
    op.create_index("ix_mosaic_panel_sessions_panel_id", "mosaic_panel_sessions", ["panel_id"])
    op.create_index("ix_mosaic_panel_sessions_status", "mosaic_panel_sessions", ["status"])
    op.create_index("ix_mps_panel_status", "mosaic_panel_sessions", ["panel_id", "status"])

    op.create_table(
        "mosaic_suggestions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("suggested_name", sa.String(255), nullable=False),
        sa.Column("base_name", sa.String(255), nullable=True),
        sa.Column("target_ids", ARRAY(UUID(as_uuid=True)), nullable=False),
        sa.Column("panel_labels", ARRAY(sa.String), nullable=False),
        sa.Column("panel_patterns", ARRAY(sa.String), nullable=True),
        sa.Column("session_dates", JSONB, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("confidence", sa.String(10), nullable=True),
        sa.Column("discovery_source", sa.String(10), nullable=True),
        sa.Column("geometry", JSONB, nullable=True),
        sa.Column("flags", JSONB, nullable=True),
        sa.Column("dedup_signature", sa.String(512), nullable=True),
    )

    op.create_table(
        "custom_columns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False, unique=True),
        sa.Column("column_type", ENUM("boolean", "text", "dropdown", name="column_type_enum"), nullable=False),
        sa.Column("applies_to", ENUM("target", "session", "rig", "mosaic", name="applies_to_enum"), nullable=False),
        sa.Column("dropdown_options", sa.ARRAY(sa.String), nullable=True),
        sa.Column("display_order", sa.Integer, nullable=False, server_default=sa.text("0")),
        # NB: nullable at the DB level despite the model's nullable=False --
        # matches the original 0001 migration.
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "custom_column_values",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("column_id", UUID(as_uuid=True), sa.ForeignKey("custom_columns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id", ondelete="CASCADE"), nullable=True),
        sa.Column("mosaic_id", UUID(as_uuid=True), sa.ForeignKey("mosaics.id", ondelete="CASCADE"), nullable=True),
        sa.Column("session_date", sa.Date, nullable=True),
        sa.Column("rig_label", sa.String(255), nullable=True),
        sa.Column("value", sa.Text, nullable=False),
        # NB: nullable at the DB level despite the model's nullable=False --
        # matches the original 0001 migration.
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_custom_column_values_target", "custom_column_values", ["target_id"])
    op.create_index("ix_custom_column_values_target_id", "custom_column_values", ["target_id"])
    op.create_index("ix_custom_column_values_column", "custom_column_values", ["column_id"])
    op.create_index("ix_custom_column_values_mosaic", "custom_column_values", ["mosaic_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_custom_column_value "
        "ON custom_column_values ("
        "column_id, "
        "COALESCE(target_id, '00000000-0000-0000-0000-000000000000'), "
        "COALESCE(mosaic_id, '00000000-0000-0000-0000-000000000000'), "
        "COALESCE(session_date, '1970-01-01'), "
        "COALESCE(rig_label, '')"
        ")"
    )

    op.create_table(
        "filename_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("extracted_name", sa.String(255), nullable=True),
        sa.Column("suggested_target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=True),
        sa.Column("method", sa.String(50), nullable=False, server_default="none"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("file_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("file_paths", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("image_ids", ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "app_logs",
        sa.Column("id", sa.BigInteger, autoincrement=True, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("logger", sa.String(128), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("traceback", sa.Text, nullable=True),
    )
    op.create_index("ix_app_logs_timestamp", "app_logs", ["timestamp"])
    op.create_index("ix_app_logs_level_timestamp", "app_logs", ["level", "timestamp"])

    op.execute(
        """
        CREATE TABLE activity_events (
            id          bigserial PRIMARY KEY,
            timestamp   timestamptz NOT NULL DEFAULT now(),
            severity    varchar(16) NOT NULL,
            category    varchar(32) NOT NULL,
            event_type  varchar(64) NOT NULL,
            message     text NOT NULL,
            details     jsonb,
            target_id   uuid REFERENCES targets(id) ON DELETE SET NULL,
            actor       varchar(64),
            duration_ms integer,
            parent_id   bigint REFERENCES activity_events(id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX idx_activity_timestamp_desc ON activity_events (timestamp DESC)")
    op.execute("CREATE INDEX idx_activity_severity_ts ON activity_events (severity, timestamp DESC)")
    op.execute("CREATE INDEX idx_activity_category_ts ON activity_events (category, timestamp DESC)")
    op.execute("CREATE INDEX ix_activity_events_parent_id ON activity_events (parent_id)")


def downgrade() -> None:
    raise NotImplementedError("0015_v2_baseline is the checkpoint baseline; there is no prior revision to revert to.")
