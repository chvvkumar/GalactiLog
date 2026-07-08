"""Add catalog_cache table and copy data from the five per-source caches.

Introduces one generic point-lookup cache table (source, key, payload JSONB,
negative, fetched_at) intended to eventually replace simbad_cache,
sesame_cache, vizier_cache, hyperleda_cache, and gaia_cache (Phase 4 of the
retrofit roadmap). This migration only creates the table and backfills it
from the five existing tables -- it does not touch the five services (they
keep reading/writing their own tables until each is ported in a later,
separate change) and it does not drop the old tables (deferred to after a
soak period).

Column mapping per source (old table -> new row):
  simbad_cache:    source='simbad',    key=query_name,        negative = main_id IS NULL
  sesame_cache:    source='sesame',    key=query_name,        negative = main_id IS NULL
  vizier_cache:    source='vizier',    key=catalog_id,        negative = size_major IS NULL AND size_minor IS NULL
  hyperleda_cache: source='hyperleda', key=catalog_id,        negative = t_type IS NULL AND inclination IS NULL
  gaia_cache:      source='gaia',      key=target_id::text,   negative = distance_pc IS NULL

A negative row's payload is NULL; a positive row's payload is a JSONB object
of that source's non-key/non-fetched_at columns. fetched_at copies straight
across. The copy is idempotent (ON CONFLICT (source, key) DO NOTHING) so a
rerun after a partial prior apply is safe, and each old table's copy is
guarded so a legacy install missing one of the five tables doesn't fail the
whole migration.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("catalog_cache"):
        op.create_table(
            "catalog_cache",
            sa.Column("source", sa.String(32), primary_key=True, nullable=False),
            sa.Column("key", sa.String(255), primary_key=True, nullable=False),
            sa.Column("payload", JSONB(), nullable=True),
            sa.Column("negative", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column(
                "fetched_at", sa.DateTime(timezone=True), nullable=False,
                server_default=sa.func.now(),
            ),
        )

    existing_tables = set(inspector.get_table_names())

    if "simbad_cache" in existing_tables:
        bind.execute(sa.text("""
            INSERT INTO catalog_cache (source, key, payload, negative, fetched_at)
            SELECT
                'simbad',
                query_name,
                CASE WHEN main_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'main_id', main_id,
                    'raw_aliases', to_jsonb(raw_aliases),
                    'ra', ra,
                    'dec', dec,
                    'object_type', object_type
                ) END,
                main_id IS NULL,
                fetched_at
            FROM simbad_cache
            ON CONFLICT (source, key) DO NOTHING
        """))

    if "sesame_cache" in existing_tables:
        bind.execute(sa.text("""
            INSERT INTO catalog_cache (source, key, payload, negative, fetched_at)
            SELECT
                'sesame',
                query_name,
                CASE WHEN main_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'main_id', main_id,
                    'raw_aliases', to_jsonb(raw_aliases),
                    'ra', ra,
                    'dec', dec,
                    'object_type', object_type,
                    'resolver', resolver
                ) END,
                main_id IS NULL,
                fetched_at
            FROM sesame_cache
            ON CONFLICT (source, key) DO NOTHING
        """))

    if "vizier_cache" in existing_tables:
        bind.execute(sa.text("""
            INSERT INTO catalog_cache (source, key, payload, negative, fetched_at)
            SELECT
                'vizier',
                catalog_id,
                CASE WHEN size_major IS NULL AND size_minor IS NULL THEN NULL ELSE jsonb_build_object(
                    'vizier_catalog', vizier_catalog,
                    'size_major', size_major,
                    'size_minor', size_minor,
                    'constellation', constellation
                ) END,
                (size_major IS NULL AND size_minor IS NULL),
                fetched_at
            FROM vizier_cache
            ON CONFLICT (source, key) DO NOTHING
        """))

    if "hyperleda_cache" in existing_tables:
        bind.execute(sa.text("""
            INSERT INTO catalog_cache (source, key, payload, negative, fetched_at)
            SELECT
                'hyperleda',
                catalog_id,
                CASE WHEN t_type IS NULL AND inclination IS NULL THEN NULL ELSE jsonb_build_object(
                    't_type', t_type,
                    'inclination', inclination
                ) END,
                (t_type IS NULL AND inclination IS NULL),
                fetched_at
            FROM hyperleda_cache
            ON CONFLICT (source, key) DO NOTHING
        """))

    if "gaia_cache" in existing_tables:
        bind.execute(sa.text("""
            INSERT INTO catalog_cache (source, key, payload, negative, fetched_at)
            SELECT
                'gaia',
                target_id::text,
                CASE WHEN distance_pc IS NULL THEN NULL ELSE jsonb_build_object(
                    'distance_pc', distance_pc,
                    'parallax_count', parallax_count
                ) END,
                distance_pc IS NULL,
                fetched_at
            FROM gaia_cache
            ON CONFLICT (source, key) DO NOTHING
        """))


def downgrade() -> None:
    op.drop_table("catalog_cache")
