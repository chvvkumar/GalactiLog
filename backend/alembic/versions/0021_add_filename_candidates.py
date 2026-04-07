"""add filename_candidates table

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-07
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS filename_candidates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            extracted_name VARCHAR(255),
            suggested_target_id UUID REFERENCES targets(id),
            method VARCHAR(50) NOT NULL DEFAULT 'none',
            confidence FLOAT NOT NULL DEFAULT 0.0,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            file_count INTEGER NOT NULL DEFAULT 0,
            file_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
            image_ids UUID[] NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT now(),
            resolved_at TIMESTAMPTZ
        )
    """)


def downgrade() -> None:
    op.drop_table("filename_candidates")
