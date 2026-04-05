"""Add custom_columns and custom_column_values tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = :table"
    ), {"table": table})
    return result.scalar() is not None


def upgrade() -> None:
    # -- custom_columns --
    if not _table_exists("custom_columns"):
        column_type_enum = sa.Enum(
            "boolean", "text", "dropdown",
            name="custom_column_type",
            create_type=True,
        )
        applies_to_enum = sa.Enum(
            "target", "session", "rig",
            name="custom_column_applies_to",
            create_type=True,
        )
        op.create_table(
            "custom_columns",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                       server_default=sa.text("gen_random_uuid()")),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(255), nullable=False, unique=True),
            sa.Column("column_type", column_type_enum, nullable=False),
            sa.Column("applies_to", applies_to_enum, nullable=False),
            sa.Column("dropdown_options", sa.ARRAY(sa.String), nullable=True),
            sa.Column("display_order", sa.Integer, nullable=False,
                       server_default=sa.text("0")),
            sa.Column("created_by", UUID(as_uuid=True),
                       sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                       server_default=sa.text("now()")),
        )

    # -- custom_column_values --
    if not _table_exists("custom_column_values"):
        op.create_table(
            "custom_column_values",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                       server_default=sa.text("gen_random_uuid()")),
            sa.Column("column_id", UUID(as_uuid=True),
                       sa.ForeignKey("custom_columns.id", ondelete="CASCADE"),
                       nullable=False),
            sa.Column("target_id", UUID(as_uuid=True),
                       sa.ForeignKey("targets.id", ondelete="CASCADE"),
                       nullable=False),
            sa.Column("session_date", sa.Date, nullable=True),
            sa.Column("rig_label", sa.String(255), nullable=True),
            sa.Column("value", sa.Text, nullable=False),
            sa.Column("updated_by", UUID(as_uuid=True),
                       sa.ForeignKey("users.id"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                       server_default=sa.text("now()")),
        )

    # -- Indexes on custom_column_values --
    op.create_index(
        "ix_custom_column_values_target",
        "custom_column_values",
        ["target_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_custom_column_values_column",
        "custom_column_values",
        ["column_id"],
        if_not_exists=True,
    )

    # Unique composite index with COALESCE for nullable columns
    op.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_custom_column_value "
        "ON custom_column_values ("
        "column_id, target_id, "
        "COALESCE(session_date, '1970-01-01'), "
        "COALESCE(rig_label, '')"
        ")"
    ))


def downgrade() -> None:
    op.drop_index("uq_custom_column_value", table_name="custom_column_values")
    op.drop_index("ix_custom_column_values_column", table_name="custom_column_values")
    op.drop_index("ix_custom_column_values_target", table_name="custom_column_values")
    op.drop_table("custom_column_values")
    op.drop_table("custom_columns")
    op.execute(sa.text("DROP TYPE IF EXISTS custom_column_type"))
    op.execute(sa.text("DROP TYPE IF EXISTS custom_column_applies_to"))
