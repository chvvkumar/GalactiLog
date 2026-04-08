"""Add OpenNGC reference table and target enrichment fields."""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "openngc_catalog",
        if_not_exists=True,
        sa.Column("name", sa.String(20), primary_key=True),
        sa.Column("type", sa.String(10), nullable=True),
        sa.Column("ra", sa.Float, nullable=True),
        sa.Column("dec", sa.Float, nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("major_axis", sa.Float, nullable=True),
        sa.Column("minor_axis", sa.Float, nullable=True),
        sa.Column("position_angle", sa.Float, nullable=True),
        sa.Column("b_mag", sa.Float, nullable=True),
        sa.Column("v_mag", sa.Float, nullable=True),
        sa.Column("surface_brightness", sa.Float, nullable=True),
        sa.Column("common_names", sa.String(500), nullable=True),
        sa.Column("messier", sa.String(10), nullable=True),
    )

    op.add_column("targets", sa.Column("constellation", sa.String(5), nullable=True))
    op.add_column("targets", sa.Column("size_major", sa.Float, nullable=True))
    op.add_column("targets", sa.Column("size_minor", sa.Float, nullable=True))
    op.add_column("targets", sa.Column("position_angle", sa.Float, nullable=True))
    op.add_column("targets", sa.Column("v_mag", sa.Float, nullable=True))
    op.add_column("targets", sa.Column("surface_brightness", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("targets", "surface_brightness")
    op.drop_column("targets", "v_mag")
    op.drop_column("targets", "position_angle")
    op.drop_column("targets", "size_minor")
    op.drop_column("targets", "size_major")
    op.drop_column("targets", "constellation")
    op.drop_table("openngc_catalog")
