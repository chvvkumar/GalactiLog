"""Add performance indexes for hot query patterns.

Indexes target the heaviest endpoints identified by Prometheus metrics:
- /api/stats: site_dark_hours lat/lon lookup
- /api/targets: merged_into_id filter, active targets partial index
- /api/mosaics/suggestions: OBJECT header extraction from JSONB
- /api/targets composite: image_type + capture_date for timeline queries
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_site_dark_hours_lat_lon "
        "ON site_dark_hours (latitude, longitude)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_targets_merged_into_id "
        "ON targets (merged_into_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_targets_active "
        "ON targets (id) WHERE merged_into_id IS NULL"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_images_object_name "
        "ON images ((raw_headers->>'OBJECT'))"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_images_target_id_image_type "
        "ON images (resolved_target_id, image_type)"
    ))
    # Trigram index for ILIKE pattern matching on OBJECT header
    # (used by /api/mosaics/suggestions)
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_images_object_name_trgm "
        "ON images USING gin ((raw_headers->>'OBJECT') gin_trgm_ops)"
    ))


def downgrade() -> None:
    for name in [
        "ix_site_dark_hours_lat_lon",
        "ix_targets_merged_into_id",
        "ix_targets_active",
        "ix_images_object_name",
        "ix_images_object_name_trgm",
        "ix_images_target_id_image_type",
    ]:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
