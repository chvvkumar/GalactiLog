"""Tests for the generic catalog_cache client wrapper (app/services/catalog_cache.py).

Uses a real sync engine against the test DB (same _sync_session_factory
pattern as test_catalog_cache_migration.py / test_data_jobs.py) since the
upsert/negative/expiry behavior depends on real Postgres ON CONFLICT +
JSONB semantics.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "GALACTILOG_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_catalog",
)

from app.services import catalog_cache as cc  # noqa: E402

TEST_MARK = "zzcachetest"


def _sync_session_factory():
    url = os.environ["GALACTILOG_DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        conn = engine.connect()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"test DB not reachable: {exc}")
    return sessionmaker(bind=engine), engine


@pytest.fixture
def db():
    Session, engine = _sync_session_factory()
    yield Session
    engine.dispose()


@pytest.fixture
def session(db):
    Session = db
    s = Session()
    s.execute(text("DELETE FROM catalog_cache WHERE source = :src"), {"src": TEST_MARK})
    s.commit()
    try:
        yield s
    finally:
        s.execute(text("DELETE FROM catalog_cache WHERE source = :src"), {"src": TEST_MARK})
        s.commit()
        s.close()


@pytest.fixture(autouse=True)
def no_real_sleep():
    """Retry tests exercise real backoff math; don't actually block on it."""
    with patch.object(cc.time, "sleep") as mock_sleep:
        yield mock_sleep


# ---------------------------------------------------------------------------
# hit / miss / positive store
# ---------------------------------------------------------------------------

def test_cache_hit_skips_fetch(session):
    cc.save_cached(session, TEST_MARK, "k1", {"a": 1})
    session.commit()

    fetch = lambda: pytest.fail("fetch() should not be called on a cache hit")  # noqa: E731
    result = cc.get_or_fetch(session, TEST_MARK, "k1", fetch)
    assert result == {"a": 1}


def test_cache_miss_calls_fetch_and_stores_positive_result(session):
    calls = []

    def fetch():
        calls.append(1)
        return {"main_id": "M31"}

    result = cc.get_or_fetch(session, TEST_MARK, "k2", fetch)
    session.commit()

    assert result == {"main_id": "M31"}
    assert len(calls) == 1

    # Stored: a second call must not re-invoke fetch.
    result2 = cc.get_or_fetch(session, TEST_MARK, "k2", lambda: pytest.fail("should not refetch"))
    assert result2 == {"main_id": "M31"}


def test_get_cached_and_save_cached_raw_pair(session):
    assert cc.get_cached(session, TEST_MARK, "k3") is None
    cc.save_cached(session, TEST_MARK, "k3", {"x": 1})
    session.commit()
    assert cc.get_cached(session, TEST_MARK, "k3") == {"x": 1}


# ---------------------------------------------------------------------------
# negative caching
# ---------------------------------------------------------------------------

def test_failed_fetch_stores_negative_and_suppresses_refetch(session):
    calls = []

    def fetch():
        calls.append(1)
        return None  # queried successfully, nothing found

    result = cc.get_or_fetch(session, TEST_MARK, "k4", fetch)
    session.commit()
    assert result is None
    assert len(calls) == 1

    assert cc.get_cached(session, TEST_MARK, "k4") == cc.NEGATIVE

    # Subsequent call must NOT re-fetch -- this is the phase's explicit
    # "negative cache still suppresses refetch" verification bar.
    result2 = cc.get_or_fetch(
        session, TEST_MARK, "k4", lambda: pytest.fail("negative cache must suppress refetch"),
    )
    assert result2 is None


def test_clear_negative_allows_refetch(session):
    cc.save_cached(session, TEST_MARK, "k5", None)
    session.commit()
    assert cc.get_cached(session, TEST_MARK, "k5") == cc.NEGATIVE

    deleted = cc.clear_negative(session, TEST_MARK, "k5")
    session.commit()
    assert deleted == 1
    assert cc.get_cached(session, TEST_MARK, "k5") is None

    calls = []
    result = cc.get_or_fetch(session, TEST_MARK, "k5", lambda: calls.append(1) or {"ok": True})
    assert result == {"ok": True}
    assert len(calls) == 1


