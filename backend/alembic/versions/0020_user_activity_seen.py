"""Add users.activity_seen_at for the job monitor's unseen-error badge.

Nullable timezone-aware timestamp: when this user last marked the activity
error feed as seen (POST /api/activity/seen). NULL means never marked, which
the frontend treats as "every fetched error is unseen".

Plain add_column with no existence guard: guards are reserved for revisions
with a specific stated reason (see 0018's autocommit backfill), and installs
bootstrapped by create_all-then-stamp are no longer supported
(MIN_UPGRADE_FROM_DATA_VERSION = 13).

No index: the column is only ever read for the requesting user's own row,
which the primary key already serves.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("activity_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "activity_seen_at")
