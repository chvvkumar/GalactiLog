"""add image session_date column

Revision ID: 0009
Revises: 0008_add_composite_indexes_for_performance
Create Date: 2026-04-13
"""
from alembic import op
import sqlalchemy as sa


revision = "0009_add_image_session_date"
down_revision = "0008_add_composite_indexes_for_performance"
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
        "images", "session_date",
        sa.Column("session_date", sa.Date(), nullable=True),
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_images_session_date
        ON images (session_date)
    """)


def downgrade():
    op.drop_index("ix_images_session_date", table_name="images")
    op.drop_column("images", "session_date")
