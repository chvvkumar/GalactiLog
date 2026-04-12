"""Add trigram index for ILIKE pattern matching on OBJECT header.

The mosaic suggestions endpoint uses ILIKE queries against the extracted
OBJECT name from raw_headers JSONB. A pg_trgm GIN index allows Postgres
to use trigram matching instead of sequential scans (2.8s to ~770ms on
80k images).
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_images_object_name_trgm "
        "ON images USING gin ((raw_headers->>'OBJECT') gin_trgm_ops)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_images_object_name_trgm"))