def test_clear_negative_does_not_touch_positive_rows(session):
    cc.save_cached(session, TEST_MARK, "k5pos", {"a": 1})
    cc.save_cached(session, TEST_MARK, "k5neg", None)
    session.commit()

    deleted = cc.clear_negative(session, TEST_MARK)
    session.commit()

    assert deleted == 1
    assert cc.get_cached(session, TEST_MARK, "k5pos") == {"a": 1}
    assert cc.get_cached(session, TEST_MARK, "k5neg") is None


def test_invalidate_deletes_regardless_of_negative_flag(session):
    cc.save_cached(session, TEST_MARK, "k6pos", {"a": 1})
    cc.save_cached(session, TEST_MARK, "k6neg", None)
    session.commit()

    deleted = cc.invalidate(session, TEST_MARK)
    session.commit()

    assert deleted == 2
    assert cc.get_cached(session, TEST_MARK, "k6pos") is None
    assert cc.get_cached(session, TEST_MARK, "k6neg") is None


# ---------------------------------------------------------------------------
# retry / backoff
# ---------------------------------------------------------------------------

def test_retry_then_success(session, no_real_sleep):
    attempts = []

    def fetch():
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectError("boom")
        return {"ok": True}

    result = cc.get_or_fetch(session, TEST_MARK, "k7", fetch, max_attempts=3)
    session.commit()

    assert result == {"ok": True}
    assert len(attempts) == 3
    assert no_real_sleep.call_count == 2
    # Sleeps followed the documented backoff_base * 2**attempt formula.
    no_real_sleep.assert_any_call(1.0)
    no_real_sleep.assert_any_call(2.0)

    # Result is cached: a further call must not invoke fetch again.
    result2 = cc.get_or_fetch(session, TEST_MARK, "k7", lambda: pytest.fail("should be cached"))
    assert result2 == {"ok": True}


def test_retry_exhausted_returns_none_without_caching(session, no_real_sleep):
    """An outage is not evidence the object is missing: no negative row."""
    attempts = []

    def fetch():
        attempts.append(1)
        raise httpx.ConnectError("always fails")

    result = cc.get_or_fetch(session, TEST_MARK, "k8", fetch, max_attempts=3)
    session.commit()

    assert result is None
    assert len(attempts) == 3
    assert cc.get_cached(session, TEST_MARK, "k8") is None

    # Nothing cached, so once the outage marker is gone the next call goes
    # back to the network.
    cc.clear_outages()
    result2 = cc.get_or_fetch(session, TEST_MARK, "k8", lambda: {"ok": True})
    assert result2 == {"ok": True}


def test_non_transient_error_does_not_retry_and_does_not_cache(session, no_real_sleep):
    attempts = []

    def fetch():
        attempts.append(1)
        request = httpx.Request("GET", "https://example.test")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    with pytest.raises(cc.NonTransientError):
        cc.get_or_fetch(session, TEST_MARK, "k9", fetch, max_attempts=3)
    session.commit()

    assert len(attempts) == 1
    assert no_real_sleep.call_count == 0
    assert cc.get_cached(session, TEST_MARK, "k9") is None


def test_non_transient_error_message_and_attributes(session, no_real_sleep):
    request = httpx.Request("GET", "https://example.test/secret/path")
    response = httpx.Response(404, request=request)
    original = httpx.HTTPStatusError("not found", request=request, response=response)

    def fetch():
        raise original

    with pytest.raises(cc.NonTransientError) as excinfo:
        cc.get_or_fetch(session, "simbad", f"{TEST_MARK} M31", fetch, max_attempts=3)
    session.rollback()

    err = excinfo.value
    assert str(err) == (
        f"SIMBAD lookup for '{TEST_MARK} M31' failed: SIMBAD returned HTTP 404 (Not Found)"
    )
    assert "example.test" not in str(err)
    assert err.source == "simbad"
    assert err.key == f"{TEST_MARK} M31"
    assert err.original is original
    assert err.__cause__ is original

    # Plain positional construction still works.
    bare = cc.NonTransientError("some text")
    assert str(bare) == "some text"
    assert bare.source is None and bare.key is None and bare.original is None


def test_transient_429_does_retry(session, no_real_sleep):
    attempts = []

    def fetch():
        attempts.append(1)
        if len(attempts) < 2:
            request = httpx.Request("GET", "https://example.test")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
        return {"ok": True}

    result = cc.get_or_fetch(session, TEST_MARK, "k10", fetch, max_attempts=3)
    session.commit()

    assert result == {"ok": True}
    assert len(attempts) == 2
    assert no_real_sleep.call_count == 1


