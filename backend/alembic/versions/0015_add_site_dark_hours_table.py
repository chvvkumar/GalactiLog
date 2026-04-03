"""Add site_dark_hours table for precomputed astronomical night durations."""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_dark_hours",
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("dark_hours", sa.Float, nullable=False),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("site_dark_hours")
