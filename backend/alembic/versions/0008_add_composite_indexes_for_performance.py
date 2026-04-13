"""Add composite indexes for performance.

Adds two composite indexes on the images table to speed up the most
common query patterns:

- ix_images_image_type_capture_date: covers filters on image_type with
  ordering/grouping by capture_date (stats and targets queries).
- ix_images_resolved_target_id_image_type: covers grouping by
  resolved_target_id with image_type filtering (targets listing).
"""
from alembic import op

revision = "0008"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_images_image_type_capture_date "
        "ON images (image_type, capture_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_images_resolved_target_id_image_type "
        "ON images (resolved_target_id, image_type)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_images_image_type_capture_date")
    op.execute("DROP INDEX IF EXISTS ix_images_resolved_target_id_image_type")
