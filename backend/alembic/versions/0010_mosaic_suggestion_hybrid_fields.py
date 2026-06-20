"""Add name+position hybrid detection fields to mosaic_suggestions.

The mosaic panel detection rewrite groups by target and corroborates name
grouping with sky position. Each suggestion now records a confidence tier, the
discovery source (name / position / both), per-panel geometry, and a list of
human-readable low-confidence flags.

All adds use a defensive column-existence guard so the migration is safe on
installs bootstrapped via create_all then `alembic stamp head` (see CLAUDE.md
and 0006).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    inspector = sa_inspect(op.get_bind())
    return column in [c["name"] for c in inspector.get_columns(table)]


def _add_column_if_not_exists(table: str, col: sa.Column) -> None:
    if not _column_exists(table, col.name):
        op.add_column(table, col)


def upgrade() -> None:
    _add_column_if_not_exists(
        "mosaic_suggestions", sa.Column("confidence", sa.String(length=10), nullable=True)
    )
    _add_column_if_not_exists(
        "mosaic_suggestions", sa.Column("discovery_source", sa.String(length=10), nullable=True)
    )
    _add_column_if_not_exists(
        "mosaic_suggestions", sa.Column("geometry", JSONB(), nullable=True)
    )
    _add_column_if_not_exists(
        "mosaic_suggestions", sa.Column("flags", JSONB(), nullable=True)
    )


def downgrade() -> None:
    for col in ("flags", "geometry", "discovery_source", "confidence"):
        if _column_exists("mosaic_suggestions", col):
            op.drop_column("mosaic_suggestions", col)
