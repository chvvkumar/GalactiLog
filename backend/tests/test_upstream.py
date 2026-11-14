"""Unit tests for app/services/upstream.py. No database, no network."""
import logging
from unittest.mock import MagicMock

import httpx
import pytest

from app.services import upstream

PRIMARY = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"
MIRROR = "https://simbad.harvard.edu/simbad/sim-tap/sync"


def _response(status: int, url: str, method: str = "GET") -> httpx.Response:
    return httpx.Response(status, request=httpx.Request(method, url))


def _status_error(status: int, url: str = PRIMARY) -> httpx.HTTPStatusError:
    resp = _response(status, url)
    return httpx.HTTPStatusError("raw text", request=resp.request, response=resp)


# ---------------------------------------------------------------------------
# service_label
# ---------------------------------------------------------------------------

def test_service_label_known_and_unknown():
    assert upstream.service_label("simbad") == "SIMBAD"
    assert upstream.service_label("sesame") == "Sesame"
    assert upstream.service_label("vizier") == "VizieR"
    assert upstream.service_label("hyperleda") == "HyperLEDA"
    assert upstream.service_label("gaia") == "Gaia"
    assert upstream.service_label("something_else") == "something_else"


# ---------------------------------------------------------------------------
# describe_http_error
# ---------------------------------------------------------------------------

def test_describe_status_error():
    text = upstream.describe_http_error(_status_error(404))
    assert text == "returned HTTP 404 (Not Found)"
    assert "simbad" not in text


def test_describe_timeout_subclasses():
    assert upstream.describe_http_error(httpx.ReadTimeout("slow")) == "timed out"
    assert upstream.describe_http_error(httpx.ConnectTimeout("slow")) == "timed out"


def test_describe_connect_error():
    assert upstream.describe_http_error(httpx.ConnectError("dns")) == "could not be reached"


def test_describe_other_httpx_error():
    assert upstream.describe_http_error(httpx.ReadError("reset")) == "failed (ReadError)"


def test_describe_non_httpx_error_uses_first_line_capped():
    text = upstream.describe_http_error(ValueError("first line\nsecond line"))
    assert text == "failed (ValueError: first line)"

    long_text = upstream.describe_http_error(ValueError("x" * 500))
    assert long_text == f"failed (ValueError: {'x' * 120})"


# ---------------------------------------------------------------------------
# request_with_fallback
# ---------------------------------------------------------------------------

def test_first_url_ok(caplog):
    client = MagicMock()
    ok = _response(200, PRIMARY)
    client.get.return_value = ok

    with caplog.at_level(logging.WARNING, logger=upstream.logger.name):
        resp = upstream.request_with_fallback(
            client, "GET", [PRIMARY, MIRROR], service="simbad", params={"q": 1},
        )

    assert resp is ok
    client.get.assert_called_once_with(PRIMARY, params={"q": 1})
    client.request.assert_not_called()
    assert caplog.records == []


def test_first_fails_second_ok_in_order_and_warns(caplog):
    client = MagicMock()
    ok = _response(200, MIRROR, "POST")
    client.post.side_effect = [_response(404, PRIMARY, "POST"), ok]

    with caplog.at_level(logging.WARNING, logger=upstream.logger.name):
        resp = upstream.request_with_fallback(
            client, "post", [PRIMARY, MIRROR], service="simbad", data={"a": "b"},
        )

    assert resp is ok
    assert [c.args[0] for c in client.post.call_args_list] == [PRIMARY, MIRROR]
    assert all(c.kwargs == {"data": {"a": "b"}} for c in client.post.call_args_list)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "simbad.cds.unistra.fr returned HTTP 404 (Not Found)" in message
    assert "simbad.harvard.edu" in message
    assert "sim-tap" not in message


def test_transport_failure_falls_through_to_mirror():
    client = MagicMock()
    ok = _response(200, MIRROR)
    client.get.side_effect = [httpx.ConnectError("dns"), ok]

    assert upstream.request_with_fallback(client, "GET", [PRIMARY, MIRROR], service="simbad") is ok


def test_all_fail_all_client_errors_is_non_transient():
    client = MagicMock()
    client.get.side_effect = [_response(404, PRIMARY), _response(404, MIRROR)]

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        upstream.request_with_fallback(client, "GET", [PRIMARY, MIRROR], service="simbad")

    err = excinfo.value
    assert str(err) == (
        "SIMBAD is unavailable: simbad.cds.unistra.fr returned HTTP 404 (Not Found); "
        "simbad.harvard.edu returned HTTP 404 (Not Found)"
    )
    assert err.response.status_code == 404
    assert len(err.attempts) == 2
    assert [url for url, _ in err.attempts] == [PRIMARY, MIRROR]
    assert all(isinstance(exc, httpx.HTTPStatusError) for _, exc in err.attempts)
    assert err.__cause__ is err.attempts[-1][1]


