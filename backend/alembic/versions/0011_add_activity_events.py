"""Add activity_events table.

Creates the activity_events table with all columns and indexes defined in
the activity log redesign spec. Uses defensive IF NOT EXISTS guards per
project convention.
"""
from alembic import op
from sqlalchemy import text

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name"
        ),
        {"name": name},
    )
    return result.fetchone() is not None


def upgrade():
    if not _table_exists("activity_events"):
        op.execute("""
            CREATE TABLE activity_events (
                id          bigserial PRIMARY KEY,
                timestamp   timestamptz NOT NULL DEFAULT now(),
                severity    varchar(16) NOT NULL,
                category    varchar(32) NOT NULL,
                event_type  varchar(64) NOT NULL,
                message     text NOT NULL,
                details     jsonb,
                target_id   uuid REFERENCES targets(id) ON DELETE SET NULL,
                actor       varchar(64),
                duration_ms integer
            )
        """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_timestamp_desc "
        "ON activity_events (timestamp DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_severity_ts "
        "ON activity_events (severity, timestamp DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_category_ts "
        "ON activity_events (category, timestamp DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_target "
        "ON activity_events (target_id) WHERE target_id IS NOT NULL"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_activity_target")
    op.execute("DROP INDEX IF EXISTS idx_activity_category_ts")
    op.execute("DROP INDEX IF EXISTS idx_activity_severity_ts")
    op.execute("DROP INDEX IF EXISTS idx_activity_timestamp_desc")
    op.execute("DROP TABLE IF EXISTS activity_events")
