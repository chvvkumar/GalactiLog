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

alembic upgrade head
echo "Migrations complete."

echo "Starting services..."
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
