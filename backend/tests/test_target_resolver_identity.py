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


class TestCreateTargetReordered:
    def _simbad(self):
        return {
            "primary_name": "NGC 6543",
            "catalog_id": "NGC 6543",
            "common_name": None,
            "aliases": ["NGC 6543"],
            "ra": 269.6, "dec": 66.6, "object_type": "PN",
        }

    def test_sets_catalog_id_normalized_on_new_target(self):
        from app.services.target_resolver import _create_target

        session = MagicMock()
        captured = {}

        def _add(obj):
            captured["target"] = obj
        session.add.side_effect = _add

        with patch("app.services.target_resolver.match_target_by_identity", return_value=None), \
             patch("app.services.target_resolver.enrich_target_from_openngc"), \
             patch("app.services.target_resolver.enrich_target_from_vizier"), \
             patch("app.services.target_resolver.enrich_target_from_sac"):
            _create_target(self._simbad(), "NGC 6543", session)

        assert captured["target"].catalog_id_normalized == "NGC 6543"

    def test_links_to_existing_identity_instead_of_inserting(self):
        from app.services.target_resolver import _create_target

        existing = MagicMock()
        existing.id = "cats-eye"
        session = MagicMock()

        with patch("app.services.target_resolver.match_target_by_identity", return_value=existing):
            result = _create_target(self._simbad(), "NGC 6543", session)

        assert result == "cats-eye"
        session.add.assert_not_called()

    def test_integrity_error_requeries_by_post_enrichment_name_and_identity(self):
        """Collision after enrichment must re-query by catalog identity, never None."""
        from sqlalchemy.exc import IntegrityError
        from app.services.target_resolver import _create_target

        session = MagicMock()
        session.flush.side_effect = IntegrityError("dup", {}, None)
        existing = MagicMock()
        existing.id = "winner"
        session.execute.return_value.scalar_one_or_none.return_value = existing

        with patch("app.services.target_resolver.match_target_by_identity", return_value=None):
            result = _create_target(self._simbad(), "NGC 6543", session)

        assert result == "winner"
        session.rollback.assert_called_once()


class TestCreateTargetEnrichmentRenameLinksRealChain:
    """End-to-end: real OpenNGC rename must feed the identity match and link.

    Pins the literal NGC 6543 scenario: a first-seen 'NGC 6543' resolves to a
    bare primary_name, the REAL enrich_target_from_openngc renames it to
    'NGC 6543 - Cat's Eye Nebula', and the REAL match_target_by_identity then
    links to the pre-existing Cat's Eye target by normalized catalog identity
    instead of inserting a row that would collide on the unique primary_name.
    Only lookup_openngc is stubbed (to supply the OpenNGC common name), so the
    enrich -> match -> link chain runs for real.
    """

    def test_openngc_rename_links_to_existing_identity(self):
        from app.services.target_resolver import _create_target

        existing = MagicMock()
        existing.id = "cats-eye-existing"
        existing.primary_name = "NGC 6543 - Cat's Eye Nebula"
        existing.catalog_id = "NGC 6543"
        existing.catalog_id_normalized = "NGC 6543"
        existing.aliases = ["NGC 6543"]

        session = MagicMock()
        # Both the OpenNGC lookup inside enrichment and the identity lookup go
        # through session.execute; the identity lookup is the one that resolves
        # to the seeded Cat's Eye target by catalog_id_normalized.
        session.execute.return_value.scalar_one_or_none.return_value = existing

        # A real OpenNGC entry carrying the common name so the rename happens for
        # real. The six enrichment fields are None so the axis/mag loop is a
        # no-op and only the common-name rename fires.
        ngc_entry = MagicMock()
        ngc_entry.common_names = "Cat's Eye Nebula"
        ngc_entry.constellation = None
        ngc_entry.major_axis = None
        ngc_entry.minor_axis = None
        ngc_entry.position_angle = None
        ngc_entry.v_mag = None
        ngc_entry.surface_brightness = None

        simbad_result = {
            "primary_name": "NGC 6543",
            "catalog_id": "NGC 6543",
            "common_name": None,
            "aliases": ["NGC 6543"],
            "ra": 269.6, "dec": 66.6, "object_type": "PN",
        }

        # Capture the real Target instance (without replacing the class, which
        # would break the matcher's select(Target)) to prove the REAL OpenNGC
        # rename fired before the match.
        from app.services import target_resolver as tr
        RealTarget = tr.Target
        built = {}

        class _CapturingTarget(RealTarget):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                built["instance"] = self

        with patch("app.services.openngc.lookup_openngc", return_value=ngc_entry), \
             patch("app.services.target_resolver.Target", _CapturingTarget):
            result = _create_target(simbad_result, "NGC 6543", session)

        # The real enrichment renamed the in-memory target before matching.
        assert built["instance"].primary_name == "NGC 6543 - Cat's Eye Nebula"
        assert built["instance"].common_name == "Cat's Eye Nebula"
        # Linked to the existing target, no insert, never None.
        assert result == "cats-eye-existing"
        session.add.assert_not_called()


class TestNegativeCacheCorrectness:
    def _simbad(self):
        return {
            "primary_name": "NGC 6543", "catalog_id": "NGC 6543",
            "common_name": None, "aliases": ["NGC 6543"],
            "ra": 269.6, "dec": 66.6, "object_type": "PN",
        }

    def test_resolved_identity_never_writes_negative_cache(self):
        """A name that resolves to a catalog identity must never be negative-cached,
        even if _create_target transiently returns None (e.g. a lost create race)."""
        from app.services.target_resolver import resolve_target

        session = MagicMock()
        redis = MagicMock()
        redis.sismember.return_value = False

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=self._simbad()), \
             patch("app.services.target_resolver.match_target_by_identity", return_value=None), \
             patch("app.services.target_resolver._create_target", return_value=None):
            result = resolve_target("NGC 6543", session, redis=redis)

        assert result is None
        redis.sadd.assert_not_called()

    def test_unresolvable_name_still_negative_cached(self):
        from app.services.target_resolver import resolve_target

        session = MagicMock()
        redis = MagicMock()
        redis.sismember.return_value = False

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=None), \
             patch("app.services.target_resolver.resolve_sesame_cached", return_value=None):
            result = resolve_target("FlatWizard", session, redis=redis)

        assert result is None
        redis.sadd.assert_called_once()

    def test_resolve_uses_identity_matcher_after_simbad(self):
        from app.services.target_resolver import resolve_target

        session = MagicMock()
        redis = MagicMock()
        redis.sismember.return_value = False
        existing = MagicMock()
        existing.id = "cats-eye"

        with patch("app.services.target_resolver.find_target_by_name", return_value=None), \
             patch("app.services.target_resolver.resolve_target_name_cached", return_value=self._simbad()), \
             patch("app.services.target_resolver.match_target_by_identity", return_value=existing):
            result = resolve_target("NGC 6543", session, redis=redis)

        assert result == "cats-eye"
