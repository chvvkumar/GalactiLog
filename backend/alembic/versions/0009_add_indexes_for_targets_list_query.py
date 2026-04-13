"""Add indexes for targets list query.

Adds indexes to speed up the /api/targets endpoint:

- ix_images_session_date: covers ordering/grouping by session_date.
- ix_images_resolved_target_session: composite index for resolved_target_id
  with session_date, used by the main targets aggregation query.
- ix_custom_column_values_target_id: speeds up custom column value lookups
  filtered by target.
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_images_session_date "
        "ON images (session_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_images_resolved_target_session "
        "ON images (resolved_target_id, session_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_custom_column_values_target_id "
        "ON custom_column_values (target_id)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_images_session_date")
    op.execute("DROP INDEX IF EXISTS ix_images_resolved_target_session")
    op.execute("DROP INDEX IF EXISTS ix_custom_column_values_target_id")
