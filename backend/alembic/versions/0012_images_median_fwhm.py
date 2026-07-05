"""Add median_fwhm column to the images table.

The FITS/XISF scanner previously routed FWHM/MEANFWHM header values into
median_hfr, conflating two different metrics on different numeric scales
(AUD-007). FWHM parsed from headers now lands in its own median_fwhm column,
kept separate from median_hfr and from the CSV-sourced `fwhm` column.

The add uses a defensive column-existence guard so the migration is safe on
installs bootstrapped via create_all then stamped (see CLAUDE.md and 0006).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0012"
down_revision = "0011"
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
        "images", sa.Column("median_fwhm", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    if _column_exists("images", "median_fwhm"):
        op.drop_column("images", "median_fwhm")
