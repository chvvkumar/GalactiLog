"""Add simbad_cache table for persistent SIMBAD query caching."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simbad_cache",
        sa.Column("query_name", sa.String(255), primary_key=True),
        sa.Column("main_id", sa.String(255), nullable=True),
        sa.Column("raw_aliases", ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("ra", sa.Float, nullable=True),
        sa.Column("dec", sa.Float, nullable=True),
        sa.Column("object_type", sa.String(100), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("simbad_cache")
