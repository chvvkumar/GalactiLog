"""Add VizieR cache table and backfill missing columns from 0012."""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _add_column_if_not_exists(table: str, column: sa.Column) -> None:
    """Add a column only if it doesn't already exist (repairs partial 0012 runs)."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :col"
    ), {"table": table, "col": column.name})
    if result.fetchone() is None:
        op.add_column(table, column)


def upgrade() -> None:
    # Repair: Base.metadata.create_all may have created some 0012 columns
    # before Alembic ran, causing 0012 to skip them. Ensure all exist.
    # Repair targets columns from 0012
    _add_column_if_not_exists("targets", sa.Column("constellation", sa.String(5), nullable=True))
    _add_column_if_not_exists("targets", sa.Column("size_major", sa.Float, nullable=True))
    _add_column_if_not_exists("targets", sa.Column("size_minor", sa.Float, nullable=True))
    _add_column_if_not_exists("targets", sa.Column("position_angle", sa.Float, nullable=True))
    _add_column_if_not_exists("targets", sa.Column("v_mag", sa.Float, nullable=True))
    _add_column_if_not_exists("targets", sa.Column("surface_brightness", sa.Float, nullable=True))

    # Repair openngc_catalog columns from 0012
    _add_column_if_not_exists("openngc_catalog", sa.Column("constellation", sa.String(5), nullable=True))

    op.create_table(
        "vizier_cache",
        sa.Column("catalog_id", sa.String(50), primary_key=True),
        sa.Column("vizier_catalog", sa.String(20), nullable=True),
        sa.Column("size_major", sa.Float, nullable=True),
        sa.Column("size_minor", sa.Float, nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("vizier_cache")
