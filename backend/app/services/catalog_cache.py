"""Generic sync client wrapper around the ``catalog_cache`` table.

Provides get-or-fetch semantics (lookup, on miss fetch-with-retry, store,
return) on top of the single (source, key) point-lookup table defined in
``app/models/catalog_cache.py``. This replaces five near-identical per-source
cache tables (simbad_cache, sesame_cache, vizier_cache, hyperleda_cache,
gaia_cache) and each service's own ad hoc single-attempt HTTP call + manual
NULL-sentinel negative row. The five services are ported onto this wrapper
one at a time in a later task; this module only provides the shared surface
they import.

Sync only. Every current/target caller (Celery tasks, data_migrations.py's
batch backfill, filename_resolver.py/target_resolver.py, and api/merges.py's
FastAPI routes -- which already open their own sync ``Session`` against
``sync_engine`` before calling sync service functions, a pre-existing
blocking-the-loop pattern that is out of scope to fix here) operates in a
plain synchronous DB+HTTP context. simbad.py's genuinely async core
(``_query_simbad``/``resolve_target_name``) has no external caller that
needs caching -- it stays internal to simbad.py and is invoked from that
module's own sync wrapper via its existing thread-local-event-loop
``_run_async`` helper, exactly as today. No async surface is provided here;
if one is ever needed, mirror that same pattern rather than inventing a
second concurrency model.

New behavior introduced by this wrapper (see docs/retrofit-roadmap.md Phase 4
and the coordinator's task-2 brief for full rationale -- none of this existed
in the five services being replaced):

- Retry with exponential backoff on transient failures during ``fetch()``.
- Optional TTL/expiry for positive and negative cache rows (default: never
  expire, matching today's "cache forever" behavior exactly).

Preserved behavior:

- A cache hit (positive or negative) returns immediately with no HTTP call.
- A positive cached row is treated as authoritative.
- A negative cached row suppresses re-fetching indefinitely by default.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.catalog_cache import CatalogCache

logger = logging.getLogger(__name__)

# Sentinel returned by get_cached() to mean "cached negative result", distinct
# from both a positive payload (dict) and a cache miss (None).
NEGATIVE: Literal["_negative"] = "_negative"

# --- Defaults ----------------------------------------------------------
# Retry: 3 total fetch() attempts, sleeping backoff_base_seconds * 2**n
# between attempts (n = 0, 1, ... for the 2nd, 3rd, ... attempt). With the
# defaults below that is a 1s sleep before attempt 2 and a 2s sleep before
# attempt 3 -- i.e. only the first two entries of the "1s/2s/4s" backoff
# curve the coordinator specified are ever reached at max_attempts=3, since
# a 3rd sleep only happens before a 4th attempt. If a 4s sleep should also
# occur, bump max_attempts to 4 (flagged explicitly in this task's report).
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE_SECONDS = 1.0

# Expiry: off by default for both positive and negative rows, preserving
# today's "cache forever until manually deleted" behavior exactly. Per-source
# callers may opt into a TTL by passing positive_ttl/negative_ttl.
DEFAULT_POSITIVE_TTL: timedelta | None = None
DEFAULT_NEGATIVE_TTL: timedelta | None = None

# HTTP status codes considered non-transient (a retry cannot help): all 4xx
# except 429 (rate limit, which IS worth retrying with backoff).
_NON_TRANSIENT_STATUS = set(range(400, 500)) - {429}


class NonTransientError(Exception):
    """Raised by get_or_fetch when a fetch() failure should not be retried.

    fetch callables do not need to raise this directly -- get_or_fetch
    recognizes a non-transient failure automatically when the caught
    exception is an ``httpx.HTTPStatusError`` whose response status is a 4xx
    other than 429, wraps it in a NonTransientError, and re-raises it
    immediately without consuming a retry attempt or writing a cache row.
    """


def _is_transient(exc: BaseException) -> bool:
    """True if *exc* looks like a transient failure worth retrying."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code not in _NON_TRANSIENT_STATUS
    return True


def _row_expired(fetched_at: datetime, ttl: timedelta | None) -> bool:
    if ttl is None:
        return False
    now = datetime.now(timezone.utc)
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return fetched_at + ttl < now


def get_cached(
    session: Session,
    source: str,
    key: str,
    *,
    positive_ttl: timedelta | None = None,
    negative_ttl: timedelta | None = None,
) -> dict[str, Any] | Literal["_negative"] | None:
    """Look up (source, key) without ever calling out to the network.

    Returns:
    - the stored payload dict, if a fresh positive row exists;
    - ``NEGATIVE`` (the string ``"_negative"``), if a fresh negative row exists;
    - ``None``, if there is no row, or the row is stale per the given TTL.

    Lets callers that need to separate "check cache" from "query and cache"
    (so the HTTP call happens outside an open transaction) do so explicitly,
    mirroring each service's existing ``get_cached_X`` helpers.
    """
    row = session.get(CatalogCache, (source, key))
    if row is None:
        return None
    ttl = negative_ttl if row.negative else positive_ttl
    if _row_expired(row.fetched_at, ttl):
        return None
    if row.negative:
        return NEGATIVE
    return row.payload


