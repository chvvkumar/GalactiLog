import statistics
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Image, Target, User
from app.schemas.analysis import CorrelationPoint, CorrelationResponse, TrendLine
from app.services.normalization import load_alias_maps, expand_canonical
from app.api.auth import get_current_user

router = APIRouter(prefix="/analysis", tags=["analysis"])

# Allowed metric names mapped to Image model columns
METRIC_MAP = {
    # Environmental / equipment (X axis candidates)
    "humidity": Image.humidity,
    "wind_speed": Image.wind_speed,
    "ambient_temp": Image.ambient_temp,
    "dew_point": Image.dew_point,
    "pressure": Image.pressure,
    "cloud_cover": Image.cloud_cover,
    "sky_quality": Image.sky_quality,
    "focuser_temp": Image.focuser_temp,
    "airmass": Image.airmass,
    "sensor_temp": Image.sensor_temp,
    # Quality (Y axis candidates)
    "hfr": Image.median_hfr,
    "fwhm": Image.fwhm,
    "eccentricity": Image.eccentricity,
    "guiding_rms": Image.guiding_rms_arcsec,
    "guiding_rms_ra": Image.guiding_rms_ra_arcsec,
    "guiding_rms_dec": Image.guiding_rms_dec_arcsec,
    "detected_stars": Image.detected_stars,
    "adu_mean": Image.adu_mean,
    "adu_median": Image.adu_median,
    "adu_stdev": Image.adu_stdev,
}


def _compute_trend(points: list[CorrelationPoint]) -> TrendLine | None:
    """Simple linear regression."""
    if len(points) < 3:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)

    denom = n * sum_x2 - sum_x * sum_x
    if abs(denom) < 1e-12:
        return None

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    # R-squared
    mean_y = sum_y / n
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    return TrendLine(
        slope=round(slope, 6),
        intercept=round(intercept, 6),
        r_squared=round(r_squared, 4),
    )


@router.get("/correlation", response_model=CorrelationResponse)
async def get_correlation(
    x_metric: str = Query(..., description="X axis metric name"),
    y_metric: str = Query(..., description="Y axis metric name"),
    telescope: str | None = Query(None),
    camera: str | None = Query(None),
    granularity: str = Query("frame", regex="^(frame|session)$"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if x_metric not in METRIC_MAP:
        raise HTTPException(400, f"Unknown x_metric: {x_metric}")
    if y_metric not in METRIC_MAP:
        raise HTTPException(400, f"Unknown y_metric: {y_metric}")

    x_col = METRIC_MAP[x_metric]
    y_col = METRIC_MAP[y_metric]

    q = (
        select(
            x_col.label("x_val"),
            y_col.label("y_val"),
            cast(Image.capture_date, Date).label("night"),
            Image.resolved_target_id,
        )
        .where(Image.image_type == "LIGHT")
        .where(x_col.is_not(None))
        .where(y_col.is_not(None))
        .where(Image.capture_date.is_not(None))
    )

    # Equipment filtering with alias expansion
    if telescope or camera:
        _, cam_aliases, tel_aliases = await load_alias_maps(session)
    if telescope:
        variants = expand_canonical(telescope, tel_aliases)
        q = q.where(Image.telescope.in_(variants))
    if camera:
        variants = expand_canonical(camera, cam_aliases)
        q = q.where(Image.camera.in_(variants))

    if date_from:
        q = q.where(Image.capture_date >= datetime.fromisoformat(date_from))
    if date_to:
        q = q.where(Image.capture_date <= datetime.fromisoformat(date_to + "T23:59:59"))

    rows = (await session.execute(q)).all()

    if granularity == "frame":
        # Resolve target names in batch
        target_ids = {r.resolved_target_id for r in rows if r.resolved_target_id}
        target_names = {}
        if target_ids:
            tq = select(Target.id, Target.primary_name).where(Target.id.in_(target_ids))
            target_names = {t.id: t.primary_name for t in (await session.execute(tq)).all()}

        points = [
            CorrelationPoint(
                x=float(r.x_val),
                y=float(r.y_val),
                date=str(r.night),
                target_name=target_names.get(r.resolved_target_id),
            )
            for r in rows
        ]
    else:
        # Session medians: group by (night, target_id)
        session_groups: dict[tuple, dict] = defaultdict(lambda: {"xs": [], "ys": [], "target_id": None})
        for r in rows:
            key = (str(r.night), r.resolved_target_id)
            session_groups[key]["xs"].append(float(r.x_val))
            session_groups[key]["ys"].append(float(r.y_val))
            session_groups[key]["target_id"] = r.resolved_target_id

        target_ids = {g["target_id"] for g in session_groups.values() if g["target_id"]}
        target_names = {}
        if target_ids:
            tq = select(Target.id, Target.primary_name).where(Target.id.in_(target_ids))
            target_names = {t.id: t.primary_name for t in (await session.execute(tq)).all()}

        points = []
        for (night, _), g in session_groups.items():
            points.append(CorrelationPoint(
                x=statistics.median(g["xs"]),
                y=statistics.median(g["ys"]),
                date=night,
                target_name=target_names.get(g["target_id"]),
            ))

    trend = _compute_trend(points)

    return CorrelationResponse(
        points=points,
        trend=trend,
        x_metric=x_metric,
        y_metric=y_metric,
        granularity=granularity,
    )
