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
plain synchronous DB+HTTP context. simbad.py's query core
(``_query_simbad``/``_query_simbad_raw``/``resolve_target_name``) is plain
synchronous ``httpx.Client`` code, same as every other source here -- no
thread-local event loop remains anywhere in the codebase. simbad.py's
``resolve_target_name_cached`` is ported onto ``get_or_fetch`` like every
other source (it retains its own dual-key original/mapped-name cache-check
step before the leaf fetch, since ``get_or_fetch`` only tracks a single
(source, key) pair and SIMBAD, unlike every other source here, may need to
resolve either of two distinct cache keys for one lookup). No async surface
is provided by this module.

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
from app.services.upstream import describe_http_error, service_label

logger = logging.getLogger(__name__)

# Sentinel returned by get_cached() to mean "cached negative result", distinct
# from both a positive payload (dict) and a cache miss (None).
NEGATIVE: Literal["_negative"] = "_negative"

# Private sentinel returned by _fetch_with_retry when every attempt failed
# transiently (an upstream outage), as opposed to fetch() returning None
# ("queried fine, no result"). get_or_fetch writes no cache row for it.
_FETCH_FAILED = object()

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

    ``str()`` of the error is a human readable sentence naming the service
    and the lookup key. ``source`` and ``key`` identify the lookup, and
    ``original`` is the underlying exception (also set as ``__cause__``) for
    callers that want the raw detail, e.g. via ``upstream.error_chain``.
    """

    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        key: str | None = None,
        original: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.source = source
        self.key = key
        self.original = original


class CatalogOutageError(NonTransientError):
    """Raised by raise_if_outage when a source is currently marked as down.

    Lets a caller that got None from get_or_fetch tell "the service is
    unavailable" apart from "no such object".
    """


def _human_reason(source: str, exc: BaseException) -> str:
    """Human text for a failed fetch against *source*."""
    if hasattr(exc, "attempts"):
        # Raised by upstream.request_with_fallback: already a human sentence.
        lines = str(exc).splitlines()
        if lines:
            return lines[0]
    return f"{service_label(source)} {describe_http_error(exc)}"


def _non_transient(source: str, key: str, exc: BaseException) -> NonTransientError:
    """Build the NonTransientError for a failed (source, key) fetch."""
    return NonTransientError(
        f"{service_label(source)} lookup for '{key}' failed: {_human_reason(source, exc)}",
        source=source, key=key, original=exc,
    )


# --- Outage marker / circuit breaker -------------------------------------
# How long a source stays marked after a failed fetch. While marked,
# get_or_fetch skips the network on a cache miss instead of repeating the
# whole retry chain for every key. Once the cooldown is over the next cache
# miss is a single-attempt probe (no retries, no backoff). Worst case for a
# timeout-style outage: one probe across two mirrors at 15 s each is about
# 30 s of waiting per 300 s cooldown, i.e. roughly 30 s in every 330 s per
# source per process.
OUTAGE_COOLDOWN_SECONDS = 300

# source -> (time.monotonic() deadline, human reason, original exception).
# An entry past its deadline is kept as "suspect": outage() no longer reports
# it, but it makes the next fetch a probe. Only a successful fetch or
# clear_outages() removes an entry.
# ponytail: per-process state, each worker process learns about an outage
# separately (one failed retry chain per process per cooldown); move the
# marker to Redis if that matters.
_OUTAGES: dict[str, tuple[float, str, BaseException]] = {}


# Non-transient statuses that say "this particular request was rejected"
# (bad request, payload too large, URI too long, unprocessable) rather than
# "the service is down". One malformed key must not mark a whole source as
# down, so these never set the outage marker. Every other non-transient
# status (401, 403, 404, 410, ...) does: each catalog client calls a fixed
# query endpoint with the object in the parameters, so those mean the
# endpoint itself is missing or blocked, which is what a CDS outage page
# (404 on every path) looks like.
_REQUEST_SPECIFIC_STATUS = frozenset({400, 413, 414, 422})


def _is_request_specific(exc: BaseException) -> bool:
    """True if *exc* is about this one request, not the health of the service.

    For a failure from upstream.request_with_fallback (carries ``attempts``)
    every mirror's answer must be request-specific.
    """
    attempts = getattr(exc, "attempts", None)
    originals = [original for _, original in attempts] if attempts else [exc]
    return all(
        isinstance(original, httpx.HTTPStatusError)
        and original.response.status_code in _REQUEST_SPECIFIC_STATUS
        for original in originals
    )


def _mark_outage(source: str, exc: BaseException) -> None:
    _OUTAGES[source] = (
        time.monotonic() + OUTAGE_COOLDOWN_SECONDS, _human_reason(source, exc), exc,
    )


def _current_outage(source: str) -> tuple[float, str, BaseException] | None:
    entry = _OUTAGES.get(source)
    if entry is None or time.monotonic() >= entry[0]:
        # Expired entries stay in the dict as "suspect" (see _OUTAGES).
        return None
    return entry


def outage(source: str) -> str | None:
    """Human reason *source* is currently marked as down, or None.

    A source is marked for OUTAGE_COOLDOWN_SECONDS when a fetch exhausts its
    transient retries or fails non-transiently for a reason that is not
    specific to that one request, and unmarked by the next successful fetch.
    Returns None once the cooldown is over, even before a fetch has proven
    the service is back, so callers do not report an outage that may have
    ended.
    """
    entry = _current_outage(source)
    return entry[1] if entry else None


def raise_if_outage(*sources: str, key: str | None = None) -> None:
    """Raise CatalogOutageError for the first of *sources* marked as down.

    Call after a lookup came back empty to turn "None because the service is
    unavailable" into an error instead of reporting "not found".
    """
    for source in sources:
        entry = _current_outage(source)
        if entry is None:
            continue
        _, reason, original = entry
        subject = f"lookup for '{key}'" if key is not None else "lookup"
        raise CatalogOutageError(
            f"{service_label(source)} {subject} could not be completed: {reason}",
            source=source, key=key, original=original,
        ) from original


def clear_outages() -> None:
    """Forget every outage marker (tests, or an explicit "retry now")."""
    _OUTAGES.clear()


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
) -> dict[str, Any] | object | None:
    """Call fetch() up to max_attempts times, retrying transient failures.

    Returns the payload (or None for "queried, genuinely no result") on
    success. If every attempt raises a transient exception, returns the
    private ``_FETCH_FAILED`` sentinel: the upstream service is unreachable,
    which says nothing about whether the object exists, so the caller must
    not cache anything. A non-transient
    exception (an httpx.HTTPStatusError with a 4xx status other than 429)
    aborts immediately -- no further attempts, nothing cached -- by raising
    NonTransientError from the original exception, with a human readable
    message and the source, key and original exception attached.

    Exhausted transient retries always mark *source* as down (see
    ``outage``). A non-transient failure marks it too, unless the failure is
    request-specific (see ``_REQUEST_SPECIFIC_STATUS``). A successful fetch
    clears the mark.
    """
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            payload = fetch()
            _OUTAGES.pop(source, None)
            return payload
        except retry_on as exc:
            last_exc = exc
            if not _is_transient(exc):
                logger.warning(
                    "%s/%s: non-transient fetch failure, not retrying: %s", source, key, exc,
                )
                if not _is_request_specific(exc):
                    _mark_outage(source, exc)
                raise _non_transient(source, key, exc) from exc
            remaining = max_attempts - attempt - 1
            if remaining <= 0:
                logger.warning(
                    "%s/%s: fetch failed after %d attempt(s), giving up, result not cached: "
                    "%s %s (%s)",
                    source, key, max_attempts,
                    service_label(source), describe_http_error(exc), exc,
                )
                _mark_outage(source, exc)
                return _FETCH_FAILED
            delay = backoff_base_seconds * (2 ** attempt)
            logger.warning(
                "%s/%s: fetch attempt %d/%d failed (%s), retrying in %.1fs",
                source, key, attempt + 1, max_attempts, exc, delay,
            )
            time.sleep(delay)
    # Unreachable in practice (loop always returns or raises), but keeps
    # type-checkers happy and guards against max_attempts <= 0.
    if last_exc is not None:
        _mark_outage(source, last_exc)
        raise _non_transient(source, key, last_exc) from last_exc
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
      negative row if fetch() returned None), and returns it.
    - Every attempt failed transiently (upstream outage): returns None,
      writes NO cache row, and marks *source* as down for
      OUTAGE_COOLDOWN_SECONDS.
    - Cache miss while *source* is marked as down: returns None at once, with
      no fetch() call, no sleep and no cache row. Cache hits are still served.
      Callers that must tell this None from "no such object" call
      ``raise_if_outage(source, key=key)`` or check ``outage(source)``.
    - Cache miss after the cooldown, before any success: the fetch is a probe
      with a single attempt (no retries, no sleeps) whatever *max_attempts*
      says. Failure marks the source again; success restores normal behavior.

    fetch() must return a payload dict on success, or None to mean "queried
    successfully, no data found" (stored as a negative row). It should raise
    on network/HTTP failure rather than swallowing errors internally --
    that's what lets this wrapper distinguish "transient, worth retrying"
    from "definitively no result" from "non-transient client error, don't
    retry and don't cache" (see NonTransientError).

    A non-transient failure (NonTransientError) propagates to the caller
    uncaught -- nothing is cached, since it likely indicates a bug or a bad
    request rather than "this object doesn't exist." Unless the status says
    only this request was rejected (400, 413, 414, 422), it also marks
    *source* as down, so later cache misses within the cooldown return None.
    """
    cached = get_cached(session, source, key, positive_ttl=positive_ttl, negative_ttl=negative_ttl)
    if cached is NEGATIVE:
        return None
    if cached is not None:
        return cached

    reason = outage(source)
    if reason is not None:
        logger.debug("%s/%s: skipping fetch, source marked as down: %s", source, key, reason)
        return None
    if source in _OUTAGES:
        # Cooldown over but no success since: probe with a single attempt so
        # a continuing outage costs one request, not a full retry chain.
        max_attempts = 1

    payload = _fetch_with_retry(
        fetch,
        max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds,
        retry_on=retry_on,
        source=source,
        key=key,
    )
    if payload is _FETCH_FAILED:
        return None
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
