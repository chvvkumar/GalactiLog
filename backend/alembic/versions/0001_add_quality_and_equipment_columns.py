"""Add quality metrics and equipment columns to images table."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = "0000"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("images", sa.Column("telescope", sa.String(255), nullable=True))
    op.add_column("images", sa.Column("camera", sa.String(255), nullable=True))
    op.add_column("images", sa.Column("median_hfr", sa.Float, nullable=True))
    op.add_column("images", sa.Column("eccentricity", sa.Float, nullable=True))
    op.create_index("ix_images_telescope", "images", ["telescope"])
    op.create_index("ix_images_camera", "images", ["camera"])

def downgrade() -> None:
    op.drop_index("ix_images_camera", table_name="images")
    op.drop_index("ix_images_telescope", table_name="images")
    op.drop_column("images", "eccentricity")
    op.drop_column("images", "median_hfr")
    op.drop_column("images", "camera")
    op.drop_column("images", "telescope")
