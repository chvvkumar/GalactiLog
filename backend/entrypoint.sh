#!/bin/bash
set -e

# ---- PUID/PGID handling ----
PUID=${PUID:-1000}
PGID=${PGID:-1000}

# Belt-and-suspenders: ensure runtime dirs exist even if a bind mount shadowed
# them (e.g. dev override mounts ./backend to /app) or the image predates the
# /app/run layout.
mkdir -p /app/run \
         /app/run/nginx/client_body \
         /app/run/nginx/proxy \
         /app/run/nginx/fastcgi \
         /app/run/nginx/uwsgi \
         /app/run/nginx/scgi

CURRENT_UID=$(id -u galactilog)
CURRENT_GID=$(id -g galactilog)

if [ "$PGID" != "$CURRENT_GID" ]; then
    groupmod -o -g "$PGID" galactilog
fi
if [ "$PUID" != "$CURRENT_UID" ]; then
    usermod -o -u "$PUID" galactilog
fi

# Internal runtime dir is container-local; chown is cheap.
chown -R galactilog:galactilog /app/run 2>/dev/null || true

DID_CHOWN=0
# /app/data/fits is typically a read-only bind mount, so we must NOT recurse
# into /app/data. Shallow chown /app/data itself, recursive chown for
# /app/data/thumbnails (the only dir we actually write into).
# Honor GALACTILOG_SKIP_CHOWN=1 for users who manage ownership themselves.
if [ "${GALACTILOG_SKIP_CHOWN:-0}" != "1" ]; then
    desired="$PUID:$PGID"

    if [ -d /app/data ]; then
        current_owner=$(stat -c '%u:%g' /app/data 2>/dev/null || echo "")
        if [ -n "$current_owner" ] && [ "$current_owner" != "$desired" ]; then
            echo "Adjusting ownership of /app/data from $current_owner to $desired (shallow)..."
            if chown "$PUID:$PGID" /app/data 2>/dev/null; then
                DID_CHOWN=1
            else
                echo "Warning: chown of /app/data failed (likely read-only mount, continuing)"
            fi
        fi
    fi

    if [ -d /app/data/thumbnails ]; then
        current_owner=$(stat -c '%u:%g' /app/data/thumbnails 2>/dev/null || echo "")
        if [ -n "$current_owner" ] && [ "$current_owner" != "$desired" ]; then
            echo "Adjusting ownership of /app/data/thumbnails from $current_owner to $desired (one-time, may take a moment on large directories)..."
            if chown -R "$PUID:$PGID" /app/data/thumbnails 2>/dev/null; then
                DID_CHOWN=1
            else
                echo "Warning: chown of /app/data/thumbnails failed (continuing)"
            fi
        fi
    fi
fi
# ---- end PUID/PGID handling ----

echo "Running database migrations..."

# Run a python DB probe with retries, distinguishing a genuine "no such
# table/row" result (which the probe script itself prints, rc 0) from a
# transient database error (nonzero rc, e.g. connection refused while
# postgres is still starting). Probes that misclassify a connectivity error
# as a definitive "no" can send an existing, populated database down the
# fresh-install code path, so on persistent failure this refuses to start
# rather than falling through to a wrong branch.
run_db_probe() {
    local desc="$1"
    local script="$2"
    local max_attempts=5
    local attempt=1
    local output
    while [ "$attempt" -le "$max_attempts" ]; do
        if output=$(python -c "$script" 2>&1); then
            printf '%s' "$output"
            return 0
        fi
        echo "Warning: $desc probe failed (attempt $attempt/$max_attempts): $output" >&2
        attempt=$((attempt + 1))
        [ "$attempt" -le "$max_attempts" ] && sleep 3
    done
    echo "ERROR: Could not reach the database after $max_attempts attempts while checking: $desc" >&2
    echo "" >&2
    echo "The database has NOT been modified." >&2
    echo "This looks like a transient database connectivity issue rather than a" >&2
    echo "fresh or unrecognized database, so startup is refusing to guess." >&2
    exit 1
}

