"""Consolidated schema evolution: mosaic layout, catalogs, activity, health.

Combines migrations 0002-0015 into a single step. All operations use
defensive guards (IF NOT EXISTS, column-existence checks) per project
convention, making this safe for databases bootstrapped with create_all.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text, inspect as sa_inspect
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    inspector = sa_inspect(op.get_bind())
    return column in [c["name"] for c in inspector.get_columns(table)]


def _table_exists(table: str) -> bool:
    inspector = sa_inspect(op.get_bind())
    return table in inspector.get_table_names()


def _add_col(table: str, col: sa.Column) -> None:
    if not _column_exists(table, col.name):
        op.add_column(table, col)


def upgrade() -> None:
    # -- Extensions -----------------------------------------------------------
    op.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

    # -- Columns on existing tables -------------------------------------------

    # mosaic_panels: manual grid layout
    _add_col("mosaic_panels", sa.Column("grid_row", sa.Integer(), nullable=True))
    _add_col("mosaic_panels", sa.Column("grid_col", sa.Integer(), nullable=True))
    _add_col("mosaic_panels", sa.Column("rotation", sa.Integer(), nullable=False, server_default="0"))
    _add_col("mosaic_panels", sa.Column("flip_h", sa.Boolean(), nullable=False, server_default="false"))

    # refresh_tokens: remember-me persistence
    _add_col("refresh_tokens", sa.Column("persistent", sa.Boolean(), nullable=False, server_default=text("false")))

    # mosaic_suggestions: pre-computed patterns and session dates
    _add_col("mosaic_suggestions", sa.Column("base_name", sa.String(255), nullable=True))
    _add_col("mosaic_suggestions", sa.Column("panel_patterns", ARRAY(sa.String), nullable=True))
    _add_col("mosaic_suggestions", sa.Column("session_dates", JSONB, nullable=True))

    # images: imaging-night session grouping
    _add_col("images", sa.Column("session_date", sa.Date(), nullable=True))

    # mosaics: canvas arranger and review tracking
    _add_col("mosaics", sa.Column("rotation_angle", sa.Float(), nullable=True, server_default="0.0"))
    _add_col("mosaics", sa.Column("pixel_coords", sa.Boolean(), nullable=False, server_default="false"))
    _add_col("mosaics", sa.Column("needs_review", sa.Boolean(), nullable=False, server_default="false"))

    # targets: catalog enrichment and health
    _add_col("targets", sa.Column("sac_description", sa.Text(), nullable=True))
    _add_col("targets", sa.Column("sac_notes", sa.Text(), nullable=True))
    _add_col("targets", sa.Column("reference_thumbnail_path", sa.String(1024), nullable=True))
    _add_col("targets", sa.Column("distance_pc", sa.Float(), nullable=True))
    _add_col("targets", sa.Column("name_locked", sa.Boolean(), nullable=False, server_default="false"))

    # merge_candidates: human-readable reason and nullable target
    _add_col("merge_candidates", sa.Column("reason_text", sa.String(500), nullable=True))
    op.alter_column("merge_candidates", "suggested_target_id", nullable=True)

    # -- New tables: catalog enrichment ---------------------------------------

    if not _table_exists("gaia_cache"):
        op.create_table(
            "gaia_cache",
            sa.Column("target_id", UUID(as_uuid=True), primary_key=True),
            sa.Column("distance_pc", sa.Float, nullable=True),
            sa.Column("parallax_count", sa.Integer, nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _table_exists("sac_catalog"):
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

    if not _table_exists("caldwell_catalog"):
        op.create_table(
            "caldwell_catalog",
            sa.Column("catalog_id", sa.String(10), primary_key=True),
            sa.Column("ngc_ic_id", sa.String(20), nullable=True),
            sa.Column("object_type", sa.String(20), nullable=True),
            sa.Column("constellation", sa.String(5), nullable=True),
            sa.Column("common_name", sa.String(100), nullable=True),
        )

    if not _table_exists("herschel400_catalog"):
        op.create_table(
            "herschel400_catalog",
            sa.Column("ngc_id", sa.String(20), primary_key=True),
            sa.Column("object_type", sa.String(20), nullable=True),
            sa.Column("constellation", sa.String(5), nullable=True),
            sa.Column("magnitude", sa.Float, nullable=True),
        )

    if not _table_exists("arp_catalog"):
        op.create_table(
            "arp_catalog",
            sa.Column("arp_id", sa.String(10), primary_key=True),
            sa.Column("ngc_ic_ids", sa.String(200), nullable=True),
            sa.Column("peculiarity_class", sa.String(100), nullable=True),
            sa.Column("peculiarity_description", sa.Text, nullable=True),
        )

    if not _table_exists("abell_catalog"):
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

    if not _table_exists("target_catalog_memberships"):
        op.create_table(
            "target_catalog_memberships",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=False, index=True),
            sa.Column("catalog_name", sa.String(30), nullable=False),
            sa.Column("catalog_number", sa.String(20), nullable=False),
            sa.Column("metadata", JSONB, nullable=True),
            sa.UniqueConstraint("target_id", "catalog_name", name="uq_target_catalog"),
        )

    # -- New table: activity events -------------------------------------------

    if not _table_exists("activity_events"):
        op.execute(text("""
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
                duration_ms integer
            )
        """))

    # -- New table: mosaic session membership ----------------------------------

    if not _table_exists("mosaic_panel_sessions"):
        op.create_table(
            "mosaic_panel_sessions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
            sa.Column("panel_id", UUID(as_uuid=True), sa.ForeignKey("mosaic_panels.id", ondelete="CASCADE"), nullable=False),
            sa.Column("session_date", sa.Date, nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="available"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("panel_id", "session_date", name="uq_mosaic_panel_sessions_panel_date"),
        )

    # -- Indexes (all IF NOT EXISTS) ------------------------------------------

    for stmt in [
        "CREATE INDEX IF NOT EXISTS ix_site_dark_hours_lat_lon ON site_dark_hours (latitude, longitude)",
        "CREATE INDEX IF NOT EXISTS ix_targets_merged_into_id ON targets (merged_into_id)",
        "CREATE INDEX IF NOT EXISTS ix_targets_active ON targets (id) WHERE merged_into_id IS NULL",
        "CREATE INDEX IF NOT EXISTS ix_images_object_name ON images ((raw_headers->>'OBJECT'))",
        "CREATE INDEX IF NOT EXISTS ix_images_object_name_trgm ON images USING gin ((raw_headers->>'OBJECT') gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS ix_images_image_type_capture_date ON images (image_type, capture_date)",
        "CREATE INDEX IF NOT EXISTS ix_images_resolved_target_id_image_type ON images (resolved_target_id, image_type)",
        "CREATE INDEX IF NOT EXISTS ix_images_session_date ON images (session_date)",
        "CREATE INDEX IF NOT EXISTS ix_images_resolved_target_session ON images (resolved_target_id, session_date)",
        "CREATE INDEX IF NOT EXISTS ix_custom_column_values_target_id ON custom_column_values (target_id)",
        "CREATE INDEX IF NOT EXISTS idx_activity_timestamp_desc ON activity_events (timestamp DESC)",
        "CREATE INDEX IF NOT EXISTS idx_activity_severity_ts ON activity_events (severity, timestamp DESC)",
        "CREATE INDEX IF NOT EXISTS idx_activity_category_ts ON activity_events (category, timestamp DESC)",
        "CREATE INDEX IF NOT EXISTS idx_activity_target ON activity_events (target_id) WHERE target_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_mosaic_panel_sessions_panel_id ON mosaic_panel_sessions (panel_id)",
        "CREATE INDEX IF NOT EXISTS ix_mosaic_panel_sessions_status ON mosaic_panel_sessions (status)",
    ]:
        op.execute(text(stmt))

    # -- Data migration: seed mosaic panel session records --------------------
    conn = op.get_bind()
    panels = conn.execute(text(
        "SELECT mp.id AS panel_id, mp.target_id, mp.object_pattern "
        "FROM mosaic_panels mp JOIN mosaics m ON mp.mosaic_id = m.id"
    )).fetchall()

    for panel in panels:
        if panel.object_pattern:
            dates = conn.execute(text(
                "SELECT DISTINCT session_date FROM images "
                "WHERE resolved_target_id = :tid AND image_type = 'LIGHT' "
                "AND raw_headers->>'OBJECT' ILIKE :pat AND session_date IS NOT NULL"
            ), {"tid": panel.target_id, "pat": panel.object_pattern}).fetchall()
        else:
            dates = conn.execute(text(
                "SELECT DISTINCT session_date FROM images "
                "WHERE resolved_target_id = :tid AND image_type = 'LIGHT' "
                "AND session_date IS NOT NULL"
            ), {"tid": panel.target_id}).fetchall()

        for row in dates:
            conn.execute(text(
                "INSERT INTO mosaic_panel_sessions (id, panel_id, session_date, status) "
                "VALUES (gen_random_uuid(), :panel_id, :session_date, 'available') "
                "ON CONFLICT (panel_id, session_date) DO NOTHING"
            ), {"panel_id": panel.panel_id, "session_date": row.session_date})

    conn.execute(text("UPDATE mosaics SET needs_review = true"))

    # -- Activity events: parent_id for hierarchical grouping (was 0003) -----

    if not _column_exists("activity_events", "parent_id"):
        op.add_column(
            "activity_events",
            sa.Column(
                "parent_id",
                sa.BigInteger(),
                sa.ForeignKey("activity_events.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_activity_events_parent_id "
        "ON activity_events (parent_id)"
    ))

    # -- Custom columns: mosaic support (was 0004) ----------------------------

    op.alter_column("custom_column_values", "target_id", nullable=True)

    op.execute(text("ALTER TYPE applies_to_enum ADD VALUE IF NOT EXISTS 'mosaic'"))

    _add_col(
        "custom_column_values",
        sa.Column(
            "mosaic_id",
            UUID(as_uuid=True),
            sa.ForeignKey("mosaics.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_custom_column_values_mosaic "
        "ON custom_column_values (mosaic_id)"
    ))

    # Rebuild unique constraint to include mosaic_id
    try:
        op.drop_index("uq_custom_column_value", table_name="custom_column_values")
    except Exception:
        pass  # index may not exist yet on fresh installs
    op.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_custom_column_value
        ON custom_column_values (
            column_id,
            COALESCE(target_id, '00000000-0000-0000-0000-000000000000'),
            COALESCE(mosaic_id, '00000000-0000-0000-0000-000000000000'),
            COALESCE(session_date, '1970-01-01'),
            COALESCE(rig_label, '')
        )
    """))


