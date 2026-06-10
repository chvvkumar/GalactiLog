"""Custom (user_defined) targets must never be mutated by enrichment."""
from unittest.mock import MagicMock

from app.models.target import Target
from app.services.openngc import enrich_target_from_openngc
from app.services.sac import enrich_target_from_sac
from app.services.vizier import enrich_target_from_vizier
from app.services.hyperleda import enrich_target_from_hyperleda


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