# Check if alembic_version table exists. If the DB has tables but no
# alembic tracking (created by Base.metadata.create_all), stamp at head
# since create_all produces the current schema. This makes deployment
# safe for existing installs - future migrations will run incrementally.
HAS_ALEMBIC=$(run_db_probe "alembic_version table check" "
from sqlalchemy import create_engine, text
from app.config import settings
url = settings.database_url.replace('+asyncpg', '+psycopg2')
eng = create_engine(url)
with eng.connect() as c:
    r = c.execute(text(
        \"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'alembic_version')\"
    ))
    print('yes' if r.scalar() else 'no')
eng.dispose()
")

if [ "$HAS_ALEMBIC" = "no" ]; then
    # Check if the images table exists (i.e. DB has data but no alembic
    # tracking). Post-squash, this can only mean a pre-checkpoint (pre-v2.0)
    # install: the migration history that used to let us safely assume
    # create_all's schema matched "stamp head" no longer exists in this tree,
    # so silently stamping would claim a schema state the database was never
    # actually migrated to. Refuse and point at the checkpoint image, same as
    # the unknown-revision gate below.
    HAS_IMAGES=$(run_db_probe "images table check" "
from sqlalchemy import create_engine, text
from app.config import settings
url = settings.database_url.replace('+asyncpg', '+psycopg2')
eng = create_engine(url)
with eng.connect() as c:
    r = c.execute(text(
        \"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'images')\"
    ))
    print('yes' if r.scalar() else 'no')
eng.dispose()
")

    if [ "$HAS_IMAGES" = "yes" ]; then
        CHECKPOINT_TAG=$(python -c "from app.config import CHECKPOINT_IMAGE_TAG; print(CHECKPOINT_IMAGE_TAG)" 2>/dev/null || echo "unknown")
        MIN_REV=$(python -c "from app.config import MIN_UPGRADE_FROM_ALEMBIC_REVISION; print(MIN_UPGRADE_FROM_ALEMBIC_REVISION)" 2>/dev/null || echo "unknown")
        echo "ERROR: Database has existing tables but no alembic tracking."
        echo ""
        echo "The database has NOT been modified."
        echo ""
        echo "This database predates alembic tracking entirely, which means it also"
        echo "predates the checkpoint release and must first be upgraded through the"
        echo "checkpoint image before this release can proceed."
        echo "This release supports upgrading from revision $MIN_REV or newer."
        echo ""
        echo "Run the checkpoint image first:"
        echo "  $CHECKPOINT_TAG"
        echo ""
        echo "Then retry starting this release."
        exit 1
    fi
else
    # alembic_version exists - check whether the stamped revision is known
    # to this release's migration history. If it is not, the database was
    # last touched by a different release (older or newer, or one whose
    # history was squashed at a checkpoint) and we must refuse to proceed
    # rather than silently rewrite migration state.
    STAMPED_REV=$(run_db_probe "stamped alembic revision read" "
from sqlalchemy import create_engine, text
from app.config import settings
url = settings.database_url.replace('+asyncpg', '+psycopg2')
eng = create_engine(url)
with eng.connect() as c:
    row = c.execute(text('SELECT version_num FROM alembic_version')).first()
    print(row[0] if row else '')
eng.dispose()
")

    REV_KNOWN=$(python -c "
from alembic.config import Config
from alembic.script import ScriptDirectory
cfg = Config('alembic.ini')
scripts = ScriptDirectory.from_config(cfg)
known = {s.revision for s in scripts.walk_revisions()}
print('yes' if '$STAMPED_REV' in known else 'no')
" 2>/dev/null || echo "no")

    if [ "$REV_KNOWN" = "no" ]; then
        CHECKPOINT_TAG=$(python -c "from app.config import CHECKPOINT_IMAGE_TAG; print(CHECKPOINT_IMAGE_TAG)" 2>/dev/null || echo "unknown")
        MIN_REV=$(python -c "from app.config import MIN_UPGRADE_FROM_ALEMBIC_REVISION; print(MIN_UPGRADE_FROM_ALEMBIC_REVISION)" 2>/dev/null || echo "unknown")
        echo "ERROR: Database is stamped at alembic revision '$STAMPED_REV', which this release does not recognize."
        echo ""
        echo "The database has NOT been modified."
        echo ""
        echo "This database was last touched by a different release and must first be"
        echo "upgraded through the checkpoint image before this release can proceed."
        echo "This release supports upgrading from revision $MIN_REV or newer."
        echo ""
        echo "Run the checkpoint image first:"
        echo "  $CHECKPOINT_TAG"
        echo ""
        echo "Then retry starting this release."
        exit 1
    fi
fi

# Capture alembic output to detect what happened
ALEMBIC_OUTPUT=$(alembic upgrade head 2>&1) || ALEMBIC_EXIT=$?
ALEMBIC_EXIT=${ALEMBIC_EXIT:-0}
echo "$ALEMBIC_OUTPUT"

# Post migration result to Redis activity feed so it shows in the UI. The
# alembic output is passed via environment variable rather than interpolated
# into the python source: alembic output can contain quotes/backslashes
# (e.g. from a migration's docstring or an error traceback) that would break
# out of a naively-interpolated triple-quoted string literal.
# Note: the "stamped" (pre-alembic-tracking existing DB) case used to be
# logged here too, but that path now hard-stops above (see the HAS_IMAGES
# check) before alembic ever runs, so it can no longer occur at this point.
export GALACTILOG_ALEMBIC_OUTPUT="$ALEMBIC_OUTPUT"
export GALACTILOG_ALEMBIC_EXIT="$ALEMBIC_EXIT"
python -c "
import json, time, sys, os
try:
    import redis
    r = redis.from_url(os.environ.get('GALACTILOG_REDIS_URL', 'redis://redis:6379/0'))
    output = os.environ.get('GALACTILOG_ALEMBIC_OUTPUT', '')
    exit_code = int(os.environ.get('GALACTILOG_ALEMBIC_EXIT', '0'))

    if exit_code != 0:
        entry = {
            'type': 'migration_failed',
            'message': 'Database migration failed: ' + output.strip()[-200:],
            'details': {'exit_code': exit_code},
            'timestamp': time.time(),
        }
    elif 'Running upgrade' in output:
        # Extract migration steps from output
        steps = [l.strip() for l in output.splitlines() if 'Running upgrade' in l]
        msg = 'Database migrated: ' + '; '.join(
            l.split('Running upgrade ')[-1] for l in steps
        )
        entry = {
            'type': 'migration_applied',
            'message': msg,
            'details': {'steps': len(steps)},
            'timestamp': time.time(),
        }
    else:
        entry = None  # No need to log when schema is already up to date

    if entry is not None:
        r.lpush('scan:activity', json.dumps(entry))
        r.ltrim('scan:activity', 0, 19)
    r.close()
except Exception as e:
    print(f'Warning: could not post migration activity: {e}', file=sys.stderr)
" 2>&1 || true
unset GALACTILOG_ALEMBIC_OUTPUT GALACTILOG_ALEMBIC_EXIT

if [ $ALEMBIC_EXIT -ne 0 ]; then
    echo "ERROR: Database migration failed!"
    exit 1
fi

echo "Migrations complete."

# Check stored data version against this release's minimum supported data
# version before touching anything else. A fresh install (no app_metadata
# table, or no data_version row yet) has nothing to gate on and proceeds
# unchanged; an install at or above the minimum proceeds unchanged too.
# Only an install whose data predates what this release knows how to migrate
# from is refused, so that a future checkpoint release can delete superseded
# data-migration code without breaking upgrades from very old installs.
STORED_DATA_VERSION=$(run_db_probe "stored data version read" "
from sqlalchemy import create_engine, text
from app.config import settings
url = settings.database_url.replace('+asyncpg', '+psycopg2')
eng = create_engine(url)
with eng.connect() as c:
    has_table = c.execute(text(
        \"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'app_metadata')\"
    )).scalar()
    if not has_table:
        print('')
    else:
        row = c.execute(text(
            \"SELECT value FROM app_metadata WHERE key = 'data_version'\"
        )).first()
        print(row[0] if row else '')
eng.dispose()
")

if [ -n "$STORED_DATA_VERSION" ]; then
    MIN_DATA_VERSION=$(python -c "from app.config import MIN_UPGRADE_FROM_DATA_VERSION; print(MIN_UPGRADE_FROM_DATA_VERSION)" 2>/dev/null || echo "")
    if [ -n "$MIN_DATA_VERSION" ] && [ "$STORED_DATA_VERSION" -lt "$MIN_DATA_VERSION" ]; then
        CHECKPOINT_TAG=$(python -c "from app.config import CHECKPOINT_IMAGE_TAG; print(CHECKPOINT_IMAGE_TAG)" 2>/dev/null || echo "unknown")
        echo "ERROR: Database is at data version $STORED_DATA_VERSION, which this release does not support upgrading from."
        echo ""
        echo "The data has NOT been modified."
        echo ""
        echo "This database was last touched by a different release and must first be"
        echo "upgraded through the checkpoint image before this release can proceed."
        echo "This release supports upgrading from data version $MIN_DATA_VERSION or newer."
        echo ""
        echo "Run the checkpoint image first:"
        echo "  $CHECKPOINT_TAG"
        echo ""
        echo "Then retry starting this release."
        exit 1
    fi
fi

# Dispatch data migrations if needed (runs in Celery background after services
# start). Reuses STORED_DATA_VERSION computed above rather than re-querying.
DATA_RESULT=$(python -c "
current = '$STORED_DATA_VERSION'
from app.services.data_migrations import DATA_VERSION
if current == '' or int(current) >= DATA_VERSION:
    print('current')
else:
    print(current)
" 2>/dev/null || echo "current")

if [ "$DATA_RESULT" != "current" ]; then
    echo "Data version v${DATA_RESULT} is behind - scheduling background upgrade..."
    python -c "
import json, time
import redis
import os
r = redis.from_url(os.environ.get('GALACTILOG_REDIS_URL', 'redis://redis:6379/0'))
from app.services.data_migrations import DATA_VERSION
entry = {
    'type': 'data_upgrade_started',
    'message': f'Data upgrade v${DATA_RESULT} -> v{DATA_VERSION} starting in background...',
    'details': {'from_version': ${DATA_RESULT}, 'to_version': DATA_VERSION},
    'timestamp': time.time(),
}
r.lpush('scan:activity', json.dumps(entry))
r.ltrim('scan:activity', 0, 19)
from app.worker.tasks import run_data_migrations
run_data_migrations.apply_async(args=[${DATA_RESULT}])
r.close()
" 2>&1 || echo "Warning: could not dispatch data migration task"
else
    echo "Data version is current - scheduling startup maintenance..."
    python -c "
from app.worker.tasks import smart_rebuild_targets, detect_mosaic_panels_task
smart_rebuild_targets.apply_async(countdown=10)
detect_mosaic_panels_task.apply_async(countdown=30)
" 2>&1 || echo "Warning: could not dispatch startup maintenance tasks"
fi

# Load the static reference catalogs (OpenNGC, SAC, Caldwell, Herschel 400,
# Arp, Abell) if they have never been loaded. Dispatched unconditionally and
# independent of the data-version branch above: the v2.0 baseline seeds fresh
# databases at the current data_version so the upgrade gate holds, which means
# the data migrations that used to load these catalogs as a side effect never
# fire on a fresh install, leaving the catalog tables permanently empty. The
# task itself checks openngc_catalog for emptiness before doing any work, so
# this is a cheap no-op on every other boot.
python -c "
from app.worker.tasks import load_reference_catalogs_if_empty
load_reference_catalogs_if_empty.apply_async(countdown=2)
" 2>&1 || echo "Warning: could not dispatch reference catalog load task"

if [ "$DID_CHOWN" = "1" ]; then
    python -c "
import json, time, os, sys
try:
    import redis
    r = redis.from_url(os.environ.get('GALACTILOG_REDIS_URL', 'redis://redis:6379/0'))
    entry = {
        'type': 'ownership_adjusted',
        'message': 'Data directory ownership aligned to PUID=${PUID} PGID=${PGID}',
        'details': {'puid': ${PUID}, 'pgid': ${PGID}},
        'timestamp': time.time(),
    }
    r.lpush('scan:activity', json.dumps(entry))
    r.ltrim('scan:activity', 0, 19)
    r.close()
except Exception as e:
    print(f'Warning: could not post ownership activity: {e}', file=sys.stderr)
" 2>&1 || true
fi

echo "Starting services..."
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
