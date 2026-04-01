"""Quick perf test for the targets endpoint phases."""
import asyncio
import time
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import engine
from app.models import Image, Target

SQL = """
WITH grouped AS (
    SELECT coalesce(CAST(i.resolved_target_id AS VARCHAR),
           concat('obj:', coalesce(i.raw_headers->>'OBJECT', '__uncategorized__'))) AS target_key,
           coalesce(min(t.primary_name), min(i.raw_headers->>'OBJECT'), 'Uncategorized') AS primary_name,
           sum(coalesce(i.exposure_time, 0)) AS total_integration,
           count(i.id) AS total_frames,
           count(distinct CAST(i.capture_date AS DATE)) AS session_count
    FROM images i LEFT JOIN targets t ON i.resolved_target_id = t.id
    WHERE i.image_type = 'LIGHT' AND (i.resolved_target_id IS NULL OR t.merged_into_id IS NULL)
    GROUP BY 1
),
agg AS (SELECT count(*) AS tc, sum(total_integration) AS ti, sum(total_frames) AS tf FROM grouped),
page AS (SELECT * FROM grouped ORDER BY total_integration DESC LIMIT 25 OFFSET 0)
SELECT (SELECT tc FROM agg), (SELECT ti FROM agg), (SELECT tf FROM agg),
       p.target_key, p.primary_name, p.total_integration, p.total_frames, p.session_count
FROM page p
"""

async def main():
    async with AsyncSession(engine) as session:
        # Phase 1-3: raw SQL
        t0 = time.perf_counter()
        r1 = await session.execute(text(SQL))
        rows = r1.all()
        t1 = time.perf_counter()
        print(f"Phase 1-3 (raw SQL text): {(t1-t0)*1000:.0f}ms, {len(rows)} rows")

        # Phase 4: ORM detail query (simulating what the endpoint does)
        import uuid
        uuids = [uuid.UUID(r[3]) for r in rows if not r[3].startswith("obj:")]
        t2 = time.perf_counter()
        detail = await session.execute(
            select(Image, Target)
            .outerjoin(Target, Image.resolved_target_id == Target.id)
            .where(Image.image_type == "LIGHT", Image.resolved_target_id.in_(uuids))
        )
        detail_rows = detail.all()
        t3 = time.perf_counter()
        print(f"Phase 4 (ORM detail):     {(t3-t2)*1000:.0f}ms, {len(detail_rows)} rows")

        # Phase 4 alt: column-only select
        from sqlalchemy import cast
        import sqlalchemy as sa
        t4 = time.perf_counter()
        detail2 = await session.execute(
            select(
                cast(Image.resolved_target_id, sa.String).label("tid"),
                Image.raw_headers["OBJECT"].astext.label("obj"),
                Image.exposure_time, Image.filter_used, Image.camera,
                Image.telescope, Image.capture_date,
            )
            .outerjoin(Target, Image.resolved_target_id == Target.id)
            .where(Image.image_type == "LIGHT", Image.resolved_target_id.in_(uuids))
        )
        detail2_rows = detail2.all()
        t5 = time.perf_counter()
        print(f"Phase 4 (column select):  {(t5-t4)*1000:.0f}ms, {len(detail2_rows)} rows")

        # Phase 4 alt2: raw SQL text
        t6 = time.perf_counter()
        detail3 = await session.execute(
            text("SELECT CAST(i.resolved_target_id AS VARCHAR), i.raw_headers->>'OBJECT', "
                 "i.exposure_time, i.filter_used, i.camera, i.telescope, i.capture_date "
                 "FROM images i LEFT JOIN targets t ON i.resolved_target_id = t.id "
                 "WHERE i.image_type = 'LIGHT' AND i.resolved_target_id = ANY(:uuids)"),
            {"uuids": [str(u) for u in uuids]},
        )
        detail3_rows = detail3.all()
        t7 = time.perf_counter()
        print(f"Phase 4 (raw SQL text):   {(t7-t6)*1000:.0f}ms, {len(detail3_rows)} rows")

        print(f"\nTOTAL (best combo):       {(t1-t0)*1000 + (t7-t6)*1000:.0f}ms")

asyncio.run(main())