# ---------------------------------------------------------------------------
# expiry (opt-in TTL)
# ---------------------------------------------------------------------------

def test_positive_ttl_expiry_causes_refetch(session):
    cc.save_cached(session, TEST_MARK, "k11", {"stale": True})
    session.commit()
    # Backdate fetched_at so it's older than the TTL.
    session.execute(
        text(
            "UPDATE catalog_cache SET fetched_at = now() - interval '2 hours' "
            "WHERE source = :src AND key = :key"
        ),
        {"src": TEST_MARK, "key": "k11"},
    )
    session.commit()

    calls = []

    def fetch():
        calls.append(1)
        return {"fresh": True}

    result = cc.get_or_fetch(
        session, TEST_MARK, "k11", fetch, positive_ttl=timedelta(hours=1),
    )
    session.commit()

    assert result == {"fresh": True}
    assert len(calls) == 1
    assert cc.get_cached(session, TEST_MARK, "k11") == {"fresh": True}


def test_positive_ttl_not_expired_skips_fetch(session):
    cc.save_cached(session, TEST_MARK, "k12", {"fresh": True})
    session.commit()

    result = cc.get_or_fetch(
        session, TEST_MARK, "k12",
        lambda: pytest.fail("should not refetch a fresh row"),
        positive_ttl=timedelta(hours=1),
    )
    assert result == {"fresh": True}


def test_negative_ttl_expiry_allows_refetch(session):
    cc.save_cached(session, TEST_MARK, "k13", None)
    session.commit()
    session.execute(
        text(
            "UPDATE catalog_cache SET fetched_at = now() - interval '2 days' "
            "WHERE source = :src AND key = :key"
        ),
        {"src": TEST_MARK, "key": "k13"},
    )
    session.commit()

    calls = []

    def fetch():
        calls.append(1)
        return {"ok": True}

    result = cc.get_or_fetch(
        session, TEST_MARK, "k13", fetch, negative_ttl=timedelta(days=1),
    )
    session.commit()

    assert result == {"ok": True}
    assert len(calls) == 1


def test_default_ttls_never_expire(session):
    """Default behavior must exactly match today's 'cache forever' semantics."""
    cc.save_cached(session, TEST_MARK, "k14", {"old": True})
    session.commit()
    session.execute(
        text(
            "UPDATE catalog_cache SET fetched_at = now() - interval '365 days' "
            "WHERE source = :src AND key = :key"
        ),
        {"src": TEST_MARK, "key": "k14"},
    )
    session.commit()

    result = cc.get_or_fetch(
        session, TEST_MARK, "k14", lambda: pytest.fail("default TTL must never expire"),
    )
    assert result == {"old": True}


# ---------------------------------------------------------------------------
# outage marker / circuit breaker (no database: MagicMock session)
# ---------------------------------------------------------------------------

def _miss_session():
    s = MagicMock()
    s.get.return_value = None  # real cc.get_cached: cache miss
    return s


def _status_error(status):
    request = httpx.Request("GET", "https://example.test/secret/path")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("raw", request=request, response=response)


def _raiser(exc):
    def fetch():
        raise exc
    return fetch


def test_outage_marked_when_transient_retries_exhausted():
    s = _miss_session()
    assert cc.outage("simbad") is None

    result = cc.get_or_fetch(s, "simbad", "M31", _raiser(httpx.ConnectTimeout("slow")))

    assert result is None
    assert cc.outage("simbad") == "SIMBAD timed out"
    assert cc.outage("vizier") is None
    s.execute.assert_not_called()


def test_outage_marked_on_non_transient_error():
    s = _miss_session()

    with pytest.raises(cc.NonTransientError):
        cc.get_or_fetch(s, "simbad", "M31", _raiser(_status_error(404)))

    assert cc.outage("simbad") == "SIMBAD returned HTTP 404 (Not Found)"


@pytest.mark.parametrize("status", [400, 413, 414, 422])
def test_request_specific_error_does_not_mark_outage(status):
    """One rejected key must not take the whole source down."""
    s = _miss_session()

    with pytest.raises(cc.NonTransientError):
        cc.get_or_fetch(s, "simbad", "bad key", _raiser(_status_error(status)))

    assert cc.outage("simbad") is None
    cc.raise_if_outage("simbad", key="bad key")

    fetch = MagicMock(return_value={"ok": True})
    assert cc.get_or_fetch(s, "simbad", "M31", fetch) == {"ok": True}
    fetch.assert_called_once()


