import math

from app.services.frame_quality import median, mad, group_baselines, MIN_GROUP


def test_median_ignores_none():
    assert median([1.0, None, 3.0, 2.0]) == 2.0


def test_median_empty_is_none():
    assert median([None, None]) is None


def test_mad_basic():
    # values 1,2,3,4,5 -> median 3 -> |dev| 2,1,0,1,2 -> median 1
    assert mad([1, 2, 3, 4, 5]) == 1.0


def test_mad_uniform_is_zero():
    assert mad([4, 4, 4]) == 0.0


def test_group_baselines_groups_by_train_filter():
    frames = [
        {"telescope": "T", "camera": "C", "filter_used": "Ha", "median_hfr": 2.0,
         "fwhm": None, "eccentricity": 0.3, "detected_stars": 100,
         "adu_median": 500, "guiding_rms_arcsec": 0.5},
        {"telescope": "T", "camera": "C", "filter_used": "Ha", "median_hfr": 2.4,
         "fwhm": None, "eccentricity": 0.5, "detected_stars": 80,
         "adu_median": 600, "guiding_rms_arcsec": 0.7},
    ]
    out = group_baselines(frames)
    key = "T|C|Ha"
    assert key in out
    assert out[key]["median_hfr"]["median"] == 2.2
    assert out[key]["median_hfr"]["n"] == 2
    # |2.0-2.2|, |2.4-2.2| -> 0.2,0.2 -> 0.2 (isclose: 0.4-0.2 subtraction is FP-inexact)
    assert math.isclose(out[key]["median_hfr"]["mad"], 0.2, abs_tol=1e-9)


def test_group_baselines_null_component_key():
    frames = [{"telescope": None, "camera": "C", "filter_used": None,
               "median_hfr": 1.0, "fwhm": None, "eccentricity": None,
               "detected_stars": None, "adu_median": None, "guiding_rms_arcsec": None}]
    out = group_baselines(frames)
    assert "|C|" in out
