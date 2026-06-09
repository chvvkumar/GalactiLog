"""Add HyperLEDA galaxy enrichment columns to the targets table.

app.services.hyperleda.enrich_target_from_hyperleda writes
target.hubble_t_type (Hubble morphological T-type) and target.inclination
(disk inclination in degrees), but no prior migration added these columns.
This adds both as nullable Float columns.

Both adds use a defensive column-existence guard so the migration is safe on
installs bootstrapped via create_all then stamped (see CLAUDE.md and 0002).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    inspector = sa_inspect(op.get_bind())
    return column in [c["name"] for c in inspector.get_columns(table)]


def _add_column_if_not_exists(table: str, col: sa.Column) -> None:
    if not _column_exists(table, col.name):
        op.add_column(table, col)


def upgrade() -> None:
    _add_column_if_not_exists(
        "targets", sa.Column("hubble_t_type", sa.Float(), nullable=True)
    )
    _add_column_if_not_exists(
        "targets", sa.Column("inclination", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    for col in ("inclination", "hubble_t_type"):
        if _column_exists("targets", col):
            op.drop_column("targets", col)
