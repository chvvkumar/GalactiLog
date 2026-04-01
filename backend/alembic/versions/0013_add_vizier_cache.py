"""Add VizieR cache table."""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vizier_cache",
        sa.Column("catalog_id", sa.String(50), primary_key=True),
        sa.Column("vizier_catalog", sa.String(20), nullable=True),
        sa.Column("size_major", sa.Float, nullable=True),
        sa.Column("size_minor", sa.Float, nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("vizier_cache")
