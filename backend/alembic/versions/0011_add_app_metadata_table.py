"""Add app_metadata table for tracking data version."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_metadata",
        if_not_exists=True,
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", JSONB, nullable=False, server_default="{}"),
    )
    # Seed the data_version row at 0 (no migrations applied yet)
    op.execute(
        "INSERT INTO app_metadata (key, value) VALUES ('data_version', '0') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("app_metadata")
