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

    assert row.general["phd2_profile_map"] == {
        "P_OAG": {
            "telescope": "SVBony 80ED",
            "timezone": "",
            "latitude": None,
            "longitude": None,
        },
    }
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
    assert row.general["phd2_profile_map"] == {
        "P_OAG": {
            "telescope": "SVBony 80ED",
            "timezone": "",
            "latitude": None,
            "longitude": None,
        },
    }


@pytest.mark.asyncio
async def test_folding_a_telescope_name_keeps_that_profile_s_zone_and_site(monkeypatch):
    """The zone and the site of a rig are not equipment.

    Grouping two telescope names is an equipment edit, and it must not be able
    to clear the timezone a rig's logs are read in: that would silently move
    every one of its guiding sessions by hours and file its nights under the
    wrong date.
    """
    from app.api import settings as settings_api
    from app.schemas.settings import EquipmentConfig

    class _Row:
        def __init__(self):
            self.equipment = {}
            self.general = {
                "phd2_profile_map": {
                    "Remote": {
                        "telescope": "SVBony SV503 80mm",
                        "timezone": "America/Chicago",
                        "latitude": 30.27,
                        "longitude": -97.74,
                    },
                    "Home": {
                        "telescope": None,
                        "timezone": "Europe/Berlin",
                        "latitude": None,
                        "longitude": None,
                    },
                },
            }

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

    assert row.general["phd2_profile_map"] == {
        "Remote": {
            "telescope": "SVBony 80ED",
            "timezone": "America/Chicago",
            "latitude": 30.27,
            "longitude": -97.74,
        },
        "Home": {
            "telescope": None,
            "timezone": "Europe/Berlin",
            "latitude": None,
            "longitude": None,
        },
    }
    assert dispatched == [{"remap_only": True}]


@pytest.mark.asyncio
async def test_a_rig_on_the_prime_meridian_keeps_its_longitude(monkeypatch):
    """Zero is Greenwich, not "unset". A regrouping must leave it alone."""
    from app.api import settings as settings_api
    from app.schemas.settings import EquipmentConfig

    class _Row:
        def __init__(self):
            self.equipment = {}
            self.general = {
                "phd2_profile_map": {
                    "Greenwich": {
                        "telescope": "SVBony SV503 80mm",
                        "timezone": "Europe/London",
                        "latitude": 0.0,
                        "longitude": 0.0,
                    },
                },
            }

    row = _Row()

    class _Session:
        async def commit(self):
            pass

        async def refresh(self, _row):
            pass

    class _Task:
        @staticmethod
        def delay(**kwargs):
            pass

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

    entry = row.general["phd2_profile_map"]["Greenwich"]
    assert entry["telescope"] == "SVBony 80ED"
    assert entry["latitude"] == 0.0
    assert entry["longitude"] == 0.0
