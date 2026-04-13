import math
import statistics
from collections import defaultdict
from datetime import date as date_type, datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, cast, Date, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Image, Target, User
from app.schemas.analysis import (
    BoxPlotGroup,
    BoxPlotResponse,
    CompareGroupStats,
    CompareResponse,
    ConfidenceBandPoint,
    CorrelationPoint,
    CorrelationResponse,
    DistributionResponse,
    HistogramBin,
    MatrixCell,
    MatrixResponse,
    MovingAveragePoint,
    SummaryStats,
    TimeSeriesPoint,
    TimeSeriesResponse,
    TrendLine,
)
from app.services.normalization import load_alias_maps, expand_canonical, normalize_equipment, normalize_filter
from app.api.auth import get_current_user

router = APIRouter(prefix="/analysis", tags=["analysis"])

# ── Metric map ──────────────────────────────────────────────────────────

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

X_METRICS = [
    "humidity", "wind_speed", "ambient_temp", "dew_point", "pressure",
    "cloud_cover", "sky_quality", "focuser_temp", "airmass", "sensor_temp",
]
Y_METRICS = [
    "hfr", "fwhm", "eccentricity", "guiding_rms", "guiding_rms_ra",
    "guiding_rms_dec", "detected_stars", "adu_mean", "adu_median", "adu_stdev",
]


# ── Shared helpers ──────────────────────────────────────────────────────

async def _apply_filters(
    q,
    session: AsyncSession,
    telescope: str | None,
    camera: str | None,
    filter_used: str | None,
    date_from: str | None,
    date_to: str | None,
):
    """Apply shared equipment/date/filter_used filters to a query."""
    if telescope or camera:
        _, cam_aliases, tel_aliases = await load_alias_maps(session)
        if telescope:
            variants = expand_canonical(telescope, tel_aliases)
            q = q.where(Image.telescope.in_(variants))
        if camera:
            variants = expand_canonical(camera, cam_aliases)
            q = q.where(Image.camera.in_(variants))
    if filter_used:
        q = q.where(Image.filter_used == filter_used)
    if date_from:
        q = q.where(Image.session_date >= date_type.fromisoformat(date_from))
    if date_to:
        q = q.where(Image.session_date <= date_type.fromisoformat(date_to))
    return q


async def _resolve_target_names(
    session: AsyncSession, target_ids: set,
) -> dict:
    """Batch-resolve target IDs to primary names."""
    if not target_ids:
        return {}
    tq = select(Target.id, Target.primary_name).where(Target.id.in_(target_ids))
    return {t.id: t.primary_name for t in (await session.execute(tq)).all()}


def _compute_summary_stats(values: list[float]) -> SummaryStats | None:
    if len(values) < 2:
        return None
    s = sorted(values)
    n = len(s)
    mean = sum(s) / n
    variance = sum((v - mean) ** 2 for v in s) / (n - 1)
    return SummaryStats(
        count=n,
        min=round(s[0], 6),
        max=round(s[-1], 6),
        mean=round(mean, 6),
        median=round(statistics.median(s), 6),
        std_dev=round(math.sqrt(variance), 6),
    )


