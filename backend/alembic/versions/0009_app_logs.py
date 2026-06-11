"""Add app_logs table for backend log capture.

Raw Python backend logs (api / worker / beat) are buffered to Redis by a
logging handler and drained into this table by a Celery beat task. DDL is
defensive per CLAUDE.md: the table may already exist on installs that were
bootstrapped via create_all then `alembic stamp head`, so creation is guarded.
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "app_logs" in insp.get_table_names():
        return
    op.create_table(
        "app_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("logger", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_logs_timestamp", "app_logs", ["timestamp"])
    op.create_index("ix_app_logs_level_timestamp", "app_logs", ["level", "timestamp"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "app_logs" not in insp.get_table_names():
        return
    op.drop_index("ix_app_logs_level_timestamp", table_name="app_logs")
    op.drop_index("ix_app_logs_timestamp", table_name="app_logs")
    op.drop_table("app_logs")
