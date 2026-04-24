"""Add parent_id to activity_events for hierarchical grouping.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    inspector = sa_inspect(op.get_bind())
    return column in [c["name"] for c in inspector.get_columns(table)]


def upgrade() -> None:
    if not _column_exists("activity_events", "parent_id"):
        op.add_column(
            "activity_events",
            sa.Column(
                "parent_id",
                sa.BigInteger(),
                sa.ForeignKey("activity_events.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )
        op.create_index(
            "ix_activity_events_parent_id",
            "activity_events",
            ["parent_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_activity_events_parent_id", table_name="activity_events")
    op.drop_column("activity_events", "parent_id")
