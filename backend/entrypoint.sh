#!/bin/bash
set -e

echo "Running database migrations..."

# Check if alembic_version table exists. If the DB has tables but no
# alembic tracking (created by Base.metadata.create_all), stamp at head
# since create_all produces the current schema. This makes deployment
# safe for existing installs — future migrations will run incrementally.
HAS_ALEMBIC=$(python -c "
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
" 2>/dev/null || echo "no")

if [ "$HAS_ALEMBIC" = "no" ]; then
    # Check if the images table exists (i.e. DB was created by create_all)
    HAS_IMAGES=$(python -c "
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
" 2>/dev/null || echo "no")

    if [ "$HAS_IMAGES" = "yes" ]; then
        echo "Existing database detected without alembic tracking — stamping at head"
        alembic stamp head
    fi
fi

# Capture alembic output to detect what happened
ALEMBIC_OUTPUT=$(alembic upgrade head 2>&1) || ALEMBIC_EXIT=$?
ALEMBIC_EXIT=${ALEMBIC_EXIT:-0}
echo "$ALEMBIC_OUTPUT"

# Post migration result to Redis activity feed so it shows in the UI
python -c "
import json, time, sys, os
try:
    import redis
    r = redis.from_url(os.environ.get('GALACTILOG_REDIS_URL', 'redis://redis:6379/0'))
    output = '''$ALEMBIC_OUTPUT'''
    exit_code = $ALEMBIC_EXIT
    stamped = '$HAS_ALEMBIC' == 'no' and '$HAS_IMAGES' == 'yes'

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
            'details': {'steps': len(steps), 'stamped': stamped},
            'timestamp': time.time(),
        }
    elif stamped:
        entry = {
            'type': 'migration_initialized',
            'message': 'Database migration tracking initialized (existing database detected)',
            'details': {'stamped': True},
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

if [ $ALEMBIC_EXIT -ne 0 ]; then
    echo "ERROR: Database migration failed!"
    exit 1
fi

echo "Migrations complete."

# Dispatch data migrations if needed (runs in Celery background after services start)
DATA_RESULT=$(python -c "
from sqlalchemy import create_engine, text
from app.config import settings
url = settings.database_url.replace('+asyncpg', '+psycopg2')
eng = create_engine(url)
with eng.connect() as c:
    has_table = c.execute(text(
        \"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'app_metadata')\"
    )).scalar()
    if not has_table:
        print('current')
    else:
        row = c.execute(text(
            \"SELECT value FROM app_metadata WHERE key = 'data_version'\"
        )).first()
        current = int(row[0]) if row else 0
        from app.services.data_migrations import DATA_VERSION
        if current < DATA_VERSION:
            print(f'{current}')
        else:
            print('current')
eng.dispose()
" 2>/dev/null || echo "current")

if [ "$DATA_RESULT" != "current" ]; then
    echo "Data version v${DATA_RESULT} is behind — scheduling background upgrade..."
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
    echo "Data version is current — scheduling startup maintenance..."
    python -c "
from app.worker.tasks import smart_rebuild_targets, detect_mosaic_panels_task
smart_rebuild_targets.apply_async(countdown=10)
detect_mosaic_panels_task.apply_async(countdown=30)
" 2>&1 || echo "Warning: could not dispatch startup maintenance tasks"
fi

echo "Starting services..."
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
