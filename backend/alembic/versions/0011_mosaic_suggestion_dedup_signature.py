"""Add dedup_signature to mosaic_suggestions for durable dismissals.

Detection clears all pending suggestions and regenerates each run. To keep a
dismissed (status='rejected') suggestion from resurfacing, each suggestion now
stores a stable signature of its panel set (base_name + sorted target_ids +
sorted panel_labels). A new run skips any group whose signature matches a
rejected row.

The add uses a defensive column-existence guard so the migration is safe on
installs bootstrapped via create_all then `alembic stamp head` (see CLAUDE.md
and 0006). The index creation is likewise guarded.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_INDEX = "ix_mosaic_suggestions_dedup_signature"
_TABLE = "mosaic_suggestions"
_COLUMN = "dedup_signature"


def _column_exists(table: str, column: str) -> bool:
    inspector = sa_inspect(op.get_bind())
    return column in [c["name"] for c in inspector.get_columns(table)]


def _index_exists(table: str, index: str) -> bool:
    inspector = sa_inspect(op.get_bind())
    return index in [ix["name"] for ix in inspector.get_indexes(table)]


def _add_column_if_not_exists(table: str, col: sa.Column) -> None:
    if not _column_exists(table, col.name):
        op.add_column(table, col)


def upgrade() -> None:
    _add_column_if_not_exists(
        _TABLE, sa.Column(_COLUMN, sa.String(length=512), nullable=True)
    )
    if not _index_exists(_TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    if _index_exists(_TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if _column_exists(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
