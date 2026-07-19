"""Add images.arcsec_per_pixel, the materialized plate scale.

Nullable float: 206.265 * XPIXSZ(um) / FOCALLEN(mm), computed at ingest by the
scanner via units.arcsec_per_pixel. NULL when the headers carry no usable pixel
size or focal length. Materialized because deriving the plate scale per-row
from raw_headers JSONB (regex-guarded text casts, units.sql_arcsec_per_pixel)
made cold /api/stats aggregations take tens of seconds.

Plain add_column with no existence guard: guards are reserved for revisions
with a specific stated reason (see 0018's autocommit backfill), and installs
bootstrapped by create_all-then-stamp are no longer supported
(MIN_UPGRADE_FROM_DATA_VERSION = 13).

Schema only. Backfilling existing rows is inference from raw_headers, not a
structural DDL step, so it runs through app.services.data_migrations as data
migration v15, where raw-headers re-derivation already lives and where the
version gate makes it run exactly once (same split as 0019 / v14).

No index: the column is aggregated over full scans (multiplied into HFR/FWHM
conversions), never used as a filter, so a btree would cost every ingest write
for no read. Add one when a query needs it.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "images",
        sa.Column("arcsec_per_pixel", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("images", "arcsec_per_pixel")
