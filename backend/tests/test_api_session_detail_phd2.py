"""Night+rig attribution rules for the session-detail PHD2 summary."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.phd2 import Phd2NightSummary
from app.schemas.target import SessionDetailResponse
from app.services.phd2_metrics import aggregate_night
from app.services.target_detail import select_phd2_night_rows


def _row(telescope, profile, frame_count=200):
    return SimpleNamespace(
        telescope=telescope, equipment_profile=profile, frame_count=frame_count,
        rms_ra_arcsec=1.0, rms_dec_arcsec=1.0, rms_total_arcsec=1.4,
        drop_count=1, max_drop_run=1, unguided_seconds=1.0,
        dither_count=1, settle_failed_count=0, settle_median_s=3.0,
        last_cal_issue=None,
    )


def test_mapped_rig_rows_are_selected():
    rows = [_row("140APO", "AM5n_OAG_ASI174M"), _row("RedCat 51", "ASI220mm_30F5_AM5")]
    selected = select_phd2_night_rows(rows, {"140APO"})
    assert [r.telescope for r in selected] == ["140APO"]


def test_unmapped_profile_is_used_when_it_is_the_nights_only_profile():
    rows = [_row(None, "AM5n_OAG_ASI174M"), _row(None, "AM5n_OAG_ASI174M")]
    selected = select_phd2_night_rows(rows, {"140APO"})
    assert len(selected) == 2


def test_unmapped_profile_is_skipped_on_a_multi_rig_night():
    rows = [_row(None, "AM5n_OAG_ASI174M"), _row(None, "ASI220mm_30F5_AM5")]
    assert select_phd2_night_rows(rows, {"140APO"}) == []


def test_a_profile_mapped_to_another_rig_is_never_borrowed():
    """The sole-profile fallback is for the pre-configuration state only. Once
    a profile is mapped, the user has said which rig it guides, and returning
    its sessions to a different rig would put the guided rig's numbers and
    graph on the unguided rig's card."""
    rows = [_row("RedCat 51", "ASI220mm_30F5_AM5"), _row("RedCat 51", "ASI220mm_30F5_AM5")]
    assert select_phd2_night_rows(rows, {"140APO"}) == []


def test_no_rows_selects_nothing():
    assert select_phd2_night_rows([], {"140APO"}) == []


def _rows_result(rows):
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _use_alias_map(monkeypatch, tel_map):
    """Patch the shared reader, not target_detail's import of it.

    `load_telescope_match_set` resolves `load_alias_maps` in its own module,
    so patching it there covers the night summary and the /phd2/sessions route
    identically, and keeps the in-process alias cache out of the test.
    """
    from app.services import normalization

    async def _load(_session):
        return {}, {}, tel_map

    monkeypatch.setattr(normalization, "load_alias_maps", _load)


@pytest.mark.asyncio
async def test_night_summary_matches_a_telescope_through_its_alias(monkeypatch):
    """Production case: frames are catalogued as "SVBony SV503 80mm" while the
    profile map holds the canonical "SVBony 80ED". Comparing raw strings threw
    the whole night's guiding away."""
    from app.services import target_detail

    _use_alias_map(monkeypatch, {"SVBony SV503 80mm": "SVBony 80ED"})
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_rows_result([_row("SVBony 80ED", "ASI220mm_30F5_AM5")])
    )

    summary = await target_detail.build_phd2_night_summary(
        db, date(2026, 7, 14), {"SVBony SV503 80mm"}
    )
    assert summary is not None
    assert summary.session_count == 1


@pytest.mark.asyncio
async def test_night_summary_matches_a_profile_map_holding_an_aliased_name(monkeypatch):
    """The other ordering: the profile was mapped first, so the map holds the
    name that later became an alias, and PUT /settings/equipment never
    re-keys it. Folding the frame's name onto the canonical one and stopping
    there sent the night dark from the opposite direction."""
    from app.services import target_detail

    _use_alias_map(monkeypatch, {"SVBony SV503 80mm": "SVBony 80ED"})
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_rows_result([_row("SVBony SV503 80mm", "ASI220mm_30F5_AM5")])
    )

    summary = await target_detail.build_phd2_night_summary(
        db, date(2026, 7, 14), {"SVBony SV503 80mm"}
    )
    assert summary is not None
    assert summary.session_count == 1


