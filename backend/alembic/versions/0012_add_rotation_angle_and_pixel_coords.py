"""Add rotation_angle and pixel_coords columns to mosaics table.

Supports Konva.js canvas-based mosaic panel arranger: rotation_angle stores
global mosaic rotation in degrees, pixel_coords distinguishes legacy cell-index
positions from pixel coordinate positions.

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _add_column_if_not_exists(table, column_name, column):
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    if column_name not in columns:
        op.add_column(table, column)


def upgrade():
    _add_column_if_not_exists(
        "mosaics", "rotation_angle",
        sa.Column("rotation_angle", sa.Float(), nullable=True, server_default="0.0"),
    )
    _add_column_if_not_exists(
        "mosaics", "pixel_coords",
        sa.Column("pixel_coords", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade():
    op.drop_column("mosaics", "pixel_coords")
    op.drop_column("mosaics", "rotation_angle")
