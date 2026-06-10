"""Add targets.user_defined flag for manually created custom targets.

Custom targets (planets, comets, user-defined objects) must never be renamed
or mutated by SIMBAD re-resolution, enrichment, or rebuild maintenance. DDL is
defensive per CLAUDE.md (see 0007).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision = "0008"
down_revision = "0007"
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
        "targets",
        sa.Column("user_defined", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    if _column_exists("targets", "user_defined"):
        op.drop_column("targets", "user_defined")
