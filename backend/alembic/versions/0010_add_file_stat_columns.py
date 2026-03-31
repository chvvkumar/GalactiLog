"""Add file_size and file_mtime columns for delta rescans."""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("images", sa.Column("file_size", sa.BigInteger(), nullable=True))
    op.add_column("images", sa.Column("file_mtime", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("images", "file_mtime")
    op.drop_column("images", "file_size")
