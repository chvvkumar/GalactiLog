"""Add catalog_id and common_name columns to targets."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("targets", sa.Column("catalog_id", sa.String(100), nullable=True))
    op.add_column("targets", sa.Column("common_name", sa.String(255), nullable=True))
    op.execute(
        "CREATE INDEX ix_targets_catalog_id_trgm ON targets "
        "USING GIN (catalog_id gin_trgm_ops)"
    )

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_targets_catalog_id_trgm")
    op.drop_column("targets", "common_name")
    op.drop_column("targets", "catalog_id")
