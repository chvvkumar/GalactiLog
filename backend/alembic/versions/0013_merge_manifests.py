"""Add merge_manifests table for reversible target merges.

A target merge previously recorded nothing about which exact images it moved,
so an unmerge/revert could only re-derive membership from OBJECT-header text.
That is lossy for images attached via filename resolution (blank/missing
OBJECT header), which then stayed stranded on the winner (AUD-005). This table
persists the exact image id set moved by a merge, plus the session-note and
custom-column-value rows that were re-keyed/appended (AUD-018), so unmerge and
revert replay the merge precisely.

DDL is defensive per CLAUDE.md: the table may already exist on installs
bootstrapped via create_all then `alembic stamp head`, so creation is guarded.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "merge_manifests" in insp.get_table_names():
        return
    op.create_table(
        "merge_manifests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("winner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("loser_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["winner_id"], ["targets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["loser_id"], ["targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_merge_manifests_winner", "merge_manifests", ["winner_id"])
    op.create_index("ix_merge_manifests_loser", "merge_manifests", ["loser_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "merge_manifests" not in insp.get_table_names():
        return
    op.drop_index("ix_merge_manifests_loser", table_name="merge_manifests")
    op.drop_index("ix_merge_manifests_winner", table_name="merge_manifests")
    op.drop_table("merge_manifests")
