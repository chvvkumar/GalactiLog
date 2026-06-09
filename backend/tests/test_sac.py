"""Unit tests for app.services.sac - name normalization, float parsing, and lookup logic."""
import pytest
from unittest.mock import MagicMock, patch

from app.services.sac import (
    _normalize_sac_name,
    _parse_float,
    lookup_sac,
    enrich_target_from_sac,
)


# ---------------------------------------------------------------------------
# _normalize_sac_name
# ---------------------------------------------------------------------------

class TestNormalizeSacName:
    def test_ngc_with_leading_zeros(self):
        assert _normalize_sac_name("NGC0031") == "NGC 31"

    def test_ngc_with_space_and_zeros(self):
        assert _normalize_sac_name("NGC 0031") == "NGC 31"

    def test_ngc_preserves_suffix_letter(self):
        assert _normalize_sac_name("NGC5128A") == "NGC 5128A"

    def test_ic_with_leading_zeros(self):
        assert _normalize_sac_name("IC0002") == "IC 2"

    def test_ic_lowercase(self):
        assert _normalize_sac_name("ic0010") == "IC 10"

    def test_messier_with_leading_zeros(self):
        assert _normalize_sac_name("M031") == "M 31"

    def test_messier_lowercase(self):
        assert _normalize_sac_name("m001") == "M 1"

    def test_messier_no_leading_zeros(self):
        assert _normalize_sac_name("M 42") == "M 42"

    def test_unrecognized_name_returned_stripped(self):
        assert _normalize_sac_name("  SomeObject  ") == "SomeObject"

    def test_empty_string(self):
        assert _normalize_sac_name("") == ""

    def test_already_normalized_ngc(self):
        assert _normalize_sac_name("NGC 31") == "NGC 31"

    def test_ngc_uppercase_prefix(self):
        # NGC prefix uppercased even when given in lowercase
        assert _normalize_sac_name("ngc224") == "NGC 224"


# ---------------------------------------------------------------------------
# _parse_float
# ---------------------------------------------------------------------------

class TestParseFloat:
    def test_valid_integer_string(self):
        assert _parse_float("42") == pytest.approx(42.0)

    def test_valid_float_string(self):
        assert _parse_float("3.14") == pytest.approx(3.14)

    def test_whitespace_around_value(self):
        assert _parse_float("  7.5  ") == pytest.approx(7.5)

    def test_negative_value(self):
        assert _parse_float("-1.2") == pytest.approx(-1.2)

    def test_empty_string_returns_none(self):
        assert _parse_float("") is None

    def test_whitespace_only_returns_none(self):
        assert _parse_float("   ") is None

    def test_none_input_returns_none(self):
        assert _parse_float(None) is None

    def test_non_numeric_string_returns_none(self):
        assert _parse_float("abc") is None

    def test_partial_number_string_returns_none(self):
        assert _parse_float("1.2.3") is None


# ---------------------------------------------------------------------------
# lookup_sac
# ---------------------------------------------------------------------------

class TestLookupSac:
    def _make_session(self, return_value):
        """Build a mock session whose scalar_one_or_none returns return_value."""
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = return_value
        return session

    def test_direct_catalog_id_match(self):
        mock_entry = MagicMock()
        session = self._make_session(mock_entry)

        result = lookup_sac(session, "NGC 31")
        assert result is mock_entry

    def test_normalized_catalog_id_match(self):
        # First call (direct) returns None, second (normalized) returns the entry
        mock_entry = MagicMock()
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.side_effect = [None, mock_entry]

        result = lookup_sac(session, "NGC0031")
        assert result is mock_entry

    def test_no_match_returns_none(self):
        session = self._make_session(None)
        result = lookup_sac(session, "XYZNOTFOUND")
        assert result is None

    def test_alias_match(self):
        mock_entry = MagicMock()
        session = MagicMock()
        # catalog_id direct -> None, catalog_id normalized -> None (same),
        # alias direct -> mock_entry
        session.execute.return_value.scalar_one_or_none.side_effect = [
            None,  # direct catalog_id
            mock_entry,  # alias
        ]

        result = lookup_sac(session, "NOTFOUND", aliases=["NGC 31"])
        assert result is mock_entry

    def test_none_catalog_id_uses_aliases_only(self):
        mock_entry = MagicMock()
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = mock_entry

        result = lookup_sac(session, None, aliases=["M 42"])
        assert result is mock_entry

    def test_empty_aliases_list_returns_none(self):
        session = self._make_session(None)
        result = lookup_sac(session, None, aliases=[])
        assert result is None

    def test_blank_alias_skipped(self):
        # A blank alias entry should be skipped without executing a query
        session = self._make_session(None)
        result = lookup_sac(session, None, aliases=["", "  "])
        assert result is None

    def test_normalized_alias_tried_when_raw_alias_misses(self):
        mock_entry = MagicMock()
        session = MagicMock()
        # alias direct -> None, alias normalized -> mock_entry
        session.execute.return_value.scalar_one_or_none.side_effect = [None, mock_entry]

        result = lookup_sac(session, None, aliases=["NGC0031"])
        assert result is mock_entry


# ---------------------------------------------------------------------------
# enrich_target_from_sac
# ---------------------------------------------------------------------------

class TestEnrichTargetFromSac:
    def test_no_sac_entry_returns_false(self):
        session = MagicMock()
        target = MagicMock()
        target.catalog_id = "NOTFOUND"
        target.aliases = []

        with patch("app.services.sac.lookup_sac", return_value=None):
            result = enrich_target_from_sac(session, target)

        assert result is False

    def test_fills_description_when_missing(self):
        session = MagicMock()
        target = MagicMock()
        target.catalog_id = "NGC 31"
        target.aliases = []
        target.sac_description = None
        target.sac_notes = None

        mock_entry = MagicMock()
        mock_entry.description = "A fine galaxy"
        mock_entry.notes = None

        with patch("app.services.sac.lookup_sac", return_value=mock_entry):
            result = enrich_target_from_sac(session, target)

        assert result is True
        assert target.sac_description == "A fine galaxy"

    def test_does_not_overwrite_existing_description(self):
        session = MagicMock()
        target = MagicMock()
        target.catalog_id = "NGC 31"
        target.aliases = []
        target.sac_description = "Already set"
        target.sac_notes = None

        mock_entry = MagicMock()
        mock_entry.description = "New description"
        mock_entry.notes = None

        with patch("app.services.sac.lookup_sac", return_value=mock_entry):
            result = enrich_target_from_sac(session, target)

        # No update because description already present
        assert result is False
        assert target.sac_description == "Already set"

    def test_fills_notes_when_missing(self):
        session = MagicMock()
        target = MagicMock()
        target.catalog_id = "NGC 31"
        target.aliases = []
        target.sac_description = None
        target.sac_notes = None

        mock_entry = MagicMock()
        mock_entry.description = None
        mock_entry.notes = "Some note"

        with patch("app.services.sac.lookup_sac", return_value=mock_entry):
            result = enrich_target_from_sac(session, target)

        assert result is True
        assert target.sac_notes == "Some note"
