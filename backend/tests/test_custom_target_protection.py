"""Custom (user_defined) targets must never be mutated by enrichment."""
import pathlib
from unittest.mock import MagicMock

from app.models.target import Target
from app.services.openngc import enrich_target_from_openngc
from app.services.sac import enrich_target_from_sac
from app.services.vizier import enrich_target_from_vizier
from app.services.hyperleda import enrich_target_from_hyperleda


def _rebuild_targets_source() -> str:
    """Return the body of the rebuild_targets task without importing tasks.py.

    tasks.py imports fitsio (not installed in CI), so read the source directly
    and slice out the rebuild_targets function.
    """
    src = (
        pathlib.Path(__file__).resolve().parent.parent
        / "app" / "worker" / "tasks.py"
    ).read_text(encoding="utf-8")
    start = src.index("def rebuild_targets(")
    end = src.index("@celery_app.task", start)
    return src[start:end]


def _custom_target():
    t = MagicMock(spec=Target)
    t.user_defined = True
    t.catalog_id = "NGC 9999"
    t.aliases = []
    t.object_type = "Planet"
    return t


def test_openngc_enrichment_skips_user_defined():
    session = MagicMock()
    assert enrich_target_from_openngc(session, _custom_target()) is False
    session.execute.assert_not_called()


def test_vizier_enrichment_skips_user_defined():
    session = MagicMock()
    assert enrich_target_from_vizier(session, _custom_target()) is False
    session.execute.assert_not_called()


def test_sac_enrichment_skips_user_defined():
    session = MagicMock()
    assert enrich_target_from_sac(session, _custom_target()) is False
    session.execute.assert_not_called()


def test_hyperleda_enrichment_skips_user_defined():
    session = MagicMock()
    assert enrich_target_from_hyperleda(session, _custom_target()) is False
    session.execute.assert_not_called()


def test_full_rebuild_preserves_user_defined_targets():
    """rebuild_targets must not delete custom targets nor unlink their images."""
    body = _rebuild_targets_source()
    # Custom targets survive the wipe.
    assert "DELETE FROM targets WHERE user_defined = FALSE" in body
    assert "DELETE FROM targets\n" not in body  # no unconditional delete
    # Images attached to a surviving custom target are not unlinked.
    assert "user_defined = TRUE" in body
    assert "UPDATE images SET resolved_target_id = NULL\n        \"\"\"" not in body