def test_server_error_then_client_error_is_transient():
    """A 503 from one mirror outweighs a 404 from the other: worth retrying."""
    client = MagicMock()
    client.get.side_effect = [_response(503, PRIMARY), _response(404, MIRROR)]

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        upstream.request_with_fallback(client, "GET", [PRIMARY, MIRROR], service="simbad")

    err = excinfo.value
    assert err.response.status_code == 503
    assert str(err) == (
        "SIMBAD is unavailable: simbad.cds.unistra.fr returned HTTP 503 (Service Unavailable); "
        "simbad.harvard.edu returned HTTP 404 (Not Found)"
    )
    assert len(err.attempts) == 2
    assert err.__cause__ is err.attempts[0][1]


def test_client_error_then_timeout_is_transient():
    client = MagicMock()
    last = httpx.ReadTimeout("slow")
    client.get.side_effect = [_response(404, PRIMARY), last]

    with pytest.raises(httpx.ReadTimeout) as excinfo:
        upstream.request_with_fallback(client, "GET", [PRIMARY, MIRROR], service="simbad")

    err = excinfo.value
    assert not isinstance(err, httpx.HTTPStatusError)
    assert str(err) == (
        "SIMBAD is unavailable: simbad.cds.unistra.fr returned HTTP 404 (Not Found); "
        "simbad.harvard.edu timed out"
    )
    assert len(err.attempts) == 2
    assert err.__cause__ is last


def test_rate_limit_counts_as_transient():
    client = MagicMock()
    client.get.side_effect = [_response(429, PRIMARY), _response(404, MIRROR)]

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        upstream.request_with_fallback(client, "GET", [PRIMARY, MIRROR], service="simbad")

    assert excinfo.value.response.status_code == 429


def test_all_fail_with_timeout():
    client = MagicMock()
    last = httpx.ReadTimeout("slow")
    client.get.side_effect = [httpx.ConnectTimeout("slow"), last]

    with pytest.raises(httpx.HTTPError) as excinfo:
        upstream.request_with_fallback(client, "GET", [PRIMARY, MIRROR], service="vizier")

    err = excinfo.value
    assert isinstance(err, (httpx.TimeoutException, httpx.TransportError))
    assert type(err) is httpx.ReadTimeout
    assert str(err) == (
        "VizieR is unavailable: simbad.cds.unistra.fr timed out; simbad.harvard.edu timed out"
    )
    assert len(err.attempts) == 2
    assert err.__cause__ is last


def test_single_url_failure_is_still_human_readable():
    client = MagicMock()
    client.get.return_value = _response(404, PRIMARY)

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        upstream.request_with_fallback(client, "GET", [PRIMARY], service="simbad")

    err = excinfo.value
    assert str(err) == "SIMBAD is unavailable: simbad.cds.unistra.fr returned HTTP 404 (Not Found)"
    assert err.response.status_code == 404
    assert len(err.attempts) == 1


def test_non_httpx_error_is_not_swallowed():
    client = MagicMock()
    client.get.side_effect = ValueError("bug")

    with pytest.raises(ValueError):
        upstream.request_with_fallback(client, "GET", [PRIMARY, MIRROR], service="simbad")
    assert client.get.call_count == 1


# ---------------------------------------------------------------------------
# error_chain
# ---------------------------------------------------------------------------

def test_error_chain_follows_cause():
    try:
        try:
            raise ValueError("inner")
        except ValueError as inner:
            raise RuntimeError("outer") from inner
    except RuntimeError as exc:
        chain = upstream.error_chain(exc)

    assert chain == "RuntimeError: outer <- ValueError: inner"


def test_error_chain_single_and_truncated():
    assert upstream.error_chain(KeyError("k")) == "KeyError: 'k'"
    assert len(upstream.error_chain(ValueError("x" * 5000), limit=50)) == 50


def test_error_chain_keeps_raw_detail_of_fallback_failure():
    client = MagicMock()
    client.get.return_value = _response(404, PRIMARY)

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        upstream.request_with_fallback(client, "GET", [PRIMARY], service="simbad")

    chain = upstream.error_chain(excinfo.value)
    assert chain.startswith("HTTPStatusError: SIMBAD is unavailable")
    # The original httpx message, including the URL, stays available for debugging.
    assert " <- HTTPStatusError: " in chain
    assert PRIMARY in chain


def test_error_chain_collapses_newlines():
    chain = upstream.error_chain(ValueError("first\nsecond\n"))
    assert chain == "ValueError: first | second"


