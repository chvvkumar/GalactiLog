# Upgrading GalactiLog

## Overview

GalactiLog v2.0 is a checkpoint release that consolidated the migration history and established a clean schema baseline. All releases after v2.0 follow a linear upgrade path from that baseline.

If your install predates v2.0, a one-time hop through the checkpoint image is required before moving to any later release.

## Upgrade Paths

### Fresh Install (No Existing Database)

Download the latest image tag and start normally. On first boot, alembic applies the baseline schema migration (revision 0015) plus any newer linear migrations to the empty database. The baseline seeds the current data version directly, so the background data migration sequence is skipped.

```bash
docker compose up -d
```

### v2.0 or Later to Latest

If your install is already at v2.0 or newer (alembic revision 0015, data version 13 or higher), upgrades proceed linearly. Simply pull the latest image and restart.

```bash
docker compose pull app
docker compose up -d
```

Alembic runs new linear migrations automatically. Each migration is applied once in sequence with no guards or compatibility fallbacks.

### Pre-v2.0 (v1.x or Earlier) to Latest

Installs predating v2.0 must first run the v2.0 checkpoint image once, then move to the latest. The checkpoint converges any schema variant onto a clean baseline.

Do not skip the checkpoint. Attempting to upgrade directly from a pre-v2.0 database to a post-v2.0 release will trigger the boot gate, which refuses to start and instructs you to run the checkpoint first.

#### Step 1: Run Checkpoint Image

Update docker-compose.yml to pin the checkpoint image:

```yaml
services:
  app:
    image: chvvkumar/galactilog:v2.0
```

Start the container and wait for full migration completion:

```bash
docker compose up -d
docker compose logs -f app
```

Watch for "Migrations complete." and "Starting services..." in the logs. This ensures the database is fully converged to the baseline.

The checkpoint image may take longer than usual on first run, especially on large catalogs, because it runs the full historical data migration sequence (SIMBAD curation, constellation computation, OpenNGC/VizieR/SAC enrichment, etc.). Let it finish without interruption.

Once complete, stop the container:

```bash
docker compose down
```

#### Step 2: Move to Latest Image

Update docker-compose.yml to use the latest release or a specific newer tag:

```yaml
services:
  app:
    image: chvvkumar/galactilog:latest
    # Or pin a specific version:
    # image: chvvkumar/galactilog:1.5.2
```

Start normally:

```bash
docker compose up -d
```

Subsequent upgrades skip the checkpoint and proceed linearly.

## Boot Gate Errors

The boot gate runs before migrations and refuses to start with a clear message if the database is too old. No data is modified when the gate refuses.

### Error: Unknown Alembic Revision

```
ERROR: Database is stamped at alembic revision '0012', which this release does not recognize.

The database has NOT been modified.

This database was last touched by a different release and must first be
upgraded through the checkpoint image before this release can proceed.
This release supports upgrading from revision 0015 or newer.

Run the checkpoint image first:
  chvvkumar/galactilog:v2.0

Then retry starting this release.
```

This means the database is at an alembic revision that the current image does not recognize (typically a pre-v2.0 revision like 0001-0014). Run the v2.0 checkpoint image once.

### Error: No Alembic Tracking on Populated Database

```
ERROR: Database has existing tables but no alembic tracking.

The database has NOT been modified.

This database predates alembic tracking entirely, which means it also
predates the checkpoint release and must first be upgraded through the
checkpoint image before this release can proceed.
This release supports upgrading from revision 0015 or newer.

Run the checkpoint image first:
  chvvkumar/galactilog:v2.0

Then retry starting this release.
```

This means the database has tables (images, targets, etc.) but no alembic_version table. This occurs only on installs that bootstrapped via `Base.metadata.create_all` before alembic tracking was added, which predates v2.0. Run the v2.0 checkpoint image once.

### Error: Data Version Too Old

```
ERROR: Database is at data version 8, which this release does not support upgrading from.

The data has NOT been modified.

This database was last touched by a different release and must first be
upgraded through the checkpoint image before this release can proceed.
This release supports upgrading from data version 13 or newer.

Run the checkpoint image first:
  chvvkumar/galactilog:v2.0

Then retry starting this release.
```

This means the database's stored data version (which tracks SIMBAD curation, target enrichment, and other data derivation) is older than what the current release knows how to migrate from. Run the v2.0 checkpoint image once.

## Checkpoint Release Mechanics (Contributors)

### Post-v2.0 Migration Policy

After v2.0, all new migrations are linear. There are no guards, compatibility fallbacks, or information_schema checks.

Do not add `IF NOT EXISTS` clauses to `op.create_table`. Do not use `_add_column_if_not_exists` helpers. Do not check `information_schema` for table/column existence before creating them. Alembic is the sole schema owner.

```python
# INCORRECT (do not add this pattern post-v2.0)
def upgrade() -> None:
    if not table_exists('new_table'):
        op.create_table('new_table', ...)

# CORRECT (post-v2.0 pattern)
def upgrade() -> None:
    op.create_table('new_table', ...)
```

This is safe because:
- Every install running a post-v2.0 migration has already converged to the v2.0 baseline via the checkpoint image or was bootstrapped fresh at a post-v2.0 release.
- The alembic_version table is the source of truth for what migrations have run.
- No install can skip migrations or upgrade from an unknown state.

### Data Version Bumps

When changes to target data derivation logic are made (SIMBAD curation, constellation computation, catalog membership matching, enrichment sources like Gaia/HyperLEDA/VizieR), bump `DATA_VERSION` in `backend/app/services/data_migrations.py` and add a corresponding migration function.

```python
# backend/app/services/data_migrations.py

DATA_VERSION = 14  # Incremented from 13

def _migrate_v14_example(session: Session) -> str:
    """Example migration description."""
    from app.models import Target
    # ... migration logic
    return f"Example: {count} targets updated"

MIGRATIONS: dict[int, tuple[str, Callable[[Session], str]]] = {
    # ... existing entries
    14: ("Example migration description", _migrate_v14_example),
}
```

Data migrations run in the background after boot and are resumable if interrupted. Use the same pacing and chunk-commit pattern as earlier data migrations (e.g., `_migrate_v11_hyperleda_galaxies`) to avoid Celery timeouts on large catalogs.

### Future Checkpoint Releases

Future checkpoint releases may repeat the migration squash pattern. The gate constants live in `backend/app/config.py`:

```python
MIN_UPGRADE_FROM_ALEMBIC_REVISION = "0015"
MIN_UPGRADE_FROM_DATA_VERSION = 13
CHECKPOINT_IMAGE_TAG = "chvvkumar/galactilog:v2.0"
```

At the next checkpoint, these are bumped to the new baseline revision, data version, and image tag. All post-checkpoint migrations again become linear and guard-free.
