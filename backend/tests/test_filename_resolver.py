"""Tests for filename_resolver.resolve_filename_candidate."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services.filename_resolver import resolve_filename_candidate


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def fake_target():
    t = MagicMock()
    t.id = uuid.uuid4()
    t.primary_name = "M 31"
    return t


class TestDirectAliasMatch:
    def test_alias_match_found(self, mock_session, fake_target):
        with patch(
            "app.services.filename_resolver.find_target_by_name",
            return_value=fake_target,
        ):
            result = resolve_filename_candidate("M 31", mock_session)

        assert result["method"] == "alias_match"
        assert result["confidence"] == 1.0
        assert result["suggested_target_id"] == str(fake_target.id)
        assert result["suggested_target_name"] == "M 31"
        assert result["extracted_name"] == "M 31"


class TestCommonNameMap:
    def test_common_name_match(self, mock_session, fake_target):
        fake_target.primary_name = "NGC 7000"
        fake_target.id = uuid.uuid4()

        def find_side_effect(name, session):
            if name == "NGC 7000":
                return fake_target
            return None

        with patch(
            "app.services.filename_resolver.find_target_by_name",
            side_effect=find_side_effect,
        ), patch(
            "app.services.filename_resolver.COMMON_NAME_MAP",
            {"north america nebula": "NGC 7000"},
        ):
            result = resolve_filename_candidate("North America Nebula", mock_session)

        assert result["method"] == "common_name"
        assert result["confidence"] == 0.95
        assert result["suggested_target_id"] == str(fake_target.id)
        assert result["suggested_target_name"] == "NGC 7000"


class TestSpaceInsert:
    def test_space_insert_m31(self, mock_session, fake_target):
        fake_target.primary_name = "M 31"

        def find_side_effect(name, session):
            if name == "M 31":
                return fake_target
            return None

        with patch(
            "app.services.filename_resolver.find_target_by_name",
            side_effect=find_side_effect,
        ), patch(
            "app.services.filename_resolver.COMMON_NAME_MAP",
            {},
        ):
            result = resolve_filename_candidate("M31", mock_session)

        assert result["method"] == "space_insert"
        assert result["confidence"] == 0.9
        assert result["suggested_target_id"] == str(fake_target.id)
        assert result["suggested_target_name"] == "M 31"

    def test_space_insert_ngc7000(self, mock_session, fake_target):
        fake_target.primary_name = "NGC 7000"

        def find_side_effect(name, session):
            if name == "NGC 7000":
                return fake_target
            return None

        with patch(
            "app.services.filename_resolver.find_target_by_name",
            side_effect=find_side_effect,
        ), patch(
            "app.services.filename_resolver.COMMON_NAME_MAP",
            {},
        ):
            result = resolve_filename_candidate("NGC7000", mock_session)

        assert result["method"] == "space_insert"
        assert result["confidence"] == 0.9
        assert result["suggested_target_id"] == str(fake_target.id)


class TestNoMatch:
    def test_no_match_returns_none(self, mock_session):
        with patch(
            "app.services.filename_resolver.find_target_by_name",
            return_value=None,
        ), patch(
            "app.services.filename_resolver.COMMON_NAME_MAP",
            {},
        ), patch(
            "app.services.filename_resolver.resolve_target_name_cached",
            return_value=None,
        ), patch(
            "app.services.filename_resolver.resolve_sesame_cached",
            return_value=None,
        ):
            # Also mock the trigram query to raise (extension not installed)
            mock_session.execute.side_effect = Exception("pg_trgm not available")

            result = resolve_filename_candidate("xyzzy", mock_session)

        assert result["method"] == "none"
        assert result["confidence"] == 0.0
        assert result["suggested_target_id"] is None
        assert result["suggested_target_name"] is None
        assert result["extracted_name"] == "xyzzy"
