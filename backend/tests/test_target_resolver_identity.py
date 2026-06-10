"""Tests for the shared catalog-identity matcher and the reordered creator."""
import pytest
from unittest.mock import MagicMock, patch


class TestMatchTargetByIdentity:
    def test_matches_by_normalized_catalog_id(self):
        from app.services.target_resolver import match_target_by_identity

        existing = MagicMock()
        existing.id = "cats-eye"
        session = MagicMock()
        # First execute (catalog_id_normalized lookup) returns the target
        session.execute.return_value.scalar_one_or_none.return_value = existing

        resolved = {"catalog_id": "NGC  6543", "primary_name": "NGC 6543",
                    "aliases": ["NGC 6543"]}
        result = match_target_by_identity(resolved, "NGC 6543", session)
        assert result is existing

    def test_double_spaced_catalog_id_still_matches(self):
        from app.services.target_resolver import match_target_by_identity

        existing = MagicMock()
        existing.id = "cats-eye"
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = existing

        resolved = {"catalog_id": "NGC  6543", "primary_name": "NGC 6543", "aliases": []}
        assert match_target_by_identity(resolved, "NGC  6543", session) is existing

    def test_falls_back_to_name_match_when_no_catalog_id(self):
        from app.services.target_resolver import match_target_by_identity

        existing = MagicMock()
        existing.id = "comet"
        session = MagicMock()

        resolved = {"catalog_id": None, "primary_name": "C/2023 A3", "aliases": []}
        with patch("app.services.target_resolver.find_target_by_name",
                   return_value=existing) as fbn:
            result = match_target_by_identity(resolved, "C/2023 A3", session)
        assert result is existing
        fbn.assert_called_once()

    def test_falls_back_to_name_match_when_identity_misses(self):
        from app.services.target_resolver import match_target_by_identity

        named = MagicMock()
        named.id = "named-hit"
        session = MagicMock()
        # catalog_id_normalized lookup misses
        session.execute.return_value.scalar_one_or_none.return_value = None

        resolved = {"catalog_id": "NGC 6543", "primary_name": "NGC 6543", "aliases": []}
        with patch("app.services.target_resolver.find_target_by_name",
                   return_value=named) as fbn:
            result = match_target_by_identity(resolved, "NGC 6543", session)
        assert result is named
        fbn.assert_called_once()

    def test_returns_none_when_nothing_matches(self):
        from app.services.target_resolver import match_target_by_identity

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = None
        resolved = {"catalog_id": "NGC 9999", "primary_name": "NGC 9999", "aliases": []}
        with patch("app.services.target_resolver.find_target_by_name", return_value=None):
            assert match_target_by_identity(resolved, "NGC 9999", session) is None

    def test_adds_incoming_object_as_alias_on_identity_match(self):
        from app.services.target_resolver import match_target_by_identity

        existing = MagicMock()
        existing.id = "cats-eye"
        existing.aliases = ["NGC 6543"]
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = existing

        resolved = {"catalog_id": "NGC 6543", "primary_name": "NGC 6543", "aliases": []}
        match_target_by_identity(resolved, "Cat's Eye Nebula", session)
        # Normalized incoming OBJECT recorded so future direct lookups hit
        assert "CAT'S EYE NEBULA" in existing.aliases
