"""Tests for the generic catalog_cache client wrapper (app/services/catalog_cache.py).

Uses a real sync engine against the test DB (same _sync_session_factory
pattern as test_catalog_cache_migration.py / test_data_jobs.py) since the
upsert/negative/expiry behavior depends on real Postgres ON CONFLICT +
JSONB semantics.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

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


def test_retry_exhausted_stores_negative(session, no_real_sleep):
    attempts = []

    def fetch():
        attempts.append(1)
        raise httpx.ConnectError("always fails")

    result = cc.get_or_fetch(session, TEST_MARK, "k8", fetch, max_attempts=3)
    session.commit()

    assert result is None
    assert len(attempts) == 3
    assert cc.get_cached(session, TEST_MARK, "k8") == cc.NEGATIVE


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
