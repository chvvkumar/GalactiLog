import pytest

from app.services.target_aggregation import categorize_object_type


@pytest.mark.parametrize("raw,expected", [
    ("Planet", "Planet"),
    ("planet", "Planet"),
    ("Comet", "Comet"),
    ("Moon", "Moon"),
    ("Sun", "Sun"),
    ("Asteroid", "Asteroid"),
])
def test_categorize_solar_system_types(raw, expected):
    assert categorize_object_type(raw) == expected


def test_categorize_passes_through_existing_category_names():
    # Admin-edited object types store category names directly.
    assert categorize_object_type("Galaxy") == "Galaxy"
    assert categorize_object_type("Emission Nebula") == "Emission Nebula"


def test_categorize_simbad_codes_still_map():
    assert categorize_object_type("G") == "Galaxy"
    assert categorize_object_type("PN,HII") == "Planetary Nebula"


def test_categorize_unknown_is_other():
    assert categorize_object_type("XYZ") == "Other"
    assert categorize_object_type(None) == "Other"
