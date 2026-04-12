"""Add catalog enrichment tables and target columns for Phase 2.

Creates NED, HyperLEDA, and Gaia cache tables; SAC, Caldwell, Herschel 400,
Arp, and Abell catalog tables; the target_catalog_memberships join table;
and new enrichment columns on the targets table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "a1b2c3d4e5f6"
down_revision = "0006"
branch_labels = None
depends_on = None


def _add_column_if_not_exists(table, column_name, column):
    """Defensive helper: skip if column already exists (legacy create_all installs)."""
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    if column_name not in columns:
        op.add_column(table, sa.Column(column_name, column.type, nullable=column.nullable))


def _create_table_if_not_exists(table_name, *columns, **kw):
    """Create a table only if it does not already exist."""
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    if table_name not in inspector.get_table_names():
        op.create_table(table_name, *columns, **kw)


def upgrade() -> None:
    # -- Cache tables ----------------------------------------------------------

    _create_table_if_not_exists(
        "ned_cache",
        sa.Column("catalog_id", sa.String(100), primary_key=True),
        sa.Column("ned_morphology", sa.String(50), nullable=True),
        sa.Column("redshift", sa.Float, nullable=True),
        sa.Column("distance_mpc", sa.Float, nullable=True),
        sa.Column("activity_type", sa.String(100), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    _create_table_if_not_exists(
        "hyperleda_cache",
        sa.Column("catalog_id", sa.String(100), primary_key=True),
        sa.Column("t_type", sa.Float, nullable=True),
        sa.Column("inclination", sa.Float, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    _create_table_if_not_exists(
        "gaia_cache",
        sa.Column("target_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("distance_pc", sa.Float, nullable=True),
        sa.Column("parallax_count", sa.Integer, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # -- Catalog source tables -------------------------------------------------

    _create_table_if_not_exists(
        "sac_catalog",
        sa.Column("object_name", sa.String(50), primary_key=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("object_type", sa.String(20), nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("magnitude", sa.Float, nullable=True),
        sa.Column("size", sa.String(30), nullable=True),
    )

    _create_table_if_not_exists(
        "caldwell_catalog",
        sa.Column("catalog_id", sa.String(10), primary_key=True),
        sa.Column("ngc_ic_id", sa.String(20), nullable=True),
        sa.Column("object_type", sa.String(20), nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("common_name", sa.String(100), nullable=True),
    )

    _create_table_if_not_exists(
        "herschel400_catalog",
        sa.Column("ngc_id", sa.String(20), primary_key=True),
        sa.Column("object_type", sa.String(20), nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("magnitude", sa.Float, nullable=True),
    )

    _create_table_if_not_exists(
        "arp_catalog",
        sa.Column("arp_id", sa.String(10), primary_key=True),
        sa.Column("ngc_ic_ids", sa.String(200), nullable=True),
        sa.Column("peculiarity_class", sa.String(100), nullable=True),
        sa.Column("peculiarity_description", sa.Text, nullable=True),
    )

    _create_table_if_not_exists(
        "abell_catalog",
        sa.Column("abell_id", sa.String(20), primary_key=True),
        sa.Column("ra", sa.Float, nullable=True),
        sa.Column("dec", sa.Float, nullable=True),
        sa.Column("richness_class", sa.Integer, nullable=True),
        sa.Column("distance_class", sa.Integer, nullable=True),
        sa.Column("bm_type", sa.String(10), nullable=True),
        sa.Column("redshift", sa.Float, nullable=True),
    )

    # -- Catalog membership join table -----------------------------------------

    _create_table_if_not_exists(
        "target_catalog_memberships",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=False, index=True),
        sa.Column("catalog_name", sa.String(30), nullable=False),
        sa.Column("catalog_number", sa.String(20), nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
        sa.UniqueConstraint("target_id", "catalog_name", name="uq_target_catalog"),
    )

    # -- New columns on targets ------------------------------------------------

    _add_column_if_not_exists(
        "targets", "ned_morphology",
        sa.Column("ned_morphology", sa.String(50), nullable=True),
    )
    _add_column_if_not_exists(
        "targets", "redshift",
        sa.Column("redshift", sa.Float, nullable=True),
    )
    _add_column_if_not_exists(
        "targets", "distance_mpc",
        sa.Column("distance_mpc", sa.Float, nullable=True),
    )
    _add_column_if_not_exists(
        "targets", "activity_type",
        sa.Column("activity_type", sa.String(100), nullable=True),
    )
    _add_column_if_not_exists(
        "targets", "hubble_t_type",
        sa.Column("hubble_t_type", sa.Float, nullable=True),
    )
    _add_column_if_not_exists(
        "targets", "inclination",
        sa.Column("inclination", sa.Float, nullable=True),
    )
    _add_column_if_not_exists(
        "targets", "sac_description",
        sa.Column("sac_description", sa.Text, nullable=True),
    )
    _add_column_if_not_exists(
        "targets", "sac_notes",
        sa.Column("sac_notes", sa.Text, nullable=True),
    )
    _add_column_if_not_exists(
        "targets", "reference_thumbnail_path",
        sa.Column("reference_thumbnail_path", sa.String(1024), nullable=True),
    )
    _add_column_if_not_exists(
        "targets", "distance_pc",
        sa.Column("distance_pc", sa.Float, nullable=True),
    )


def downgrade() -> None:
    pass