def _compute_box_plot(values: list[float], group_name: str) -> BoxPlotGroup | None:
    if len(values) < 4:
        return None
    s = sorted(values)
    n = len(s)
    q1 = statistics.median(s[: n // 2])
    q3 = statistics.median(s[(n + 1) // 2 :])
    med = statistics.median(s)
    iqr = q3 - q1
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr
    whisker_low = min(v for v in s if v >= lower_fence)
    whisker_high = max(v for v in s if v <= upper_fence)
    outliers = [v for v in s if v < lower_fence or v > upper_fence]
    return BoxPlotGroup(
        group_name=group_name,
        min=round(whisker_low, 6),
        q1=round(q1, 6),
        median=round(med, 6),
        q3=round(q3, 6),
        max=round(whisker_high, 6),
        outliers=[round(v, 6) for v in outliers],
        count=n,
    )


def _is_outlier_iqr(x: float, y: float, xs: list[float], ys: list[float]) -> bool:
    """Check if a point is an outlier on either axis using IQR method."""
    for vals, val in [(xs, x), (ys, y)]:
        s = sorted(vals)
        n = len(s)
        q1 = statistics.median(s[: n // 2])
        q3 = statistics.median(s[(n + 1) // 2 :])
        iqr = q3 - q1
        if val < q1 - 1.5 * iqr or val > q3 + 1.5 * iqr:
            return True
    return False


def _pearson_r(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx < 1e-12 or dy < 1e-12:
        return 0.0
    return num / (dx * dy)


def _spearman_rho(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0

    def _rank(vals):
        indexed = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and vals[indexed[j]] == vals[indexed[j + 1]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                ranks[indexed[k]] = avg_rank
            i = j + 1
        return ranks

    rx = _rank(xs)
    ry = _rank(ys)
    return _pearson_r(rx, ry)


def _compute_trend(points: list[CorrelationPoint]) -> TrendLine | None:
    """Linear regression with Pearson r, Spearman rho, and 95% confidence band."""
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
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Confidence band (95%) at evenly spaced x points
    mean_x = sum_x / n
    se = math.sqrt(ss_res / (n - 2)) if n > 2 and ss_res > 0 else 0
    t_val = 1.96 if n > 30 else 2.0

    x_sorted = sorted(xs)
    x_min, x_max = x_sorted[0], x_sorted[-1]
    n_band = min(50, n)
    x_step = (x_max - x_min) / max(n_band - 1, 1)
    band_xs = [x_min + i * x_step for i in range(n_band)]

    sx2 = sum((x - mean_x) ** 2 for x in xs)
    upper, lower = [], []
    for bx in band_xs:
        y_hat = slope * bx + intercept
        h = 1 / n + (bx - mean_x) ** 2 / sx2 if sx2 > 0 else 1 / n
        margin = t_val * se * math.sqrt(h)
        upper.append(ConfidenceBandPoint(x=round(bx, 6), y=round(y_hat + margin, 6)))
        lower.append(ConfidenceBandPoint(x=round(bx, 6), y=round(y_hat - margin, 6)))

    return TrendLine(
        slope=round(slope, 6),
        intercept=round(intercept, 6),
        r_squared=round(r_squared, 4),
        pearson_r=round(_pearson_r(xs, ys), 4),
        spearman_rho=round(_spearman_rho(xs, ys), 4),
        confidence_upper=upper,
        confidence_lower=lower,
    )


# ── Endpoints ───────────────────────────────────────────────────────────

@router.get("/filters", response_model=list[str])
async def get_filters(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return distinct filter_used values from LIGHT frames."""
    q = (
        select(distinct(Image.filter_used))
        .where(Image.image_type == "LIGHT")
        .where(Image.filter_used.is_not(None))
        .order_by(Image.filter_used)
    )
    rows = (await session.execute(q)).scalars().all()
    return list(rows)


@router.get("/correlation", response_model=CorrelationResponse)
async def get_correlation(
    x_metric: str = Query(..., description="X axis metric name"),
    y_metric: str = Query(..., description="Y axis metric name"),
    telescope: str | None = Query(None),
    camera: str | None = Query(None),
    filter_used: str | None = Query(None),
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
            Image.session_date.label("night"),
            Image.resolved_target_id,
        )
        .where(Image.image_type == "LIGHT")
        .where(x_col.is_not(None))
        .where(y_col.is_not(None))
        .where(Image.capture_date.is_not(None))
    )
    q = await _apply_filters(q, session, telescope, camera, filter_used, date_from, date_to)
    rows = (await session.execute(q)).all()

    if granularity == "frame":
        target_ids = {r.resolved_target_id for r in rows if r.resolved_target_id}
        target_names = await _resolve_target_names(session, target_ids)
        raw_points = [
            (float(r.x_val), float(r.y_val), str(r.night), target_names.get(r.resolved_target_id))
            for r in rows
        ]
    else:
        session_groups: dict[tuple, dict] = defaultdict(lambda: {"xs": [], "ys": [], "target_id": None})
        for r in rows:
            key = (str(r.night), r.resolved_target_id)
            session_groups[key]["xs"].append(float(r.x_val))
            session_groups[key]["ys"].append(float(r.y_val))
            session_groups[key]["target_id"] = r.resolved_target_id

        target_ids = {g["target_id"] for g in session_groups.values() if g["target_id"]}
        target_names = await _resolve_target_names(session, target_ids)
        raw_points = [
            (
                statistics.median(g["xs"]),
                statistics.median(g["ys"]),
                night,
                target_names.get(g["target_id"]),
            )
            for (night, _), g in session_groups.items()
        ]

    # Outlier detection
    all_xs = [p[0] for p in raw_points]
    all_ys = [p[1] for p in raw_points]

    points = [
        CorrelationPoint(
            x=x, y=y, date=d, target_name=tn,
            outlier=_is_outlier_iqr(x, y, all_xs, all_ys) if len(raw_points) >= 4 else False,
        )
        for x, y, d, tn in raw_points
    ]

    trend = _compute_trend(points)
    x_stats = _compute_summary_stats(all_xs)
    y_stats = _compute_summary_stats(all_ys)

    return CorrelationResponse(
        points=points,
        trend=trend,
        x_metric=x_metric,
        y_metric=y_metric,
        granularity=granularity,
        x_stats=x_stats,
        y_stats=y_stats,
    )


@router.get("/distribution", response_model=DistributionResponse)
async def get_distribution(
    metric: str = Query(..., description="Metric name"),
    telescope: str | None = Query(None),
    camera: str | None = Query(None),
    filter_used: str | None = Query(None),
    granularity: str = Query("frame", regex="^(frame|session)$"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if metric not in METRIC_MAP:
        raise HTTPException(400, f"Unknown metric: {metric}")

    col = METRIC_MAP[metric]
    q = (
        select(col.label("val"), Image.session_date.label("night"), Image.resolved_target_id)
        .where(Image.image_type == "LIGHT")
        .where(col.is_not(None))
        .where(Image.capture_date.is_not(None))
    )
    q = await _apply_filters(q, session, telescope, camera, filter_used, date_from, date_to)
    rows = (await session.execute(q)).all()

    if granularity == "session":
        groups: dict[tuple, list[float]] = defaultdict(list)
        for r in rows:
            groups[(str(r.night), r.resolved_target_id)].append(float(r.val))
        values = [statistics.median(vs) for vs in groups.values()]
    else:
        values = [float(r.val) for r in rows]

    if len(values) < 2:
        raise HTTPException(400, "Not enough data points for distribution")

    stats = _compute_summary_stats(values)

    # Sturges' rule for bin count
    n_bins = max(1, int(math.ceil(math.log2(len(values)) + 1)))
    v_min, v_max = min(values), max(values)
    bin_width = (v_max - v_min) / n_bins if v_max > v_min else 1.0

    bins = []
    for i in range(n_bins):
        b_start = v_min + i * bin_width
        b_end = b_start + bin_width
        count = sum(1 for v in values if (b_start <= v < b_end) or (i == n_bins - 1 and v == b_end))
        bins.append(HistogramBin(bin_start=round(b_start, 6), bin_end=round(b_end, 6), count=count))

    # Skewness (Fisher)
    mean = stats.mean
    std = stats.std_dev
    n = len(values)
    if std > 0 and n > 2:
        skewness = (n / ((n - 1) * (n - 2))) * sum(((v - mean) / std) ** 3 for v in values)
    else:
        skewness = 0.0

    return DistributionResponse(
        bins=bins,
        stats=stats,
        metric=metric,
        skewness=round(skewness, 4),
    )


@router.get("/boxplot", response_model=BoxPlotResponse)
async def get_boxplot(
    metric: str = Query(..., description="Quality metric name"),
    group_by: str = Query(..., regex="^(filter|equipment|month|target)$"),
    telescope: str | None = Query(None),
    camera: str | None = Query(None),
    filter_used: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if metric not in METRIC_MAP:
        raise HTTPException(400, f"Unknown metric: {metric}")

    col = METRIC_MAP[metric]

    # For equipment and filter grouping, we need to normalize in Python
    # so that grouped aliases are combined under their canonical names.
    if group_by in ("equipment", "filter"):
        extra_cols = [Image.telescope, Image.camera, Image.filter_used]
    elif group_by == "month":
        extra_cols = [func.to_char(Image.capture_date, "YYYY-MM").label("month_grp")]
    else:  # target
        extra_cols = [Image.resolved_target_id]

    q = (
        select(col.label("val"), Image.resolved_target_id, *extra_cols)
        .where(Image.image_type == "LIGHT")
        .where(col.is_not(None))
        .where(Image.capture_date.is_not(None))
    )
    q = await _apply_filters(q, session, telescope, camera, filter_used, date_from, date_to)
    rows = (await session.execute(q)).all()

    # Load alias maps for normalization
    filter_map, cam_map, tel_map = await load_alias_maps(session)

    grouped: dict[str, list[float]] = defaultdict(list)
    target_id_map: dict[str, str | None] = {}
    for r in rows:
        if group_by == "equipment":
            tel_norm = normalize_equipment(r.telescope, tel_map) or r.telescope
            cam_norm = normalize_equipment(r.camera, cam_map) or r.camera
            if not tel_norm or not cam_norm:
                continue
            key = f"{tel_norm} + {cam_norm}"
        elif group_by == "filter":
            f = normalize_filter(r.filter_used, filter_map) or r.filter_used
            if not f:
                continue
            key = f
        elif group_by == "month":
            if not r.month_grp:
                continue
            key = str(r.month_grp)
        else:  # target
            if not r.resolved_target_id:
                continue
            key = str(r.resolved_target_id)
            target_id_map[key] = r.resolved_target_id
        grouped[key].append(float(r.val))

    if group_by == "target":
        tid_set = {v for v in target_id_map.values() if v}
        tnames = await _resolve_target_names(session, tid_set)
        resolved_groups: dict[str, list[float]] = {}
        for key, vals in grouped.items():
            tid = target_id_map.get(key)
            name = tnames.get(tid, key) if tid else key
            resolved_groups.setdefault(name, []).extend(vals)
        grouped = resolved_groups

    groups = []
    for name, vals in sorted(grouped.items()):
        bp = _compute_box_plot(vals, name)
        if bp:
            groups.append(bp)

    return BoxPlotResponse(groups=groups, metric=metric, group_by=group_by)


@router.get("/timeseries", response_model=TimeSeriesResponse)
async def get_timeseries(
    metric: str = Query(..., description="Metric name"),
    telescope: str | None = Query(None),
    camera: str | None = Query(None),
    filter_used: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if metric not in METRIC_MAP:
        raise HTTPException(400, f"Unknown metric: {metric}")

    col = METRIC_MAP[metric]
    q = (
        select(
            col.label("val"),
            Image.session_date.label("night"),
            Image.resolved_target_id,
        )
        .where(Image.image_type == "LIGHT")
        .where(col.is_not(None))
        .where(Image.capture_date.is_not(None))
    )
    q = await _apply_filters(q, session, telescope, camera, filter_used, date_from, date_to)
    rows = (await session.execute(q)).all()

    nightly: dict[str, dict] = defaultdict(lambda: {"vals": [], "target_ids": set()})
    for r in rows:
        night = str(r.night)
        nightly[night]["vals"].append(float(r.val))
        if r.resolved_target_id:
            nightly[night]["target_ids"].add(r.resolved_target_id)

    all_tids = set()
    for g in nightly.values():
        all_tids.update(g["target_ids"])
    tnames = await _resolve_target_names(session, all_tids)

    sorted_nights = sorted(nightly.keys())
    points = []
    for night in sorted_nights:
        g = nightly[night]
        tid_list = list(g["target_ids"])
        target_name = tnames.get(tid_list[0]) if tid_list else None
        points.append(TimeSeriesPoint(
            date=night,
            value=round(statistics.median(g["vals"]), 6),
            target_name=target_name,
            frame_count=len(g["vals"]),
        ))

    raw_values = [p.value for p in points]

    def _moving_avg(vals, window):
        result = []
        for i in range(len(vals)):
            start = max(0, i - window + 1)
            chunk = vals[start : i + 1]
            if len(chunk) >= window:
                result.append(MovingAveragePoint(
                    date=points[i].date,
                    value=round(sum(chunk) / len(chunk), 6),
                ))
        return result

    ma_7 = _moving_avg(raw_values, 7)
    ma_30 = _moving_avg(raw_values, 30)

    months_seen = set()
    month_boundaries = []
    for night in sorted_nights:
        ym = night[:7]
        if ym not in months_seen:
            months_seen.add(ym)
            month_boundaries.append(night)

    return TimeSeriesResponse(
        points=points,
        ma_7=ma_7,
        ma_30=ma_30,
        metric=metric,
        month_boundaries=month_boundaries,
    )


@router.get("/matrix", response_model=MatrixResponse)
async def get_matrix(
    telescope: str | None = Query(None),
    camera: str | None = Query(None),
    filter_used: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Compute Pearson r for all X-metric vs Y-metric pairs."""
    all_metrics = list(set(X_METRICS + Y_METRICS))
    cols = [METRIC_MAP[m].label(m) for m in all_metrics]

    q = select(*cols).where(Image.image_type == "LIGHT").where(Image.capture_date.is_not(None))
    q = await _apply_filters(q, session, telescope, camera, filter_used, date_from, date_to)
    rows = (await session.execute(q)).all()

    data: dict[str, list[float | None]] = {m: [] for m in all_metrics}
    for r in rows:
        for m in all_metrics:
            data[m].append(getattr(r, m, None))

    n_rows = len(rows)
    cells = []
    for xm in X_METRICS:
        for ym in Y_METRICS:
            paired_x, paired_y = [], []
            for i in range(n_rows):
                xv, yv = data[xm][i], data[ym][i]
                if xv is not None and yv is not None:
                    paired_x.append(float(xv))
                    paired_y.append(float(yv))
            n_points = len(paired_x)
            if n_points >= 10:
                r_val = _pearson_r(paired_x, paired_y)
                cells.append(MatrixCell(x_metric=xm, y_metric=ym, pearson_r=round(r_val, 4), n_points=n_points))
            else:
                cells.append(MatrixCell(x_metric=xm, y_metric=ym, pearson_r=None, n_points=n_points))

    return MatrixResponse(cells=cells, x_metrics=X_METRICS, y_metrics=Y_METRICS)


@router.get("/compare", response_model=CompareResponse)
async def get_compare(
    metric: str = Query(..., description="Quality metric to compare"),
    mode: str = Query(..., regex="^(equipment|filter)$"),
    group_a: str = Query(..., description="First group identifier"),
    group_b: str = Query(..., description="Second group identifier"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if metric not in METRIC_MAP:
        raise HTTPException(400, f"Unknown metric: {metric}")

    col = METRIC_MAP[metric]

    async def _fetch_values(group: str) -> list[float]:
        q = (
            select(col.label("val"))
            .where(Image.image_type == "LIGHT")
            .where(col.is_not(None))
            .where(Image.capture_date.is_not(None))
        )
        if date_from:
            q = q.where(Image.session_date >= date_type.fromisoformat(date_from))
        if date_to:
            q = q.where(Image.session_date <= date_type.fromisoformat(date_to))

        if mode == "equipment":
            parts = group.split("|||")
            if len(parts) == 2:
                tel, cam = parts
                _, cam_aliases, tel_aliases = await load_alias_maps(session)
                if tel:
                    q = q.where(Image.telescope.in_(expand_canonical(tel, tel_aliases)))
                if cam:
                    q = q.where(Image.camera.in_(expand_canonical(cam, cam_aliases)))
        else:
            q = q.where(Image.filter_used == group)

        rows = (await session.execute(q)).all()
        return [float(r.val) for r in rows]

    vals_a = await _fetch_values(group_a)
    vals_b = await _fetch_values(group_b)

    if len(vals_a) < 4 or len(vals_b) < 4:
        raise HTTPException(400, "Not enough data in one or both groups (need at least 4 points each)")

    box_a = _compute_box_plot(vals_a, group_a)
    box_b = _compute_box_plot(vals_b, group_b)
    stats_a = _compute_summary_stats(vals_a)
    stats_b = _compute_summary_stats(vals_b)

    if stats_a.median != 0:
        pct_diff = abs(stats_a.median - stats_b.median) / abs(stats_a.median) * 100
    elif stats_b.median != 0:
        pct_diff = abs(stats_a.median - stats_b.median) / abs(stats_b.median) * 100
    else:
        pct_diff = 0

    if stats_a.median < stats_b.median:
        verdict = f"{group_a} has {pct_diff:.0f}% lower median than {group_b} (N={stats_a.count} vs N={stats_b.count})"
    elif stats_b.median < stats_a.median:
        verdict = f"{group_b} has {pct_diff:.0f}% lower median than {group_a} (N={stats_b.count} vs N={stats_a.count})"
    else:
        verdict = f"Both groups have identical median values (N={stats_a.count} vs N={stats_b.count})"

    return CompareResponse(
        group_a=CompareGroupStats(name=group_a, box=box_a, stats=stats_a),
        group_b=CompareGroupStats(name=group_b, box=box_b, stats=stats_b),
        metric=metric,
        mode=mode,
        verdict=verdict,
    )
