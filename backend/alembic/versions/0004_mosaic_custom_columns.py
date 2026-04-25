"""Add mosaic custom columns support

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0004_mosaic_custom_columns"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE applies_to_enum ADD VALUE IF NOT EXISTS 'mosaic'")

    op.add_column(
        "custom_column_values",
        sa.Column("mosaic_id", UUID(as_uuid=True), sa.ForeignKey("mosaics.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("ix_custom_column_values_mosaic", "custom_column_values", ["mosaic_id"])

    # Rebuild unique constraint to include mosaic_id
    op.drop_index("uq_custom_column_value", table_name="custom_column_values")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_custom_column_value
        ON custom_column_values (
            column_id,
            COALESCE(target_id, '00000000-0000-0000-0000-000000000000'),
            COALESCE(mosaic_id, '00000000-0000-0000-0000-000000000000'),
            COALESCE(session_date, '1970-01-01'),
            COALESCE(rig_label, '')
        )
        """
    )


def downgrade() -> None:
    op.drop_index("uq_custom_column_value", table_name="custom_column_values")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_custom_column_value
        ON custom_column_values (
            column_id, target_id,
            COALESCE(session_date, '1970-01-01'),
            COALESCE(rig_label, '')
        )
        """
    )
    op.drop_index("ix_custom_column_values_mosaic", table_name="custom_column_values")
    op.drop_column("custom_column_values", "mosaic_id")
