"""Add name_locked to targets and reason_text to merge_candidates.

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
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
        "targets", "name_locked",
        sa.Column("name_locked", sa.Boolean(), nullable=False, server_default="false"),
    )
    _add_column_if_not_exists(
        "merge_candidates", "reason_text",
        sa.Column("reason_text", sa.String(500), nullable=True),
    )


def downgrade():
    op.drop_column("merge_candidates", "reason_text")
    op.drop_column("targets", "name_locked")
