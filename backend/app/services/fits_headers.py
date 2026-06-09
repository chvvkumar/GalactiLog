"""Helpers for querying FITS header metadata across stored images."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_distinct_fits_keys(session: AsyncSession) -> list[str]:
    """Return the sorted distinct set of FITS header keys across all images.

    The query expands raw_headers (JSONB) via jsonb_object_keys(), which is a
    full table scan with no index path.  This is intentionally left as-is because
    the caller (settings API) caches the result in Redis for ~1 hour, so the
    expensive scan runs at most once per hour.

    A functional GIN index on jsonb_object_keys(raw_headers) would help, but
    PostgreSQL does not support that directly.  A partial workaround is a GIN
    index on the raw_headers column itself (`CREATE INDEX ... USING gin
    (raw_headers)`), which would accelerate key-existence checks (`? operator`)
    but does NOT help ORDER-BY-key scans over the expanded set.  Given the
    effective Redis caching, no index is added here.  If caching is ever removed,
    revisit with a materialized view or denormalized keys column.
    """
    result = await session.execute(
        text("SELECT DISTINCT key FROM images, jsonb_object_keys(raw_headers) AS key ORDER BY key")
    )
    return [row[0] for row in result.all()]
