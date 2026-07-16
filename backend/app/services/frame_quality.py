"""MAD-based frame-quality baseline math.

Pure functions with no DB access. They compute, for a collection of already
loaded light frames grouped by optical train + filter, a robust baseline
(median + median-absolute-deviation) per graded metric. The frontend turns a
per-frame metric and the matching baseline into a signed z-score and color band.

No new DB columns and no DATA_VERSION bump: baselines are derived on the fly
from existing per-frame data.
"""

import statistics

MIN_GROUP = 8
EPS = 1e-9

# Deviation at which a frame is called an outlier, in RAW MAD units (there is no
# 1.4826 consistency scaling anywhere in this codebase, so these are not sigma).
# The value matches the frontend `bandForZ` "reject" band in
# frontend/src/utils/frameQuality.ts, so a session insight and the per-frame cell
# colours rendered beside it cannot contradict each other.
Z_REJECT = 3.0

# Metrics for which a baseline (median + MAD) is computed per group.
METRICS = [
    "median_hfr",
    "fwhm",
    "eccentricity",
    "detected_stars",
    "adu_median",
    "guiding_rms_arcsec",
]


def median(values):
    """Median of values, ignoring None. Returns None for an empty input.

    For an even count the average of the two middle values is returned, matching
    statistics.median.
    """
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return statistics.median(nums)


def mad(values):
    """Median absolute deviation from the median, ignoring None.

    Returns None for an empty input and 0.0 for a uniform group.
    """
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    m = statistics.median(nums)
    return statistics.median([abs(x - m) for x in nums])


def _get(frame, key):
    """Read a field from a frame that may be a dict or an attribute-bearing object."""
    if isinstance(frame, dict):
        return frame.get(key)
    return getattr(frame, key, None)


def group_key(frame) -> str:
    """Build the train+filter group key matching the frontend `groupKey(frame)`.

    Format: ``"{telescope}|{camera}|{filter_used}"`` with null components
    rendered as an empty string.
    """
    tel = _get(frame, "telescope") or ""
    cam = _get(frame, "camera") or ""
    filt = _get(frame, "filter_used") or ""
    return f"{tel}|{cam}|{filt}"


def group_baselines(frames):
    """Compute per-group, per-metric ``{median, mad, n}`` baselines.

    `frames` may be dicts or attribute-bearing objects. Groups by `group_key`;
    for each metric, n is the count of non-null values for that metric within
    the group.
    """
    groups: dict[str, list] = {}
    for frame in frames:
        groups.setdefault(group_key(frame), []).append(frame)

    out: dict[str, dict] = {}
    for key, group_frames in groups.items():
        metric_stats: dict[str, dict] = {}
        for metric in METRICS:
            vals = [_get(f, metric) for f in group_frames]
            non_null = [v for v in vals if v is not None]
            metric_stats[metric] = {
                "median": median(non_null),
                "mad": mad(non_null),
                "n": len(non_null),
            }
        out[key] = metric_stats
    return out


def mad_z(value, baseline, higher_is_better=False):
    """Signed robust z-score of `value` against a ``{median, mad, n}`` baseline.

    Deliberately mirrors the frontend `madZ` (frontend/src/utils/frameQuality.ts)
    including its null semantics, so backend insight text and frontend cell
    colours are computed from the same number. Returns None when:

    - the value is missing,
    - the baseline is missing or has no median/mad,
    - the group is too sparse (n < MIN_GROUP), or
    - the group is uniform (mad == 0), which would divide by ~nothing.

    A None z must never produce an insight: staying silent beats a wrong claim.

    `higher_is_better` flips the sign so "worse than baseline" is always
    positive. Units are raw MAD, not sigma.
    """
    if value is None or not baseline:
        return None
    med = baseline.get("median")
    dev = baseline.get("mad")
    n = baseline.get("n") or 0
    if med is None or dev is None or n < MIN_GROUP or dev == 0:
        return None
    z = (value - med) / max(dev, EPS)
    return -z if higher_is_better else z


def count_outliers(frames, baselines, metric, *, z_threshold=Z_REJECT, higher_is_better=False):
    """Count frames whose `metric` sits at or beyond `z_threshold` MAD units on
    the bad side of the baseline for that frame's OWN train+filter group.

    Returns ``(outliers, graded)``. `graded` is the number of frames that had a
    usable baseline, letting callers distinguish "nothing was bad" from "nothing
    could be judged" and stay silent in the second case.
    """
    outliers = 0
    graded = 0
    for frame in frames or []:
        group = baselines.get(group_key(frame)) if baselines else None
        z = mad_z(_get(frame, metric), (group or {}).get(metric), higher_is_better)
        if z is None:
            continue
        graded += 1
        if z >= z_threshold:
            outliers += 1
    return outliers, graded
