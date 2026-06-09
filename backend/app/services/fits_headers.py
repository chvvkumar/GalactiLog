"""Helpers for querying FITS header metadata across stored images."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_distinct_fits_keys(session: AsyncSession) -> list[str]:
    """Return the sorted distinct set of FITS header keys across all images."""
    result = await session.execute(
        text("SELECT DISTINCT key FROM images, jsonb_object_keys(raw_headers) AS key ORDER BY key")
    )
    return [row[0] for row in result.all()]
