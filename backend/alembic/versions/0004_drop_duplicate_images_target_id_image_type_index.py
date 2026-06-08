"""Drop duplicate images(resolved_target_id, image_type) index.

The images table carried two identical composite indexes on
(resolved_target_id, image_type):

- ix_images_target_id_image_type            (legacy, from old create_all bootstrap)
- ix_images_resolved_target_id_image_type   (created by migration 0002)

They are functionally identical. The legacy index is dropped; the
canonical ix_images_resolved_target_id_image_type is kept.

All operations use IF EXISTS / IF NOT EXISTS guards per project convention,
since the legacy index may or may not exist depending on how the install
was bootstrapped.
"""
from alembic import op
from sqlalchemy import text


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS ix_images_target_id_image_type"))


def downgrade() -> None:
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_images_target_id_image_type "
            "ON images (resolved_target_id, image_type)"
        )
    )
