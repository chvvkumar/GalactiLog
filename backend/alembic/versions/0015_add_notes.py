"""Add session_notes table and target notes column."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    from sqlalchemy import inspect
    bind = op.get_bind()
    insp = inspect(bind)
    return column in [c["name"] for c in insp.get_columns(table)]


def upgrade() -> None:
    # Session notes table
    op.create_table(
        "session_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=False),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("target_id", "session_date", name="uq_session_notes_target_date"),
        if_not_exists=True,
    )

    # Target notes column
    if not _column_exists("targets", "notes"):
        op.add_column("targets", sa.Column("notes", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("targets", "notes")
    op.drop_table("session_notes")
