import pytest
from unittest.mock import MagicMock, patch


class TestFindTargetByName:
    """Test the DB lookup function that searches aliases then primary_name."""

    def test_finds_by_alias(self):
        from app.services.target_resolver import find_target_by_name

        mock_session = MagicMock()
        mock_target = MagicMock()
        mock_target.id = "target-123"
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_target

        result = find_target_by_name("NGC 7000", mock_session)
        assert result is not None
        assert str(result.id) == "target-123"

    def test_returns_none_when_not_found(self):
        from app.services.target_resolver import find_target_by_name

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        result = find_target_by_name("NONEXISTENT", mock_session)
        assert result is None


class TestResolveTarget:
    """Test the full resolution pipeline."""

    def test_returns_none_for_redis_negative_cached(self):
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()
        mock_redis = MagicMock()
        mock_redis.sismember.return_value = True

        result = resolve_target("FlatWizard", mock_session, redis=mock_redis)
        assert result is None

    def test_finds_existing_target_by_alias(self):
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()
        mock_redis = MagicMock()
        mock_redis.sismember.return_value = False
        mock_target = MagicMock()
        mock_target.id = "target-123"

        with patch("app.services.target_resolver.find_target_by_name", return_value=mock_target):
            result = resolve_target("NGC 7000", mock_session, redis=mock_redis)
        assert result == "target-123"

    def test_falls_back_to_simbad_and_creates_target(self):
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()
        mock_redis = MagicMock()
        mock_redis.sismember.return_value = False

        simbad_result = {
            "primary_name": "NGC 7000 - North America Nebula",
            "catalog_id": "NGC 7000",
            "common_name": "North America Nebula",
            "aliases": ["NGC 7000"],
            "ra": 314.0, "dec": 44.0, "object_type": "HII",
        }

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=simbad_result), \
             patch("app.services.target_resolver._create_target", return_value="new-target-id"):
            result = resolve_target("NGC 7000", mock_session, redis=mock_redis)
        assert result == "new-target-id"

    def test_adds_to_negative_cache_when_simbad_fails(self):
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()
        mock_redis = MagicMock()
        mock_redis.sismember.return_value = False

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=None):
            result = resolve_target("FlatWizard", mock_session, redis=mock_redis)

        assert result is None
        mock_redis.sadd.assert_called_once()
        mock_redis.expire.assert_called_once()

    def test_race_condition_recheck_finds_concurrent_target(self):
        """After SIMBAD resolves, re-check should find a concurrently-created target."""
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()
        mock_redis = MagicMock()
        mock_redis.sismember.return_value = False
        mock_target = MagicMock()
        mock_target.id = "concurrent-target"

        simbad_result = {
            "primary_name": "NGC 7000 - North America Nebula",
            "catalog_id": "NGC 7000",
            "common_name": "North America Nebula",
            "aliases": ["NGC 7000"],
            "ra": 314.0, "dec": 44.0, "object_type": "HII",
        }

        # First call (initial lookup) returns None, second call (re-check) returns target
        with patch("app.services.target_resolver.find_target_by_name", side_effect=[None, mock_target]), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=simbad_result), \
             patch("app.services.target_resolver._create_target") as mock_create:
            result = resolve_target("NGC 7000", mock_session, redis=mock_redis)

        assert result == "concurrent-target"
        mock_create.assert_not_called()

    def test_works_without_redis(self):
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=None):
            result = resolve_target("FlatWizard", mock_session, redis=None)

        assert result is None


class TestCreateTarget:
    """Test target creation with race condition handling."""

    def test_integrity_error_returns_existing_target(self):
        from sqlalchemy.exc import IntegrityError
        from app.services.target_resolver import _create_target

        mock_session = MagicMock()
        mock_session.flush.side_effect = IntegrityError("dup", {}, None)
        mock_existing = MagicMock()
        mock_existing.id = "existing-target"
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_existing

        simbad_result = {
            "primary_name": "NGC 7000 - North America Nebula",
            "catalog_id": "NGC 7000",
            "aliases": ["NGC 7000"],
        }

        result = _create_target(simbad_result, "NGC 7000", mock_session)
        assert result == "existing-target"
        mock_session.rollback.assert_called_once()
