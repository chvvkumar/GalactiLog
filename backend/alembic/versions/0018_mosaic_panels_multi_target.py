"""Allow multiple panels per target in mosaic_panels and add object_pattern."""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def _add_column_if_not_exists(table: str, column: sa.Column) -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :col"
    ), {"table": table, "col": column.name})
    if not result.scalar():
        op.add_column(table, column)


def upgrade() -> None:
    # Add object_pattern column for filtering frames by OBJECT header
    _add_column_if_not_exists(
        "mosaic_panels",
        sa.Column("object_pattern", sa.String(255), nullable=True),
    )

    # Drop the old unique constraint on target_id alone (if exists)
    conn = op.get_bind()
    # Drop column-level unique constraint on target_id
    result = conn.execute(sa.text("""
        SELECT con.conname FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = 'mosaic_panels'
          AND con.contype = 'u'
          AND con.conname IN ('mosaic_panels_target_id_key', 'uq_mosaic_panels_mosaic_target')
    """))
    for row in result:
        op.drop_constraint(row[0], "mosaic_panels", type_="unique")

    # Add new constraint: (mosaic_id, target_id, panel_label) unique
    op.create_unique_constraint(
        "uq_mosaic_panels_mosaic_target_label",
        "mosaic_panels",
        ["mosaic_id", "target_id", "panel_label"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_mosaic_panels_mosaic_target_label", "mosaic_panels", type_="unique")
    op.create_unique_constraint("uq_mosaic_panels_mosaic_target", "mosaic_panels", ["mosaic_id", "target_id"])
    op.drop_column("mosaic_panels", "object_pattern")
