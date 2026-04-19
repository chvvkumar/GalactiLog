"""Make merge_candidates.suggested_target_id nullable for orphan entries.

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("merge_candidates", "suggested_target_id", nullable=True)


def downgrade() -> None:
    op.alter_column("merge_candidates", "suggested_target_id", nullable=False)
