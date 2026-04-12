"""Add manual layout columns to mosaic_panels.

Adds grid_row, grid_col, rotation, and flip_h so users can manually arrange
mosaic panels in a grid and override per-panel orientation to reconcile
meridian-flipped captures. Existing panels default to rotation=0, flip_h=false,
and a NULL grid position (meaning "not placed in the manual grid", fall back
to sort_order-based auto layout).
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar()
    return result is not None


def _add_column_if_not_exists(table: str, column: sa.Column) -> None:
    if not _column_exists(table, column.name):
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_not_exists(
        "mosaic_panels", sa.Column("grid_row", sa.Integer(), nullable=True)
    )
    _add_column_if_not_exists(
        "mosaic_panels", sa.Column("grid_col", sa.Integer(), nullable=True)
    )
    _add_column_if_not_exists(
        "mosaic_panels",
        sa.Column("rotation", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_not_exists(
        "mosaic_panels",
        sa.Column("flip_h", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("mosaic_panels", "flip_h")
    op.drop_column("mosaic_panels", "rotation")
    op.drop_column("mosaic_panels", "grid_col")
    op.drop_column("mosaic_panels", "grid_row")