def _fallback_failure(*statuses):
    """Shaped like upstream.request_with_fallback's combined failure."""
    originals = [_status_error(status) for status in statuses]
    last = originals[-1]
    exc = httpx.HTTPStatusError(
        "SIMBAD is unavailable: a.test failed; b.test failed",
        request=last.request, response=last.response,
    )
    exc.attempts = [(f"https://m{i}.test/x", o) for i, o in enumerate(originals)]
    return exc


def test_mixed_mirror_attempts_mark_outage():
    s = _miss_session()

    with pytest.raises(cc.NonTransientError):
        cc.get_or_fetch(s, "simbad", "M31", _raiser(_fallback_failure(404, 400)))

    assert cc.outage("simbad") == "SIMBAD is unavailable: a.test failed; b.test failed"


def test_all_request_specific_mirror_attempts_do_not_mark_outage():
    s = _miss_session()

    with pytest.raises(cc.NonTransientError):
        cc.get_or_fetch(s, "simbad", "bad key", _raiser(_fallback_failure(400, 400)))

    assert cc.outage("simbad") is None


def test_outage_reason_uses_fallback_message_when_attempts_present():
    s = _miss_session()
    exc = httpx.ConnectError("SIMBAD is unavailable: a.test could not be reached")
    exc.attempts = [("https://a.test/x", httpx.ConnectError("dns"))]

    cc.get_or_fetch(s, "simbad", "M31", _raiser(exc))

    assert cc.outage("simbad") == "SIMBAD is unavailable: a.test could not be reached"


def test_get_or_fetch_short_circuits_while_marked(no_real_sleep):
    s = _miss_session()
    cc.get_or_fetch(s, "simbad", "M31", _raiser(httpx.ConnectTimeout("slow")))
    no_real_sleep.reset_mock()

    fetch = MagicMock()
    assert cc.get_or_fetch(s, "simbad", "M42", fetch) is None

    fetch.assert_not_called()
    no_real_sleep.assert_not_called()
    s.execute.assert_not_called()

    # Other sources are unaffected.
    other = MagicMock(return_value={"ok": True})
    assert cc.get_or_fetch(s, "vizier", "M42", other) == {"ok": True}
    other.assert_called_once()


