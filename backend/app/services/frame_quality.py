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
