"""Pure-logic tests for the analysis statistics helpers (issue #311)."""
import statistics

import pytest

from app.api.analysis import (
    _histogram_bins,
    _iqr_fences,
    _join_target_names,
    _pct_lower,
    _pearson_r,
    _spearman_rho,
    _t_crit_95,
)


def test_histogram_counts_sum_to_n_and_keep_the_maximum():
    # v_min + 10 * ((v_max - v_min) / 10) lands below v_max in floating point.
    values = [0.0, 2.6245] + [0.1 * i for i in range(1, 26)]
    bins = _histogram_bins(values, 10)
    assert len(bins) == 10
    assert sum(count for _, _, count in bins) == len(values)
    assert bins[-1][1] == 2.6245
    assert bins[-1][2] >= 1


def test_histogram_constant_values():
    bins = _histogram_bins([3.0, 3.0, 3.0], 3)
    assert sum(count for _, _, count in bins) == 3


def test_pct_lower_uses_the_larger_median_and_is_symmetric():
    assert round(_pct_lower(1.772, 3.997)) == 56
    assert _pct_lower(1.772, 3.997) == _pct_lower(3.997, 1.772)
    assert _pct_lower(0.0, 0.0) == 0.0
    assert _pct_lower(0.0, 2.0) == 100.0


def test_pearson_r_none_when_undefined():
    assert _pearson_r([1.0, 2.0], [1.0, 2.0]) is None
    assert _pearson_r([1.0, 1.0, 1.0, 1.0], [1.0, 2.0, 3.0, 4.0]) is None
    assert _pearson_r([1.0, 2.0, 3.0, 4.0], [5.0, 5.0, 5.0, 5.0]) is None
    assert _spearman_rho([1.0, 2.0], [1.0, 2.0]) is None
    assert _spearman_rho([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


def test_pearson_r_perfect_correlation():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _pearson_r(xs, [2 * x + 1 for x in xs]) == pytest.approx(1.0)
    assert _pearson_r(xs, [-x for x in xs]) == pytest.approx(-1.0)


def test_t_critical_values():
    assert _t_crit_95(2) == pytest.approx(4.303, abs=0.001)
    assert _t_crit_95(30) == pytest.approx(2.042, abs=0.001)
    assert _t_crit_95(31) == 1.96


def _brute_force_outlier(x, y, xs, ys):
    for vals, val in [(xs, x), (ys, y)]:
        s = sorted(vals)
        n = len(s)
        q1 = statistics.median(s[: n // 2])
        q3 = statistics.median(s[(n + 1) // 2 :])
        iqr = q3 - q1
        if val < q1 - 1.5 * iqr or val > q3 + 1.5 * iqr:
            return True
    return False


def test_iqr_fences_match_per_point_computation():
    xs = [1.0, 1.2, 0.9, 1.1, 1.05, 9.0, 1.15, 0.95, -6.0]
    ys = [2.0, 2.1, 1.9, 40.0, 2.05, 2.0, 1.95, 2.2, 2.1]
    x_lo, x_hi = _iqr_fences(xs)
    y_lo, y_hi = _iqr_fences(ys)
    flags = [x < x_lo or x > x_hi or y < y_lo or y > y_hi for x, y in zip(xs, ys)]
    assert flags == [_brute_force_outlier(x, y, xs, ys) for x, y in zip(xs, ys)]
    assert flags.count(True) == 3


def test_join_target_names():
    assert _join_target_names([]) is None
    assert _join_target_names(["M 31"]) == "M 31"
    assert _join_target_names(["NGC 7000", "M 31"]) == "M 31, NGC 7000"
    assert _join_target_names(["d", "b", "a", "c", "e"]) == "a, b, c +2 more"
