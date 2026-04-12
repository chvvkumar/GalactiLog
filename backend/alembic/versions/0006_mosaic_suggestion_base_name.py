"""Add base_name and panel_patterns columns to mosaic_suggestions.

base_name stores the original target base name (without year suffix) used
for OBJECT header pattern matching. panel_patterns stores pre-computed
ILIKE patterns per panel so the suggestions endpoint doesn't need to
reconstruct them from the suggested_name.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0006"
down_revision = "0005"
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


def upgrade() -> None:
    _add_column_if_not_exists(
        "mosaic_suggestions", "base_name",
        sa.Column("base_name", sa.String(255), nullable=True),
    )
    _add_column_if_not_exists(
        "mosaic_suggestions", "panel_patterns",
        sa.Column("panel_patterns", ARRAY(sa.String), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mosaic_suggestions", "panel_patterns")
    op.drop_column("mosaic_suggestions", "base_name")
