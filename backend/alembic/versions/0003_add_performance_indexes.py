"""Add performance indexes for common query patterns.

Two composite/single-column indexes to speed up frequent queries:
- mosaic_panel_sessions(panel_id, status)
- target_catalog_memberships(catalog_name)

The images(resolved_target_id, image_type) index is already created in 0002
as ix_images_resolved_target_id_image_type.

All operations use IF NOT EXISTS / IF EXISTS guards per project convention.
"""
# NOTE: CREATE INDEX locks the target table for the duration of the build.
# For large tables, consider running these statements manually with CONCURRENTLY
# outside of Alembic's transaction management.
from alembic import op
from sqlalchemy import text


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in [
        "CREATE INDEX IF NOT EXISTS ix_mps_panel_status ON mosaic_panel_sessions (panel_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_tcm_catalog_name ON target_catalog_memberships (catalog_name)",
    ]:
        op.execute(text(stmt))


def downgrade() -> None:
    for idx in [
        "ix_tcm_catalog_name",
        "ix_mps_panel_status",
    ]:
        op.execute(text(f"DROP INDEX IF EXISTS {idx}"))
