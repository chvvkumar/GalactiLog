"""Saving equipment aliases must not strand the PHD2 profile map.

The map's values are telescope names the user picked when they mapped each
profile. Grouping two telescope names together afterwards turns one of those
values into an alias, and nothing rewrote the map. Reads survive that through
alias expansion; the correlation writes do not, because they attribute on the
stored value.
"""
import pytest


@pytest.mark.asyncio
async def test_a_map_value_that_became_an_alias_is_rewritten_to_canonical(monkeypatch):
    from app.api import settings as settings_api
    from app.schemas.settings import EquipmentConfig

    class _Row:
        def __init__(self):
            self.equipment = {}
            self.general = {"phd2_profile_map": {"P_OAG": "SVBony SV503 80mm"}}

    row = _Row()

    class _Session:
        async def commit(self):
            pass

        async def refresh(self, _row):
            pass

    async def _get_or_create(_session):
        return row

    dispatched = []

    class _Task:
        @staticmethod
        def delay(**kwargs):
            dispatched.append(kwargs)

    monkeypatch.setattr(settings_api, "_get_or_create_settings", _get_or_create)
    monkeypatch.setattr(settings_api, "invalidate_alias_cache", lambda: None)
    monkeypatch.setattr(settings_api, "_row_to_response", lambda r: r)
    monkeypatch.setitem(
        __import__("sys").modules, "app.worker.tasks",
        type("M", (), {"scan_phd2_logs": _Task})(),
    )

    payload = EquipmentConfig.model_validate({
        "telescopes": {"SVBony 80ED": {"aliases": ["SVBony SV503 80mm"]}},
    })
    await settings_api.update_equipment(payload, _Session(), user=None)

    assert row.general["phd2_profile_map"] == {"P_OAG": "SVBony 80ED"}
    assert dispatched == [{"remap_only": True}]


@pytest.mark.asyncio
async def test_an_unaffected_map_is_left_alone_and_nothing_is_dispatched(monkeypatch):
    """A save that changes no PHD2 mapping must not queue a remap pass: the
    pass re-reads and rewrites every guiding session in the catalog."""
    from app.api import settings as settings_api
    from app.schemas.settings import EquipmentConfig

    class _Row:
        def __init__(self):
            self.equipment = {}
            self.general = {"phd2_profile_map": {"P_OAG": "SVBony 80ED"}}

    row = _Row()

    class _Session:
        async def commit(self):
            pass

        async def refresh(self, _row):
            pass

    dispatched = []

    class _Task:
        @staticmethod
        def delay(**kwargs):
            dispatched.append(kwargs)

    monkeypatch.setattr(settings_api, "_get_or_create_settings", lambda s: _async(row))
    monkeypatch.setattr(settings_api, "invalidate_alias_cache", lambda: None)
    monkeypatch.setattr(settings_api, "_row_to_response", lambda r: r)
    monkeypatch.setitem(
        __import__("sys").modules, "app.worker.tasks",
        type("M", (), {"scan_phd2_logs": _Task})(),
    )

    payload = EquipmentConfig.model_validate({
        "telescopes": {"SVBony 80ED": {"aliases": ["SVBony SV503 80mm"]}},
    })
    await settings_api.update_equipment(payload, _Session(), user=None)

    assert row.general["phd2_profile_map"] == {"P_OAG": "SVBony 80ED"}
    assert dispatched == []


async def _async(value):
    return value


@pytest.mark.asyncio
async def test_a_missing_worker_does_not_fail_the_save(monkeypatch):
    """Dev runs with no worker. A settings save must still succeed."""
    from app.api import settings as settings_api
    from app.schemas.settings import EquipmentConfig

    class _Row:
        def __init__(self):
            self.equipment = {}
            self.general = {"phd2_profile_map": {"P_OAG": "SVBony SV503 80mm"}}

    row = _Row()

    class _Session:
        async def commit(self):
            pass

        async def refresh(self, _row):
            pass

    class _Broken:
        @staticmethod
        def delay(**kwargs):
            raise RuntimeError("no broker")

    monkeypatch.setattr(settings_api, "_get_or_create_settings", lambda s: _async(row))
    monkeypatch.setattr(settings_api, "invalidate_alias_cache", lambda: None)
    monkeypatch.setattr(settings_api, "_row_to_response", lambda r: r)
    monkeypatch.setitem(
        __import__("sys").modules, "app.worker.tasks",
        type("M", (), {"scan_phd2_logs": _Broken})(),
    )

    payload = EquipmentConfig.model_validate({
        "telescopes": {"SVBony 80ED": {"aliases": ["SVBony SV503 80mm"]}},
    })
    await settings_api.update_equipment(payload, _Session(), user=None)
    assert row.general["phd2_profile_map"] == {"P_OAG": "SVBony 80ED"}
