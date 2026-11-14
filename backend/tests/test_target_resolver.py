import pytest
from unittest.mock import MagicMock, patch


class TestFindTargetByName:
    """Test the DB lookup function that searches aliases then primary_name."""

    def test_finds_by_alias(self):
        from app.services.target_resolver import find_target_by_name

        mock_session = MagicMock()
        mock_target = MagicMock()
        mock_target.id = "target-123"
        mock_session.execute.return_value.scalars.return_value.all.return_value = [mock_target]

        result = find_target_by_name("NGC 7000", mock_session)
        assert result is not None
        assert str(result.id) == "target-123"

    def test_returns_none_when_not_found(self):
        from app.services.target_resolver import find_target_by_name

        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        result = find_target_by_name("NONEXISTENT", mock_session)
        assert result is None

    def test_an_alias_shared_by_two_targets_falls_through_to_primary_name(self):
        """Production had "QUESTION MARK GALAXY" on both an unresolved
        standalone target and on M 51. scalar_one_or_none raised
        MultipleResultsFound, and every image naming it failed to ingest
        after three retries. An ambiguous alias is no match at all; the exact
        primary-name tier decides, and duplicate detection merges the pair."""
        from app.services.target_resolver import find_target_by_name

        mock_session = MagicMock()
        by_name = MagicMock()
        by_name.id = "standalone"
        mock_session.execute.return_value.scalars.return_value.all.return_value = [
            MagicMock(primary_name="Question Mark Galaxy"),
            MagicMock(primary_name="M 51 - Whirlpool"),
        ]
        mock_session.execute.return_value.scalar_one_or_none.return_value = by_name

        result = find_target_by_name("Question Mark Galaxy", mock_session)
        assert result is by_name


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
             patch("app.services.target_resolver.match_target_by_identity", return_value=None), \
             patch("app.services.target_resolver._create_target", return_value="new-target-id"):
            result = resolve_target("NGC 7000", mock_session, redis=mock_redis)
        assert result == "new-target-id"

    def test_adds_to_negative_cache_when_simbad_fails(self):
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()
        mock_redis = MagicMock()
        mock_redis.sismember.return_value = False

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=None), \
             patch("app.services.target_resolver.resolve_sesame_cached", return_value=None):
            result = resolve_target("FlatWizard", mock_session, redis=mock_redis)

        assert result is None
        mock_redis.sadd.assert_called_once()
        mock_redis.expire.assert_called_once()

    def test_outage_is_not_negative_cached(self):
        """catalog_cache returns None for an outage and stores no row. With
        no negative row to confirm the miss, the name must not be suppressed."""
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()
        mock_redis = MagicMock()
        mock_redis.sismember.return_value = False

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=None), \
             patch("app.services.target_resolver.resolve_sesame_cached", return_value=None), \
             patch("app.services.target_resolver.cc.get_cached", return_value=None):
            result = resolve_target("NGC 7000", mock_session, redis=mock_redis)

        assert result is None
        mock_redis.sadd.assert_not_called()

    def test_one_service_down_is_not_negative_cached(self):
        """Sesame answering "no match" proves nothing while SIMBAD is down."""
        from app.services import catalog_cache as cc
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()
        mock_redis = MagicMock()
        mock_redis.sismember.return_value = False

        def get_cached(session, source, key):
            return cc.NEGATIVE if source == "sesame" else None

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=None), \
             patch("app.services.target_resolver.resolve_sesame_cached", return_value=None), \
             patch("app.services.target_resolver.cc.get_cached", side_effect=get_cached):
            result = resolve_target("NGC 7000", mock_session, redis=mock_redis)

        assert result is None
        mock_redis.sadd.assert_not_called()

    def test_confirmed_no_match_is_negative_cached(self):
        from app.services import catalog_cache as cc
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()
        mock_redis = MagicMock()
        mock_redis.sismember.return_value = False

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=None), \
             patch("app.services.target_resolver.resolve_sesame_cached", return_value=None), \
             patch("app.services.target_resolver.cc.get_cached", return_value=cc.NEGATIVE):
            result = resolve_target("FlatWizard", mock_session, redis=mock_redis)

        assert result is None
        mock_redis.sadd.assert_called_once()

    @pytest.mark.parametrize("make_exc", [
        lambda: __import__("app.services.catalog_cache", fromlist=["x"]).NonTransientError(
            "SIMBAD lookup for 'NGC 7000' failed: SIMBAD returned HTTP 404",
            source="simbad", key="NGC 7000",
        ),
        lambda: __import__("httpx").ConnectTimeout("timed out"),
    ])
    def test_lookup_error_neither_raises_nor_negative_caches(self, make_exc, caplog):
        """A raising lookup used to propagate out of resolve_target and fail
        the file being ingested. It must return None, write no negative, and
        say why in plain words."""
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()
        mock_redis = MagicMock()
        mock_redis.sismember.return_value = False

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", side_effect=make_exc()), \
             patch("app.services.target_resolver.resolve_sesame_cached", side_effect=make_exc()), \
             caplog.at_level("WARNING", logger="app.services.target_resolver"):
            result = resolve_target("NGC 7000", mock_session, redis=mock_redis)

        assert result is None
        mock_redis.sadd.assert_not_called()
        assert "Catalog lookup for 'NGC 7000' skipped" in caplog.text

    @pytest.mark.parametrize("down", ["simbad", "sesame"])
    def test_marked_outage_is_not_negative_cached(self, down):
        """Negative rows exist, but a source is marked unavailable: the None
        came from the outage short-circuit, not from an answer."""
        from app.services import catalog_cache as cc
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()
        mock_redis = MagicMock()
        mock_redis.sismember.return_value = False

        def outage(source):
            return "SIMBAD is unavailable" if source == down else None

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=None), \
             patch("app.services.target_resolver.resolve_sesame_cached", return_value=None), \
             patch("app.services.target_resolver.cc.get_cached", return_value=cc.NEGATIVE), \
             patch("app.services.target_resolver.cc.outage", side_effect=outage):
            result = resolve_target("NGC 7000", mock_session, redis=mock_redis)

        assert result is None
        mock_redis.sadd.assert_not_called()

    def test_sesame_still_asked_when_simbad_raises(self):
        from app.services.catalog_cache import NonTransientError
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()
        sesame_result = {"primary_name": "NGC 7000", "catalog_id": "NGC 7000", "aliases": []}

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached",
                   side_effect=NonTransientError("SIMBAD returned HTTP 404")), \
             patch("app.services.target_resolver.resolve_sesame_cached", return_value=sesame_result), \
             patch("app.services.target_resolver.match_target_by_identity", return_value=None), \
             patch("app.services.target_resolver._create_target", return_value="new-id") as create:
            result = resolve_target("NGC 7000", mock_session, redis=None)

        assert result == "new-id"
        create.assert_called_once()

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

        # Initial lookup misses; the post-SIMBAD re-check now routes through the
        # shared identity matcher, which finds the concurrently-created target.
        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=simbad_result), \
             patch("app.services.target_resolver.match_target_by_identity", return_value=mock_target), \
             patch("app.services.target_resolver._create_target") as mock_create:
            result = resolve_target("NGC 7000", mock_session, redis=mock_redis)

        assert result == "concurrent-target"
        mock_create.assert_not_called()

    def test_works_without_redis(self):
        from app.services.target_resolver import resolve_target

        mock_session = MagicMock()

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=None), \
             patch("app.services.target_resolver.resolve_sesame_cached", return_value=None):
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

        with patch("app.services.target_resolver.match_target_by_identity", return_value=None), \
             patch("app.services.target_resolver.enrich_target_from_openngc"):
            result = _create_target(simbad_result, "NGC 7000", mock_session)
        assert result == "existing-target"
        mock_session.rollback.assert_called_once()


