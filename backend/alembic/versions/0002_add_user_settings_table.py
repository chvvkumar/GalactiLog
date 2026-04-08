"""Add user_settings table for application configuration."""
import json
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SETTINGS_ROW_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

DEFAULT_GENERAL = {
    "auto_scan_enabled": True,
    "auto_scan_interval": 240,
    "thumbnail_width": 800,
    "default_page_size": 50,
}

DEFAULT_FILTERS = {
    "Ha": {"color": "#e74c3c", "aliases": ["ha"]},
    "OIII": {"color": "#3498db", "aliases": ["Oiii", "O"]},
    "SII": {"color": "#f39c12", "aliases": ["Sii", "S"]},
    "L": {"color": "#ffffff", "aliases": []},
    "R": {"color": "#e74c3c", "aliases": []},
    "G": {"color": "#2ecc71", "aliases": []},
    "B": {"color": "#3498db", "aliases": []},
    "IR": {"color": "#9b59b6", "aliases": ["ir"]},
}

def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("general", JSONB, nullable=False, server_default="{}"),
        sa.Column("filters", JSONB, nullable=False, server_default="{}"),
        sa.Column("equipment", JSONB, nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        if_not_exists=True,
    )
    # Seed single row with defaults (ON CONFLICT for stamped installs)
    general_json = json.dumps(DEFAULT_GENERAL)
    filters_json = json.dumps(DEFAULT_FILTERS)
    equipment_json = json.dumps({"cameras": {}, "telescopes": {}})
    op.execute(sa.text(
        "INSERT INTO user_settings (id, general, filters, equipment) "
        "VALUES (:id::uuid, :general::jsonb, :filters::jsonb, :equipment::jsonb) "
        "ON CONFLICT (id) DO NOTHING"
    ), {
        "id": str(SETTINGS_ROW_ID),
        "general": general_json,
        "filters": filters_json,
        "equipment": equipment_json,
    })

def downgrade() -> None:
    op.drop_table("user_settings")