def test_outage_expires_after_cooldown(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(cc.time, "monotonic", lambda: now[0])
    s = _miss_session()
    cc.get_or_fetch(s, "simbad", "M31", _raiser(httpx.ConnectTimeout("slow")))

    now[0] += cc.OUTAGE_COOLDOWN_SECONDS - 1
    assert cc.outage("simbad") is not None

    # Between expiry and the probe nothing is reported as an outage.
    now[0] += 1
    assert cc.outage("simbad") is None
    cc.raise_if_outage("simbad", key="M31")

    fetch = MagicMock(return_value={"ok": True})
    assert cc.get_or_fetch(s, "simbad", "M31", fetch) == {"ok": True}
    fetch.assert_called_once()
    assert "simbad" not in cc._OUTAGES


def test_failed_probe_after_expiry_is_single_attempt_and_remarks(monkeypatch, no_real_sleep):
    now = [1000.0]
    monkeypatch.setattr(cc.time, "monotonic", lambda: now[0])
    s = _miss_session()
    cc.get_or_fetch(s, "simbad", "M31", _raiser(httpx.ConnectTimeout("slow")))
    now[0] += cc.OUTAGE_COOLDOWN_SECONDS
    assert cc.outage("simbad") is None
    no_real_sleep.reset_mock()

    probe = MagicMock(side_effect=httpx.ConnectError("still down"))
    assert cc.get_or_fetch(s, "simbad", "M42", probe, max_attempts=3) is None

    probe.assert_called_once()
    no_real_sleep.assert_not_called()
    s.execute.assert_not_called()
    # Marked again for a fresh cooldown, so the next miss skips the network.
    assert cc.outage("simbad") == "SIMBAD could not be reached"
    assert cc._OUTAGES["simbad"][0] == now[0] + cc.OUTAGE_COOLDOWN_SECONDS
    skipped = MagicMock()
    assert cc.get_or_fetch(s, "simbad", "M45", skipped) is None
    skipped.assert_not_called()


def test_failed_probe_with_marking_non_transient_error_raises_and_remarks(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(cc.time, "monotonic", lambda: now[0])
    s = _miss_session()
    cc.get_or_fetch(s, "simbad", "M31", _raiser(httpx.ConnectTimeout("slow")))
    now[0] += cc.OUTAGE_COOLDOWN_SECONDS

    with pytest.raises(cc.NonTransientError):
        cc.get_or_fetch(s, "simbad", "M42", _raiser(_status_error(404)))

    assert cc.outage("simbad") == "SIMBAD returned HTTP 404 (Not Found)"


def test_successful_probe_restores_full_retries(monkeypatch, no_real_sleep):
    now = [1000.0]
    monkeypatch.setattr(cc.time, "monotonic", lambda: now[0])
    s = _miss_session()
    cc.get_or_fetch(s, "simbad", "M31", _raiser(httpx.ConnectTimeout("slow")))
    now[0] += cc.OUTAGE_COOLDOWN_SECONDS

    probe = MagicMock(return_value={"ok": True})
    assert cc.get_or_fetch(s, "simbad", "M31", probe, max_attempts=3) == {"ok": True}
    probe.assert_called_once()
    assert "simbad" not in cc._OUTAGES

    # Back to normal: a later failure gets the full retry count and backoff.
    no_real_sleep.reset_mock()
    failing = MagicMock(side_effect=httpx.ConnectError("boom"))
    assert cc.get_or_fetch(s, "simbad", "M42", failing, max_attempts=3) is None
    assert failing.call_count == 3
    assert no_real_sleep.call_count == 2


@pytest.mark.parametrize("payload", [{"ok": True}, None])
def test_successful_fetch_clears_outage(payload, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(cc.time, "monotonic", lambda: now[0])
    s = _miss_session()
    cc.get_or_fetch(s, "simbad", "M31", _raiser(httpx.ConnectTimeout("slow")))
    assert cc.outage("simbad") is not None

    # Cooldown over: the next miss probes the network. Hold the clock still
    # afterwards so only a real clear (not expiry) can remove the marker.
    now[0] += cc.OUTAGE_COOLDOWN_SECONDS
    cc._OUTAGES["simbad"] = (now[0] + 10_000,) + cc._OUTAGES["simbad"][1:]
    monkeypatch.setattr(cc, "outage", lambda source: None)

    assert cc.get_or_fetch(s, "simbad", "M31", lambda: payload) == payload
    assert "simbad" not in cc._OUTAGES
    s.execute.assert_called_once()


def test_raise_if_outage_message_and_attributes():
    s = _miss_session()
    original = httpx.ConnectTimeout("slow")
    cc.get_or_fetch(s, "simbad", "M31", _raiser(original))

    cc.raise_if_outage("vizier", "gaia", key="M31")  # none marked: no raise

    with pytest.raises(cc.CatalogOutageError) as excinfo:
        cc.raise_if_outage("vizier", "simbad", key="M31")
    err = excinfo.value
    assert isinstance(err, cc.NonTransientError)
    assert str(err) == "SIMBAD lookup for 'M31' could not be completed: SIMBAD timed out"
    assert err.source == "simbad"
    assert err.key == "M31"
    assert err.original is original
    assert err.__cause__ is original

    with pytest.raises(cc.CatalogOutageError) as excinfo:
        cc.raise_if_outage("simbad")
    assert str(excinfo.value) == "SIMBAD lookup could not be completed: SIMBAD timed out"
    assert excinfo.value.key is None

    cc.clear_outages()
    cc.raise_if_outage("simbad", key="M31")


def test_cache_hit_still_served_while_marked():
    cc._mark_outage("simbad", httpx.ConnectTimeout("slow"))

    hit = MagicMock()
    hit.get.return_value = MagicMock(negative=False, payload={"main_id": "M31"})
    fetch = MagicMock()
    assert cc.get_or_fetch(hit, "simbad", "M31", fetch) == {"main_id": "M31"}

    negative = MagicMock()
    negative.get.return_value = MagicMock(negative=True, payload=None)
    assert cc.get_or_fetch(negative, "simbad", "nope", fetch) is None

    fetch.assert_not_called()
    assert cc.outage("simbad") is not None
