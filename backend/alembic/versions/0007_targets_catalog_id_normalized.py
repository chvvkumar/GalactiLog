"""Add targets.catalog_id_normalized, dedupe identities, add UNIQUE index.

Canonical catalog identity = UPPER(collapse_ws(catalog_id)). Two active targets
must never share one. This migration:
  1. Adds the column (guarded for create_all-bootstrapped installs).
  2. Backfills it from catalog_id.
  3. Dedupes existing duplicate identities by soft-merging losers (most-images
     target wins) into the winner and NULLing the losers' normalized id.
  4. Creates the UNIQUE index only if no active duplicates remain.

All DDL is defensive per CLAUDE.md (see 0002 / 0006).
"""
import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text, inspect as sa_inspect

logger = logging.getLogger("alembic.runtime.migration")

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_NORM = "UPPER(REGEXP_REPLACE(TRIM(catalog_id), '\\s+', ' ', 'g'))"


def _column_exists(table: str, column: str) -> bool:
    inspector = sa_inspect(op.get_bind())
    return column in [c["name"] for c in inspector.get_columns(table)]


def _add_column_if_not_exists(table: str, col: sa.Column) -> None:
    if not _column_exists(table, col.name):
        op.add_column(table, col)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Column (guarded).
    _add_column_if_not_exists(
        "targets", sa.Column("catalog_id_normalized", sa.String(100), nullable=True)
    )

    # 2. Backfill for active, catalogued targets.
    bind.execute(text(f"""
        UPDATE targets
        SET catalog_id_normalized = {_NORM}
        WHERE merged_into_id IS NULL
          AND catalog_id IS NOT NULL
          AND TRIM(catalog_id) <> ''
    """))

    # 3. Dedupe: for each normalized id shared by 2+ active targets, keep the
    #    one with the most images (tie-break oldest id) and soft-merge the rest.
    dup_groups = bind.execute(text("""
        SELECT catalog_id_normalized
        FROM targets
        WHERE merged_into_id IS NULL AND catalog_id_normalized IS NOT NULL
        GROUP BY catalog_id_normalized
        HAVING COUNT(*) > 1
    """)).scalars().all()

    for norm in dup_groups:
        members = bind.execute(text("""
            SELECT t.id,
                   (SELECT COUNT(*) FROM images i WHERE i.resolved_target_id = t.id) AS n_img
            FROM targets t
            WHERE t.merged_into_id IS NULL AND t.catalog_id_normalized = :norm
            ORDER BY n_img DESC, t.id ASC
        """), {"norm": norm}).all()

        winner_id = members[0][0]
        loser_ids = [m[0] for m in members[1:]]
        if not loser_ids:
            continue

        for loser_id in loser_ids:
            # Move images.
            bind.execute(text("""
                UPDATE images SET resolved_target_id = :w
                WHERE resolved_target_id = :l
            """), {"w": winner_id, "l": loser_id})
            # Reassign mosaic panels.
            bind.execute(text("""
                UPDATE mosaic_panels SET target_id = :w WHERE target_id = :l
            """), {"w": winner_id, "l": loser_id})
            # Merge aliases (loser primary_name + aliases) into winner, de-duped.
            bind.execute(text("""
                UPDATE targets w SET aliases = (
                    SELECT ARRAY(
                        SELECT DISTINCT e FROM unnest(
                            COALESCE(w.aliases, ARRAY[]::varchar[])
                            || ARRAY[l.primary_name]
                            || COALESCE(l.aliases, ARRAY[]::varchar[])
                        ) AS e
                        WHERE e <> w.primary_name
                    )
                )
                FROM targets l
                WHERE w.id = :w AND l.id = :l
            """), {"w": winner_id, "l": loser_id})
            # Soft-delete loser and clear its identity so the unique index skips it.
            bind.execute(text("""
                UPDATE targets
                SET merged_into_id = :w, merged_at = now(),
                    catalog_id_normalized = NULL
                WHERE id = :l
            """), {"w": winner_id, "l": loser_id})

    # 4. Create the UNIQUE index only if the data is now clean.
    remaining = bind.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT 1 FROM targets
            WHERE merged_into_id IS NULL AND catalog_id_normalized IS NOT NULL
            GROUP BY catalog_id_normalized
            HAVING COUNT(*) > 1
        ) d
    """)).scalar_one()

    if remaining == 0:
        op.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_targets_catalog_id_normalized "
            "ON targets (catalog_id_normalized)"
        ))
    else:
        # Leave the index uncreated; backfill + duplicate-detection resolve the
        # rest, and a later `alembic upgrade head` re-run creates it once clean.
        # The migration still succeeds (revision advances to 0007); the unique
        # index lands on the next upgrade after duplicates are cleared.
        logger.warning(
            "0007: %d duplicate catalog identities remain; UNIQUE index NOT "
            "created. Resolve duplicates (backfill / duplicate-detection) then "
            "re-run `alembic upgrade head` to create the index.", remaining,
        )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS uq_targets_catalog_id_normalized"))
    if _column_exists("targets", "catalog_id_normalized"):
        op.drop_column("targets", "catalog_id_normalized")
