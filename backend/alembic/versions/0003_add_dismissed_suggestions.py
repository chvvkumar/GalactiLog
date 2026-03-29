"""Add dismissed_suggestions column to user_settings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("dismissed_suggestions", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "dismissed_suggestions")
