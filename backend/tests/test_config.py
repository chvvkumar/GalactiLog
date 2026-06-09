from unittest.mock import MagicMock

from app.config import Settings, client_ip_from_request, load_or_create_jwt_secret


def test_settings_defaults():
    s = Settings()
    assert "postgresql" in s.database_url
    assert "redis" in s.redis_url
    assert s.thumbnail_max_width == 800


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("GALACTILOG_THUMBNAIL_MAX_WIDTH", "400")
    s = Settings()
    assert s.thumbnail_max_width == 400


# ---------------------------------------------------------------------------
# SEC-5: real client IP extraction (rate limiter / lockout key_func)
# ---------------------------------------------------------------------------

def _req(headers=None, client_host="127.0.0.1"):
    request = MagicMock()
    request.headers = headers or {}
    if client_host is None:
        request.client = None
    else:
        request.client = MagicMock()
        request.client.host = client_host
    return request


def test_client_ip_uses_forwarded_for():
    req = _req(headers={"x-forwarded-for": "203.0.113.7"})
    assert client_ip_from_request(req) == "203.0.113.7"


def test_client_ip_takes_leftmost_of_chain():
    # nginx appends: original-client, proxy1, proxy2
    req = _req(headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1, 127.0.0.1"})
    assert client_ip_from_request(req) == "203.0.113.7"


def test_client_ip_skips_leading_empty_entries():
    req = _req(headers={"x-forwarded-for": " , 203.0.113.7"})
    assert client_ip_from_request(req) == "203.0.113.7"


def test_client_ip_falls_back_to_socket_peer():
    req = _req(headers={}, client_host="198.51.100.4")
    assert client_ip_from_request(req) == "198.51.100.4"


def test_client_ip_unknown_when_no_client():
    req = _req(headers={}, client_host=None)
    assert client_ip_from_request(req) == "unknown"


# ---------------------------------------------------------------------------
# SEC-7: persisted JWT secret
# ---------------------------------------------------------------------------

def test_jwt_secret_generated_and_persisted(tmp_path):
    secret_file = tmp_path / "subdir" / ".jwt_secret"
    assert not secret_file.exists()

    secret = load_or_create_jwt_secret(str(secret_file))

    assert secret
    assert secret_file.exists()
    assert secret_file.read_text(encoding="utf-8").strip() == secret


def test_jwt_secret_loaded_when_file_exists(tmp_path):
    secret_file = tmp_path / ".jwt_secret"
    secret_file.write_text("deadbeef" * 8, encoding="utf-8")

    secret = load_or_create_jwt_secret(str(secret_file))

    assert secret == "deadbeef" * 8


def test_jwt_secret_stable_across_calls(tmp_path):
    secret_file = tmp_path / ".jwt_secret"
    first = load_or_create_jwt_secret(str(secret_file))
    second = load_or_create_jwt_secret(str(secret_file))
    assert first == second
