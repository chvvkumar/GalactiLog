"""Add performance indexes for common query patterns.

Two composite/single-column indexes to speed up frequent queries:
- mosaic_panel_sessions(panel_id, status)
- target_catalog_memberships(catalog_name)

The images(resolved_target_id, image_type) index is already created in 0002
as ix_images_resolved_target_id_image_type.

All operations use IF NOT EXISTS / IF EXISTS guards per project convention.
"""
# CREATE/DROP INDEX CONCURRENTLY cannot run inside a transaction block.
# op.get_context().autocommit_block() is the official Alembic API for this:
# it commits the preceding transaction and enters an autocommit context so the
# CONCURRENTLY statements are issued outside any DBAPI transaction.
# IF NOT EXISTS / IF EXISTS keeps each statement idempotent for installs that
# were bootstrapped via create_all before Alembic was introduced.
from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_mps_panel_status"
            " ON mosaic_panel_sessions (panel_id, status)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tcm_catalog_name"
            " ON target_catalog_memberships (catalog_name)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_mps_panel_status")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_tcm_catalog_name")