class TestCreateTargetEnrichmentOutage:
    @pytest.mark.parametrize("make_exc", [
        lambda: __import__("app.services.catalog_cache", fromlist=["x"]).NonTransientError(
            "VizieR lookup for 'NGC 7000' failed: VizieR returned HTTP 404",
            source="vizier", key="NGC 7000",
        ),
        lambda: __import__("httpx").ConnectError("connection refused"),
    ])
    def test_vizier_failure_does_not_fail_target_creation(self, make_exc, caplog):
        """The target row is committed before the VizieR size lookup. A VizieR
        outage raised out of resolve_target and failed the file's ingest."""
        from app.services.target_resolver import _create_target

        mock_session = MagicMock()

        def assign_id(target):
            target.id = "new-target"
            target.size_major = None

        mock_session.add.side_effect = assign_id
        simbad_result = {
            "primary_name": "NGC 7000 - North America Nebula",
            "catalog_id": "NGC 7000",
            "aliases": ["NGC 7000"],
        }

        with patch("app.services.target_resolver.match_target_by_identity", return_value=None), \
             patch("app.services.target_resolver.enrich_target_from_openngc"), \
             patch("app.services.target_resolver.enrich_target_from_vizier", side_effect=make_exc()), \
             patch("app.services.target_resolver.enrich_target_from_sac") as sac, \
             patch("app.services.target_resolver._dispatch_enrich_new_target") as dispatch, \
             caplog.at_level("WARNING", logger="app.services.target_resolver"):
            result = _create_target(simbad_result, "NGC 7000", mock_session)

        assert result == "new-target"
        sac.assert_called_once()
        dispatch.assert_called_once_with("new-target")
        assert "Size lookup for new target NGC 7000 - North America Nebula skipped" in caplog.text


class TestFindTargetByNameNormalization:
    def test_primary_name_lookup_normalizes_input(self):
        """Ensure primary_name lookup normalizes the input, not raw comparison.

        Regression: old code compared raw 'ngc  7000' against primary_name which never matched.
        """
        from app.services.target_resolver import find_target_by_name

        mock_session = MagicMock()
        mock_target = MagicMock()
        mock_target.id = "target-456"
        # The alias tiers miss; the primary_name tier returns the target.
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_target

        result = find_target_by_name("ngc  7000", mock_session)
        assert result is not None
        assert str(result.id) == "target-456"
