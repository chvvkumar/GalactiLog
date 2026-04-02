"""Add mosaics, mosaic_panels, and mosaic_suggestions tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mosaics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    op.create_table(
        "mosaic_panels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("mosaic_id", UUID(as_uuid=True), sa.ForeignKey("mosaics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=False, unique=True),
        sa.Column("panel_label", sa.String(100), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("mosaic_id", "target_id", name="uq_mosaic_panels_mosaic_target"),
        if_not_exists=True,
    )

    op.create_table(
        "mosaic_suggestions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("suggested_name", sa.String(255), nullable=False),
        sa.Column("target_ids", ARRAY(UUID(as_uuid=True)), nullable=False),
        sa.Column("panel_labels", ARRAY(sa.String), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("mosaic_suggestions")
    op.drop_table("mosaic_panels")
    op.drop_table("mosaics")