def save_cached(session: Session, source: str, key: str, payload: dict[str, Any] | None) -> None:
    """Upsert a cache row: *payload* is the positive result, or None for a negative row.

    Does not commit -- callers own the transaction, matching every existing
    ``save_X_cache`` helper.
    """
    values = {
        "source": source,
        "key": key,
        "payload": payload,
        "negative": payload is None,
    }
    stmt = pg_insert(CatalogCache).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "key"],
        set_={"payload": stmt.excluded.payload, "negative": stmt.excluded.negative, "fetched_at": func.now()},
    )
    session.execute(stmt)


def _fetch_with_retry(
    fetch: Callable[[], dict[str, Any] | None],
    *,
    max_attempts: int,
    backoff_base_seconds: float,
    retry_on: tuple[type[BaseException], ...],
    source: str,
    key: str,
) -> dict[str, Any] | None:
    """Call fetch() up to max_attempts times, retrying transient failures.

    Returns the payload (or None for "queried, genuinely no result") on
    success. If every attempt raises a transient exception, returns None
    (treated as a failed lookup -> caller stores a negative row, same as
    today's "any failure means negative-cache it" behavior). A non-transient
    exception (an httpx.HTTPStatusError with a 4xx status other than 429)
    aborts immediately -- no further attempts, nothing cached -- by raising
    NonTransientError from the original exception.
    """
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return fetch()
        except retry_on as exc:
            last_exc = exc
            if not _is_transient(exc):
                logger.warning(
                    "%s/%s: non-transient fetch failure, not retrying: %s", source, key, exc,
                )
                raise NonTransientError(str(exc)) from exc
            remaining = max_attempts - attempt - 1
            if remaining <= 0:
                logger.warning(
                    "%s/%s: fetch failed after %d attempt(s), giving up: %s",
                    source, key, max_attempts, exc,
                )
                return None
            delay = backoff_base_seconds * (2 ** attempt)
            logger.warning(
                "%s/%s: fetch attempt %d/%d failed (%s), retrying in %.1fs",
                source, key, attempt + 1, max_attempts, exc, delay,
            )
            time.sleep(delay)
    # Unreachable in practice (loop always returns or raises), but keeps
    # type-checkers happy and guards against max_attempts <= 0.
    if last_exc is not None:
        raise NonTransientError(str(last_exc)) from last_exc
    return None


def get_or_fetch(
    session: Session,
    source: str,
    key: str,
    fetch: Callable[[], dict[str, Any] | None],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    positive_ttl: timedelta | None = DEFAULT_POSITIVE_TTL,
    negative_ttl: timedelta | None = DEFAULT_NEGATIVE_TTL,
    retry_on: tuple[type[BaseException], ...] = (httpx.HTTPError,),
) -> dict[str, Any] | None:
    """Look up (source, key); on miss/expiry, fetch (with retry+backoff), store, return.

    - Cache hit (fresh positive row): returns the payload dict, no fetch() call.
    - Cache hit (fresh negative row): returns None, no fetch() call.
    - Cache miss or expired row: calls fetch() with retry/backoff (see
      _fetch_with_retry), stores the result (positive payload dict, or a
      negative row if fetch() returned None or every attempt transiently
      failed), and returns it.

    fetch() must return a payload dict on success, or None to mean "queried
    successfully, no data found" (stored as a negative row). It should raise
    on network/HTTP failure rather than swallowing errors internally --
    that's what lets this wrapper distinguish "transient, worth retrying"
    from "definitively no result" from "non-transient client error, don't
    retry and don't cache" (see NonTransientError).

    A non-transient failure (NonTransientError) propagates to the caller
    uncaught -- nothing is cached, since it likely indicates a bug or a bad
    request rather than "this object doesn't exist."
    """
    cached = get_cached(session, source, key, positive_ttl=positive_ttl, negative_ttl=negative_ttl)
    if cached is NEGATIVE:
        return None
    if cached is not None:
        return cached

    payload = _fetch_with_retry(
        fetch,
        max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds,
        retry_on=retry_on,
        source=source,
        key=key,
    )
    save_cached(session, source, key, payload)
    return payload


def clear_negative(session: Session, source: str, key: str | None = None) -> int:
    """Delete negative-cached row(s) for *source* (and *key*, if given).

    Equivalent of today's manual "clear negative cache to retry" affordance
    (e.g. ``DELETE FROM simbad_cache WHERE main_id IS NULL``). Returns the
    number of rows deleted. Does not commit -- callers own the transaction.
    """
    stmt = CatalogCache.__table__.delete().where(
        CatalogCache.source == source, CatalogCache.negative.is_(True),
    )
    if key is not None:
        stmt = stmt.where(CatalogCache.key == key)
    result = session.execute(stmt)
    return result.rowcount


def invalidate(session: Session, source: str, key: str | None = None) -> int:
    """Delete cached row(s) for *source* (and *key*, if given), positive or negative.

    Equivalent of today's unconditional "wipe this source's cache" affordance
    (e.g. ``DELETE FROM sesame_cache``, which deletes every row regardless of
    the negative flag). Returns the number of rows deleted. Does not commit
    -- callers own the transaction.
    """
    stmt = CatalogCache.__table__.delete().where(CatalogCache.source == source)
    if key is not None:
        stmt = stmt.where(CatalogCache.key == key)
    result = session.execute(stmt)
    return result.rowcount
