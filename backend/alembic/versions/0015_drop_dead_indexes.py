"""Drop indexes with zero live query consumers.

Production idx_scan telemetry showed 0 scans for a handful of indexes. Each was
re-checked against the current codebase (not just the original audit snapshot)
before being dropped here, and only indexes with genuinely no query shape that
could use them were kept in this migration:

- ``ix_images_adu_mean``: adu_mean is only ever filtered inside a HAVING clause
  over ``avg(i.adu_mean)`` (target_aggregation.py metric-range filters), which
  aggregates before the HAVING check runs and can never use a plain per-row
  btree index. The other adu_mean read sites (analysis.py correlation) only do
  ``IS NOT NULL``, not a value comparison.
- ``ix_mosaic_suggestions_dedup_signature``: the only read of dedup_signature
  filters ``IS NOT NULL`` (paired with status = 'rejected', which is the
  selective predicate); matching against a specific signature value happens in
  Python after loading the rejected rows, never as a SQL equality lookup, so a
  btree on the column serves no query.
- ``idx_activity_target``: no code path filters activity_events by target_id
  at all (the partial index predicate ``WHERE target_id IS NOT NULL`` never
  gets exercised).

Other candidates from the same audit list were investigated and are NOT
dropped here because a live, equality-shaped consumer was found for each:
``ix_site_dark_hours_lat_lon`` (worker/tasks.py dark-hours backfill,
api/stats.py integration-time lookup both filter latitude= AND longitude=),
``ix_custom_column_values_column`` (custom_columns.py, backup.py,
worker/tasks.py, target_aggregation.py all filter/`.in_()` on column_id),
``ix_tcm_catalog_name`` (target_aggregation.py's dashboard "filter by catalog"
EXISTS subquery filters catalog_name directly), and both ``merge_manifests``
indexes (target_merge.py/api/merges.py look up manifests by winner_id AND
loser_id during unmerge/revert). Zero recorded scans for those in production
is most likely explained by small table sizes making Postgres prefer a
sequential scan regardless of the available index, not a broken query shape;
dropping them would remove headroom that matters once those tables grow.

The three ``targets`` trgm/alias indexes (ix_targets_primary_name_trgm,
ix_targets_catalog_id_trgm, ix_targets_aliases) are a separate, deliberate
exception and are not touched by this migration at all -- see the campaign
notes for that investigation.

Defensive per project convention: ``DROP INDEX IF EXISTS`` so this is
idempotent regardless of the starting DB state, and ``downgrade()`` recreates
each index (also defensively) in case a rollback is ever needed.

Index-only change: no DATA_VERSION bump (no target derivation logic changed).
"""
from alembic import op


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_images_adu_mean")
    op.execute("DROP INDEX IF EXISTS ix_mosaic_suggestions_dedup_signature")
    op.execute("DROP INDEX IF EXISTS idx_activity_target")


def downgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_images_adu_mean ON images (adu_mean)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_mosaic_suggestions_dedup_signature "
        "ON mosaic_suggestions (dedup_signature)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_target "
        "ON activity_events (target_id) WHERE target_id IS NOT NULL"
    )
