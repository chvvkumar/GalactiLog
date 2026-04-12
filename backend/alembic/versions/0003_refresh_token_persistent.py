"""Add persistent column to refresh_tokens for 'remember me' sessions.

When a user logs in with 'Remember me' checked, the refresh token is marked
persistent so that cookie max_age is set on subsequent refreshes too.
"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar()
    return result is not None


def upgrade() -> None:
    if not _column_exists("refresh_tokens", "persistent"):
        op.add_column(
            "refresh_tokens",
            sa.Column("persistent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    if _column_exists("refresh_tokens", "persistent"):
        op.drop_column("refresh_tokens", "persistent")