def downgrade() -> None:
    # -- Undo mosaic custom columns (was 0004) --------------------------------
    op.drop_index("uq_custom_column_value", table_name="custom_column_values")
    op.execute(text("""
        CREATE UNIQUE INDEX uq_custom_column_value
        ON custom_column_values (
            column_id, target_id,
            COALESCE(session_date, '1970-01-01'),
            COALESCE(rig_label, '')
        )
    """))
    op.execute(text("DROP INDEX IF EXISTS ix_custom_column_values_mosaic"))
    if _column_exists("custom_column_values", "mosaic_id"):
        op.drop_column("custom_column_values", "mosaic_id")
    op.alter_column("custom_column_values", "target_id", nullable=False)

    # -- Undo activity parent_id (was 0003) -----------------------------------
    op.execute(text("DROP INDEX IF EXISTS ix_activity_events_parent_id"))
    if _column_exists("activity_events", "parent_id"):
        op.drop_column("activity_events", "parent_id")

    op.execute(text("DROP TABLE IF EXISTS mosaic_panel_sessions"))
    op.execute(text("DROP TABLE IF EXISTS target_catalog_memberships"))
    op.execute(text("DROP TABLE IF EXISTS activity_events"))
    op.execute(text("DROP TABLE IF EXISTS abell_catalog"))
    op.execute(text("DROP TABLE IF EXISTS arp_catalog"))
    op.execute(text("DROP TABLE IF EXISTS herschel400_catalog"))
    op.execute(text("DROP TABLE IF EXISTS caldwell_catalog"))
    op.execute(text("DROP TABLE IF EXISTS sac_catalog"))
    op.execute(text("DROP TABLE IF EXISTS gaia_cache"))

    for idx in [
        "ix_mosaic_panel_sessions_status",
        "ix_mosaic_panel_sessions_panel_id",
        "idx_activity_target",
        "idx_activity_category_ts",
        "idx_activity_severity_ts",
        "idx_activity_timestamp_desc",
        "ix_custom_column_values_target_id",
        "ix_images_resolved_target_session",
        "ix_images_session_date",
        "ix_images_resolved_target_id_image_type",
        "ix_images_image_type_capture_date",
        "ix_images_object_name_trgm",
        "ix_images_object_name",
        "ix_targets_active",
        "ix_targets_merged_into_id",
        "ix_site_dark_hours_lat_lon",
    ]:
        op.execute(text(f"DROP INDEX IF EXISTS {idx}"))

    for table, col in [
        ("merge_candidates", "reason_text"),
        ("targets", "name_locked"),
        ("targets", "distance_pc"),
        ("targets", "reference_thumbnail_path"),
        ("targets", "sac_notes"),
        ("targets", "sac_description"),
        ("mosaics", "needs_review"),
        ("mosaics", "pixel_coords"),
        ("mosaics", "rotation_angle"),
        ("images", "session_date"),
        ("mosaic_suggestions", "session_dates"),
        ("mosaic_suggestions", "panel_patterns"),
        ("mosaic_suggestions", "base_name"),
        ("refresh_tokens", "persistent"),
        ("mosaic_panels", "flip_h"),
        ("mosaic_panels", "rotation"),
        ("mosaic_panels", "grid_col"),
        ("mosaic_panels", "grid_row"),
    ]:
        if _column_exists(table, col):
            op.drop_column(table, col)

    op.alter_column("merge_candidates", "suggested_target_id", nullable=False)
