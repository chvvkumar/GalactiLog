"""Create base targets and images tables for fresh installs.

These tables were originally created by Base.metadata.create_all() before
Alembic was introduced.  Existing installs that were bootstrapped with
create_all and then ``alembic stamp head`` already have these tables, so
every CREATE is guarded with IF NOT EXISTS.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "0000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- targets ----------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS targets (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            primary_name VARCHAR(255) NOT NULL UNIQUE,
            aliases     VARCHAR[] NOT NULL DEFAULT '{}',
            ra          DOUBLE PRECISION,
            dec         DOUBLE PRECISION,
            object_type VARCHAR(100)
        )
    """)

    # -- images -----------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            file_path           VARCHAR(1024) NOT NULL UNIQUE,
            file_name           VARCHAR(255) NOT NULL,
            capture_date        TIMESTAMPTZ,
            thumbnail_path      VARCHAR(1024),
            resolved_target_id  UUID REFERENCES targets(id),
            exposure_time       DOUBLE PRECISION,
            filter_used         VARCHAR(50),
            sensor_temp         DOUBLE PRECISION,
            camera_gain         INTEGER,
            image_type          VARCHAR(20),
            raw_headers         JSONB DEFAULT '{}'
        )
    """)

    # Indexes that the original create_all would have made
    op.execute("CREATE INDEX IF NOT EXISTS ix_images_capture_date ON images (capture_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_images_filter_used  ON images (filter_used)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_images_resolved_target_id ON images (resolved_target_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_images_image_type   ON images (image_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_images_raw_headers  ON images USING GIN (raw_headers)")


def downgrade() -> None:
    op.drop_table("images")
    op.drop_table("targets")
