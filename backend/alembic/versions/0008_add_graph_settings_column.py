"""Add graph settings column to user_settings table."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("graph", JSONB, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "graph")
