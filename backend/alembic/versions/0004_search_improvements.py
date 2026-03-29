"""Add pg_trgm extension, merge tracking columns, and merge_candidates table."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pg_trgm extension for trigram similarity search
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Add GIN trigram index on targets.primary_name
    op.execute(
        "CREATE INDEX ix_targets_primary_name_trgm ON targets "
        "USING GIN (primary_name gin_trgm_ops)"
    )

    # Add merge tracking columns to targets table
    op.add_column(
        "targets",
        sa.Column(
            "merged_into_id",
            UUID(as_uuid=True),
            sa.ForeignKey("targets.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "targets",
        sa.Column(
            "merged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Create merge_candidates table
    op.create_table(
        "merge_candidates",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column(
            "source_image_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "suggested_target_id",
            UUID(as_uuid=True),
            sa.ForeignKey("targets.id"),
            nullable=False,
        ),
        sa.Column("similarity_score", sa.Float, nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("merge_candidates")
    op.drop_column("targets", "merged_at")
    op.drop_column("targets", "merged_into_id")
    op.execute("DROP INDEX IF EXISTS ix_targets_primary_name_trgm")
    # Note: pg_trgm extension is intentionally not dropped to avoid
    # removing it if it was already present before this migration.
