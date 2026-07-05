"""Add data_jobs table for durable per-job backfill state.

Introduces a single table that gives each backfill run (starting with the
existing data-migration runner) a durable record: identity (job_type +
job_key), a state machine (pending/running/succeeded/failed/interrupted),
progress counters (step/total_steps + free-text message), timestamps
(enqueued/started/finished/heartbeat), attempt count, and last_error.

Completion authority stays with the app_metadata "data_version" row read by
get_pending_migrations and the boot gate. data_jobs rows record attempt,
progress, and outcome for observability and API progress reporting only;
they are never consulted to decide what work is already done.

No behavior change yet: nothing writes to this table until the
run_data_migrations refactor that follows this migration.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, UUID

# revision identifiers, used by Alembic.
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_jobs",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("job_key", sa.String(128), nullable=False),
        sa.Column(
            "status",
            ENUM(
                "pending", "running", "succeeded", "failed", "interrupted",
                name="data_job_status_enum",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("step", sa.Integer(), nullable=True),
        sa.Column("total_steps", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("job_type", "job_key", name="uq_data_jobs_type_key"),
    )
    op.create_index("ix_data_jobs_status", "data_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_data_jobs_status", table_name="data_jobs")
    op.drop_table("data_jobs")
    ENUM(name="data_job_status_enum").drop(op.get_bind(), checkfirst=True)
