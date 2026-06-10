"""Tests for normalize_catalog_id: the canonical catalog-identity key."""
import pytest

from app.services.simbad import normalize_catalog_id


class TestNormalizeCatalogId:
    def test_uppercases_and_collapses_whitespace(self):
        assert normalize_catalog_id("NGC 6543") == "NGC 6543"

    def test_double_space_collapses_to_single(self):
        # SIMBAD main_id "NGC  6543" must key the same as "NGC 6543"
        assert normalize_catalog_id("NGC  6543") == "NGC 6543"

    def test_lowercase_input_uppercased(self):
        assert normalize_catalog_id("ngc 6543") == "NGC 6543"

    def test_leading_trailing_whitespace_stripped(self):
        assert normalize_catalog_id("  IC 1396a  ") == "IC 1396A"

    def test_none_input_returns_none(self):
        assert normalize_catalog_id(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_catalog_id("") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_catalog_id("   ") is None

    def test_matches_normalize_object_name_upper(self):
        from app.services.simbad import normalize_object_name
        assert normalize_catalog_id("ngc  6543") == normalize_object_name("ngc  6543", upper=True)
