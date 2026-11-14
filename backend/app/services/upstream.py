"""Shared helpers for calling upstream catalog services (SIMBAD, VizieR, ...).

Two concerns live here so every service client handles them the same way:

- Mirror fallback: ``request_with_fallback`` tries a list of equivalent URLs
  in order and returns the first good response.
- Error wording: ``describe_http_error`` gives a short phrase a person can
  read (no URL, no traceback), while ``error_chain`` gives the raw exception
  chain for activity-event details and debugging.

Stdlib + httpx only. This module must not import from ``app`` so any service
can import it without a cycle.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import httpx

logger = logging.getLogger(__name__)

_SERVICE_LABELS = {
    "simbad": "SIMBAD",
    "sesame": "Sesame",
    "vizier": "VizieR",
    "hyperleda": "HyperLEDA",
    "gaia": "Gaia",
}


def service_label(source: str) -> str:
    """Display name for a catalog_cache source key; unknown keys pass through."""
    return _SERVICE_LABELS.get(source, source)


def describe_http_error(exc: BaseException) -> str:
    """Short human phrase for *exc*, with no URL and no traceback text."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        reason = exc.response.reason_phrase
        return f"returned HTTP {status} ({reason})" if reason else f"returned HTTP {status}"
    if isinstance(exc, httpx.TimeoutException):
        return "timed out"
    if isinstance(exc, httpx.ConnectError):
        return "could not be reached"
    name = type(exc).__name__
    if isinstance(exc, httpx.HTTPError):
        return f"failed ({name})"
    lines = str(exc).splitlines()
    first = lines[0][:120] if lines else ""
    return f"failed ({name}: {first})" if first else f"failed ({name})"


def _host(url: str) -> str:
    return httpx.URL(url).host or url


def _describe_attempts(attempts: list[tuple[str, BaseException]]) -> str:
    return "; ".join(f"{_host(url)} {describe_http_error(exc)}" for url, exc in attempts)


def _is_client_error(exc: BaseException) -> bool:
    """True for a 4xx other than 429: retrying the same request cannot help."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    status = exc.response.status_code
    return 400 <= status < 500 and status != 429


def request_with_fallback(
    client: httpx.Client,
    method: str,
    urls: Sequence[str],
    *,
    service: str,
    **kwargs: Any,
) -> httpx.Response:
    """Send the same request to each of *urls* in order; return the first good response.

    Calls the per-verb client method (``client.get``, ``client.post``) and
    ``raise_for_status()``. Any ``httpx.HTTPError`` moves on to the next url.

    If every url fails, raises an exception modelled on one of the failures
    (same class, and same request/response for a status error) so callers
    that classify by type or status code keep working. The template is the
    last transient failure if any attempt was transient (timeout, transport
    error, 5xx, 429); only when every attempt was a 4xx other than 429 is it
    the last of those, making the combined failure non-transient. The raised
    exception has a human readable message, an ``attempts`` attribute listing
    ``(url, original_exception)`` pairs, and the template as ``__cause__``.
    """
    if not urls:
        raise ValueError("request_with_fallback requires at least one url")
    send = getattr(client, method.lower())
    attempts: list[tuple[str, BaseException]] = []
    for url in urls:
        try:
            resp = send(url, **kwargs)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            attempts.append((url, exc))
            continue
        if attempts:
            logger.warning(
                "%s: %s; answered by %s",
                service_label(service), _describe_attempts(attempts), _host(url),
            )
        return resp

    # One mirror answering "client error" proves nothing while another is
    # down or overloaded, so the combined failure is non-transient only when
    # every attempt was. Otherwise the last transient failure is the template.
    transient = [exc for _, exc in attempts if not _is_client_error(exc)]
    template = transient[-1] if transient else attempts[-1][1]
    message = f"{service_label(service)} is unavailable: {_describe_attempts(attempts)}"
    error: httpx.HTTPError
    if isinstance(template, httpx.HTTPStatusError):
        error = httpx.HTTPStatusError(
            message, request=template.request, response=template.response,
        )
    else:
        try:
            error = type(template)(message)
        except Exception:  # noqa: BLE001
            error = httpx.TransportError(message)
        try:
            error.request = template.request
        except RuntimeError:
            # The original carried no request (raised outside a real send).
            pass
    error.attempts = attempts  # type: ignore[attr-defined]
    raise error from template


def error_chain(exc: BaseException, limit: int = 1000) -> str:
    """Raw debugging string: ``Type: message`` for *exc* and each ``__cause__``.

    Links are joined by `` <- ``, embedded newlines become `` | `` so the
    stored value is a single line, and the result is truncated to *limit*
    characters. Callers store this in activity-event details.
    """
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {_one_line(current)}")
        current = current.__cause__
    return " <- ".join(parts)[:limit]


def _first_line(exc: BaseException) -> str:
    lines = str(exc).strip().splitlines()
    return lines[0].strip() if lines else ""


def human_error(exc: BaseException) -> str:
    """One readable, single-line sentence fragment for *exc* (max 300 chars).

    Meant for text shown to a person. Use ``error_details`` for the raw
    debugging payload.
    """
    name = type(exc).__name__
    first = _first_line(exc)
    text = ""
    # catalog_cache.NonTransientError (matched structurally: importing it
    # here would create an import cycle) and request_with_fallback failures
    # already carry a human readable message.
    already_human = (
        name == "NonTransientError"
        or (hasattr(exc, "source") and hasattr(exc, "original"))
        or hasattr(exc, "attempts")
    )
    if already_human:
        text = first
    elif isinstance(exc, httpx.HTTPError):
        try:
            host = exc.request.url.host
        except Exception:  # noqa: BLE001
            # No request attached (raised outside a real send).
            host = ""
        text = f"{host or 'Remote service'} {describe_http_error(exc)}"
    elif isinstance(exc, OSError):
        if isinstance(exc, FileNotFoundError) and exc.filename is not None:
            text = f"File not found: {exc.filename}"
        elif isinstance(exc, PermissionError) and exc.filename is not None:
            text = f"Permission denied: {exc.filename}"
        else:
            text = exc.strerror or ""
    if not text:
        text = f"{name}: {first}" if first else name
    return text[:300]


def _one_line(exc: BaseException) -> str:
    return " | ".join(line.strip() for line in str(exc).splitlines() if line.strip())


def error_details(exc: BaseException) -> dict[str, Any]:
    """Raw debugging payload for an activity event's ``details``.

    When *exc* or anything in its ``__cause__`` chain came from
    ``request_with_fallback``, an ``attempts`` list holds the raw error of
    every mirror tried (not only the last one, which is all ``__cause__``
    keeps). JSON-serializable: values are ``str`` or ``list[str]``.
    """
    details: dict[str, Any] = {
        "exception_type": type(exc).__name__,
        "exception": str(exc)[:500],
        "error_chain": error_chain(exc),
    }
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        attempts = getattr(current, "attempts", None)
        if attempts:
            details["attempts"] = [
                f"{url} -> {type(original).__name__}: {_one_line(original)}"[:300]
                for url, original in list(attempts)[:10]
            ]
            break
        current = current.__cause__
    return details
