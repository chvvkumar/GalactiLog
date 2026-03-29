from app.services.normalization import (
    build_alias_maps, build_equipment_alias_maps,
    normalize_filter, normalize_equipment,
)


def test_build_alias_maps_from_filter_config():
    filters = {
        "OIII": {"color": "#3498db", "aliases": ["Oiii", "O"]},
        "Ha": {"color": "#e74c3c", "aliases": ["ha"]},
    }
    alias_map = build_alias_maps(filters)
    assert alias_map["Oiii"] == "OIII"
    assert alias_map["O"] == "OIII"
    assert alias_map["ha"] == "Ha"
    assert "OIII" not in alias_map  # canonical names are not in the alias map
    assert "Ha" not in alias_map


def test_normalize_filter_maps_alias_to_canonical():
    alias_map = {"Oiii": "OIII", "ha": "Ha"}
    assert normalize_filter("Oiii", alias_map) == "OIII"
    assert normalize_filter("ha", alias_map) == "Ha"
    assert normalize_filter("SII", alias_map) == "SII"  # unknown stays as-is
    assert normalize_filter(None, alias_map) is None


def test_normalize_equipment_maps_aliases():
    equipment = {
        "cameras": {"ZWO ASI2600MM Pro": {"aliases": ["ASI2600MM"]}},
        "telescopes": {"Esprit 100ED": {"aliases": ["Esprit100ED"]}},
    }
    cam_map, tel_map = build_equipment_alias_maps(equipment)
    assert normalize_equipment("ASI2600MM", cam_map) == "ZWO ASI2600MM Pro"
    assert normalize_equipment("Esprit100ED", tel_map) == "Esprit 100ED"
    assert normalize_equipment("Unknown", cam_map) == "Unknown"
    assert normalize_equipment(None, cam_map) is None
