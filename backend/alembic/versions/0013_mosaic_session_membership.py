"""Add mosaic session membership table and related columns.

Revision ID: 0013
Revises: 0012
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c["name"] for c in insp.get_columns(table_name)]
    return column_name in columns


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    # 1. Create mosaic_panel_sessions table
    if not _table_exists("mosaic_panel_sessions"):
        op.create_table(
            "mosaic_panel_sessions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("panel_id", UUID(as_uuid=True), sa.ForeignKey("mosaic_panels.id", ondelete="CASCADE"), nullable=False),
            sa.Column("session_date", sa.Date, nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="available"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("panel_id", "session_date", name="uq_mosaic_panel_sessions_panel_date"),
        )
        op.create_index("ix_mosaic_panel_sessions_panel_id", "mosaic_panel_sessions", ["panel_id"])
        op.create_index("ix_mosaic_panel_sessions_status", "mosaic_panel_sessions", ["status"])

    # 2. Add needs_review to mosaics
    if not _column_exists("mosaics", "needs_review"):
        op.add_column("mosaics", sa.Column("needs_review", sa.Boolean, nullable=False, server_default="false"))

    # 3. Add session_dates to mosaic_suggestions
    if not _column_exists("mosaic_suggestions", "session_dates"):
        op.add_column("mosaic_suggestions", sa.Column("session_dates", JSONB, nullable=True))

    # 4. Data migration: seed session records for existing mosaic panels
    conn = op.get_bind()
    panels = conn.execute(sa.text(
        "SELECT mp.id AS panel_id, mp.target_id, mp.object_pattern, m.id AS mosaic_id "
        "FROM mosaic_panels mp JOIN mosaics m ON mp.mosaic_id = m.id"
    )).fetchall()

    for panel in panels:
        panel_id = panel.panel_id
        target_id = panel.target_id
        pattern = panel.object_pattern

        if pattern:
            dates = conn.execute(sa.text(
                "SELECT DISTINCT session_date FROM images "
                "WHERE resolved_target_id = :tid AND image_type = 'LIGHT' "
                "AND raw_headers->>'OBJECT' ILIKE :pat AND session_date IS NOT NULL"
            ), {"tid": target_id, "pat": pattern}).fetchall()
        else:
            dates = conn.execute(sa.text(
                "SELECT DISTINCT session_date FROM images "
                "WHERE resolved_target_id = :tid AND image_type = 'LIGHT' "
                "AND session_date IS NOT NULL"
            ), {"tid": target_id}).fetchall()

        for row in dates:
            conn.execute(sa.text(
                "INSERT INTO mosaic_panel_sessions (id, panel_id, session_date, status) "
                "VALUES (gen_random_uuid(), :panel_id, :session_date, 'available') "
                "ON CONFLICT (panel_id, session_date) DO NOTHING"
            ), {"panel_id": panel_id, "session_date": row.session_date})

    # Mark all existing mosaics as needs_review
    conn.execute(sa.text("UPDATE mosaics SET needs_review = true"))


def downgrade() -> None:
    op.drop_table("mosaic_panel_sessions")
    if _column_exists("mosaics", "needs_review"):
        op.drop_column("mosaics", "needs_review")
    if _column_exists("mosaic_suggestions", "session_dates"):
        op.drop_column("mosaic_suggestions", "session_dates")