# ---------------------------------------------------------------------------
# human_error
# ---------------------------------------------------------------------------

class NonTransientError(Exception):
    """Stand-in with the same class name as catalog_cache.NonTransientError."""


def test_human_error_non_transient_uses_its_message():
    exc = NonTransientError("SIMBAD lookup for 'M31' failed: SIMBAD timed out\nextra")
    assert upstream.human_error(exc) == "SIMBAD lookup for 'M31' failed: SIMBAD timed out"


def test_human_error_detects_source_and_original_attributes():
    exc = RuntimeError("Gaia lookup for 'x' failed: Gaia timed out")
    exc.source = "gaia"
    exc.original = None
    assert upstream.human_error(exc) == "Gaia lookup for 'x' failed: Gaia timed out"


def test_human_error_fallback_failure_uses_its_message():
    client = MagicMock()
    client.get.return_value = _response(404, PRIMARY)
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        upstream.request_with_fallback(client, "GET", [PRIMARY], service="simbad")

    assert upstream.human_error(excinfo.value) == (
        "SIMBAD is unavailable: simbad.cds.unistra.fr returned HTTP 404 (Not Found)"
    )


def test_human_error_httpx_with_and_without_request():
    text = upstream.human_error(_status_error(404))
    assert text == "simbad.cds.unistra.fr returned HTTP 404 (Not Found)"

    timeout = httpx.ReadTimeout("slow", request=httpx.Request("GET", MIRROR))
    assert upstream.human_error(timeout) == "simbad.harvard.edu timed out"

    assert upstream.human_error(httpx.ConnectError("dns")) == "Remote service could not be reached"


def test_human_error_os_errors():
    missing = FileNotFoundError(2, "No such file or directory", "/data/a.fits")
    assert upstream.human_error(missing) == "File not found: /data/a.fits"

    denied = PermissionError(13, "Permission denied", "/data/b.fits")
    assert upstream.human_error(denied) == "Permission denied: /data/b.fits"

    assert upstream.human_error(OSError(28, "No space left on device")) == "No space left on device"
    assert upstream.human_error(OSError("plain text")) == "OSError: plain text"


def test_human_error_generic_single_line_and_capped():
    assert upstream.human_error(ValueError("bad value\nTraceback ...")) == "ValueError: bad value"
    assert upstream.human_error(KeyError()) == "KeyError"

    long_text = upstream.human_error(ValueError("x" * 1000))
    assert len(long_text) == 300
    assert "\n" not in long_text


# ---------------------------------------------------------------------------
# error_details
# ---------------------------------------------------------------------------

def test_error_details_payload():
    try:
        try:
            raise ValueError("inner")
        except ValueError as inner:
            raise RuntimeError("y" * 600) from inner
    except RuntimeError as exc:
        details = upstream.error_details(exc)

    assert set(details) == {"exception_type", "exception", "error_chain"}
    assert details["exception_type"] == "RuntimeError"
    assert details["exception"] == "y" * 500
    assert details["error_chain"].startswith("RuntimeError: yyy")
    assert details["error_chain"].endswith(" <- ValueError: inner")


def test_error_details_omits_attempts_when_there_are_none():
    assert "attempts" not in upstream.error_details(ValueError("plain"))


def test_error_details_keeps_raw_error_of_every_mirror_attempt():
    import json

    client = MagicMock()
    client.get.side_effect = [
        _response(404, PRIMARY),
        httpx.ReadTimeout("read operation timed out"),
    ]
    with pytest.raises(httpx.ReadTimeout) as excinfo:
        upstream.request_with_fallback(client, "GET", [PRIMARY, MIRROR], service="simbad")

    # Shaped like catalog_cache.NonTransientError wrapping the fallback failure.
    wrapper = NonTransientError("SIMBAD lookup for 'M31' failed: SIMBAD is unavailable")
    wrapper.__cause__ = excinfo.value

    details = upstream.error_details(wrapper)

    assert details["exception_type"] == "NonTransientError"
    assert len(details["attempts"]) == 2
    first, second = details["attempts"]
    assert first.startswith(f"{PRIMARY} -> HTTPStatusError: Client error '404 Not Found'")
    assert second == f"{MIRROR} -> ReadTimeout: read operation timed out"
    assert all("\n" not in line and len(line) <= 300 for line in details["attempts"])
    json.dumps(details)


def test_error_details_caps_attempt_count():
    exc = RuntimeError("all failed")
    exc.attempts = [(f"https://m{i}.test/x", ValueError("x" * 1000)) for i in range(15)]

    attempts = upstream.error_details(exc)["attempts"]
    assert len(attempts) == 10
    assert all(len(line) == 300 for line in attempts)