def test_equipment_match_set_holds_the_canonical_name_and_every_alias():
    """Neither side of the PHD2 comparison can be assumed canonical, so the
    match set has to carry both forms whichever form was supplied."""
    from app.services.normalization import equipment_match_set

    tel_map = {"SVBony SV503 80mm": "SVBony 80ED", "SV503": "SVBony 80ED"}
    expected = {"SVBony 80ED", "SVBony SV503 80mm", "SV503"}
    assert equipment_match_set(["SVBony SV503 80mm"], tel_map) == expected
    assert equipment_match_set(["SVBony 80ED"], tel_map) == expected
    assert equipment_match_set(["140APO"], tel_map) == {"140APO"}
    assert equipment_match_set([None, ""], tel_map) == set()


@pytest.mark.asyncio
async def test_night_summary_still_matches_a_canonical_name_with_no_alias(monkeypatch):
    """A canonical name maps to itself, so installs that never grouped their
    equipment behave exactly as before."""
    from app.services import target_detail

    _use_alias_map(monkeypatch, {})
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_rows_result([_row("140APO", "AM5n_OAG_ASI174M")])
    )

    summary = await target_detail.build_phd2_night_summary(
        db, date(2026, 7, 14), {"140APO"}
    )
    assert summary is not None
    assert summary.session_count == 1


@pytest.mark.asyncio
async def test_night_summary_does_not_borrow_a_rig_mapped_elsewhere(monkeypatch):
    """Two rigs ran, only one was guided by PHD2, and its profile is mapped.
    The unguided rig's card must stay empty rather than show the other's."""
    from app.services import target_detail

    _use_alias_map(monkeypatch, {})
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_rows_result([_row("RedCat 51", "ASI220mm_30F5_AM5")])
    )

    summary = await target_detail.build_phd2_night_summary(
        db, date(2026, 7, 14), {"140APO"}
    )
    assert summary is None


@pytest.mark.asyncio
async def test_night_summary_falls_back_to_the_sole_unmapped_profile(monkeypatch):
    """Before any profile is mapped every stored telescope is NULL, and the
    night's only profile is the only thing that could have guided it."""
    from app.services import target_detail

    _use_alias_map(monkeypatch, {})
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_rows_result([
        _row(None, "AM5n_OAG_ASI174M"), _row(None, "AM5n_OAG_ASI174M"),
    ]))

    summary = await target_detail.build_phd2_night_summary(
        db, date(2026, 7, 14), {"140APO"}
    )
    assert summary is not None
    assert summary.session_count == 2


def test_aggregate_night_output_constructs_the_night_summary():
    """The endpoint builds the response as Phd2NightSummary(**aggregate_night(...)).
    Nothing else pins those two key sets together, so a renamed or added
    aggregate key would only surface as a 500 in production."""
    rows = [
        _row("140APO", "AM5n_OAG_ASI174M"),
        _row("140APO", "AM5n_OAG_ASI174M", frame_count=30),
    ]
    aggregate = aggregate_night(rows)
    summary = Phd2NightSummary(**aggregate)
    assert set(aggregate) == set(Phd2NightSummary.model_fields)
    assert summary.session_count == 2
    assert summary.gated_session_count == 1
    assert summary.profiles == ["AM5n_OAG_ASI174M"]


def test_session_detail_response_accepts_the_summary_and_defaults_to_none():
    base = dict(
        target_name="M 42", session_date="2026-07-14", frame_count=10,
        integration_seconds=3000.0, filters_used={"Ha": 10},
        equipment={"camera": "ASI2600MM", "telescope": "140APO"},
    )
    assert SessionDetailResponse(**base).phd2 is None
    with_summary = SessionDetailResponse(**base, phd2=Phd2NightSummary(
        session_count=3, gated_session_count=1, frame_count=510,
        rms_ra_arcsec=1.61, rms_dec_arcsec=1.4, rms_total_arcsec=2.13,
        drop_count=6, max_drop_run=2, unguided_seconds=9.0,
        dither_count=3, settle_failed_count=1, settle_median_s=4.0,
        cal_issues=["Orthogonality"], profiles=["AM5n_OAG_ASI174M"],
    ))
    assert with_summary.phd2.session_count == 3
    assert with_summary.phd2.cal_issues == ["Orthogonality"]
    assert with_summary.model_dump()["phd2"]["gated_session_count"] == 1
