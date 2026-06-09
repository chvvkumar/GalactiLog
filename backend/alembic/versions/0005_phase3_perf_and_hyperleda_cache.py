"""Phase 3 performance work and the HyperLEDA cache table.

Combines three schema changes into a single new Alembic head:

(a) PERF-4: composite index images(image_type, session_date)
    -> ix_images_type_session_date. Speeds up queries that filter by
    image_type and group/filter by session_date together. Created
    CONCURRENTLY (autocommit_block) to avoid locking the large images table,
    consistent with 0003.

(b) PERF-8 (index side): the fits-keys distinct-key query runs
    SELECT DISTINCT key FROM images, jsonb_object_keys(raw_headers).
    jsonb_object_keys is a set-returning function evaluated per row, so no
    btree or GIN index can serve a sorted DISTINCT over the expanded keys.
    The existing ix_images_raw_headers (GIN) does not help either. There is
    no non-no-op index for this query, so none is added here; the query-side
    lane handles it via caching.

(c) BUG-hyperleda: create the hyperleda_cache table backing
    app.models.hyperleda_cache.HyperLEDACache (used by
    app.services.hyperleda). Plain CREATE TABLE inside the normal
    transaction, guarded by an information_schema table-existence check so it
    is safe on installs bootstrapped via create_all.

The CONCURRENTLY index uses op.get_context().autocommit_block(), the official
Alembic API for issuing CONCURRENTLY outside a transaction block (see 0003).
IF NOT EXISTS / IF EXISTS and the table-existence guard keep each statement
idempotent.
"""
from alembic import op
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.dialects.postgresql import UUID  # noqa: F401  (kept for parity with other migrations)
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    inspector = sa_inspect(op.get_bind())
    return table in inspector.get_table_names()


def upgrade() -> None:
    # (c) hyperleda_cache table -- plain CREATE TABLE in the normal
    # transaction, guarded for create_all-bootstrapped installs.
    if not _table_exists("hyperleda_cache"):
        op.create_table(
            "hyperleda_cache",
            sa.Column("catalog_id", sa.String(50), primary_key=True),
            sa.Column("t_type", sa.Float, nullable=True),
            sa.Column("inclination", sa.Float, nullable=True),
            sa.Column(
                "fetched_at",
                sa.DateTime(timezone=True),
                server_default=text("now()"),
                nullable=False,
            ),
        )

    # (a) PERF-4 composite index on the large images table -- CONCURRENTLY,
    # outside any transaction block.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_images_type_session_date"
            " ON images (image_type, session_date)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_images_type_session_date")

    op.execute(text("DROP TABLE IF EXISTS hyperleda_cache"))
