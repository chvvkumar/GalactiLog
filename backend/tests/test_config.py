import os
from unittest.mock import MagicMock

import pytest

from app.config import (
    Settings,
    client_ip_from_request,
    get_jwt_secret,
    jwt_secret_persisted,
    load_or_create_jwt_secret,
    missing_all_credentials,
)


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


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permission bits aren't meaningful on Windows")
def test_jwt_secret_file_created_with_owner_only_perms(tmp_path):
    secret_file = tmp_path / ".jwt_secret"
    load_or_create_jwt_secret(str(secret_file))
    mode = secret_file.stat().st_mode & 0o777
    assert mode == 0o600


def test_jwt_secret_no_temp_files_left_behind(tmp_path):
    secret_file = tmp_path / ".jwt_secret"
    load_or_create_jwt_secret(str(secret_file))
    # Loser-ish path too: call again with the file already present.
    load_or_create_jwt_secret(str(secret_file))
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != ".jwt_secret"]
    assert leftovers == []


def test_jwt_secret_concurrent_callers_converge(tmp_path):
    """Racing callers must all end up with the secret persisted in the file.

    The write publishes a fully written temp file atomically (os.link), so
    a race loser can never read a partial file and silently diverge onto
    its own unpersisted secret.
    """
    import threading

    secret_file = tmp_path / ".jwt_secret"
    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(load_or_create_jwt_secret(str(secret_file)))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    persisted = secret_file.read_text(encoding="utf-8").strip()
    assert persisted
    assert set(results) == {persisted}


def test_jwt_secret_persisted_true_when_file_matches(tmp_path):
    secret_file = tmp_path / ".jwt_secret"
    secret = load_or_create_jwt_secret(str(secret_file))
    assert jwt_secret_persisted(str(secret_file), secret) is True


def test_jwt_secret_persisted_false_when_file_unreadable(tmp_path):
    # Simulates the production bug: file exists but the current process
    # cannot read it back (e.g. owned by a different user).
    secret_file = tmp_path / "does-not-exist" / ".jwt_secret"
    assert jwt_secret_persisted(str(secret_file), "some-secret") is False


# ---------------------------------------------------------------------------
# Phase 9 Task 1: startup credential fail-fast gate decision function
# ---------------------------------------------------------------------------

def test_missing_all_credentials_refuses_when_all_three_absent():
    assert missing_all_credentials(
        admin_password_env="",
        jwt_secret_env="",
        jwt_secret_file_exists=False,
        has_admin_user=False,
    ) is True


def test_missing_all_credentials_boots_when_admin_password_env_present():
    assert missing_all_credentials(
        admin_password_env="hunter2",
        jwt_secret_env="",
        jwt_secret_file_exists=False,
        has_admin_user=False,
    ) is False


def test_missing_all_credentials_boots_when_admin_user_present():
    assert missing_all_credentials(
        admin_password_env="",
        jwt_secret_env="",
        jwt_secret_file_exists=False,
        has_admin_user=True,
    ) is False


def test_missing_all_credentials_boots_when_jwt_secret_env_present():
    assert missing_all_credentials(
        admin_password_env="",
        jwt_secret_env="some-secret",
        jwt_secret_file_exists=False,
        has_admin_user=False,
    ) is False


def test_missing_all_credentials_boots_when_jwt_secret_file_present():
    assert missing_all_credentials(
        admin_password_env="",
        jwt_secret_env="",
        jwt_secret_file_exists=True,
        has_admin_user=False,
    ) is False


def test_missing_all_credentials_boots_when_password_and_admin_user_present():
    assert missing_all_credentials(
        admin_password_env="hunter2",
        jwt_secret_env="",
        jwt_secret_file_exists=False,
        has_admin_user=True,
    ) is False


def test_missing_all_credentials_boots_when_password_and_jwt_env_present():
    assert missing_all_credentials(
        admin_password_env="hunter2",
        jwt_secret_env="some-secret",
        jwt_secret_file_exists=False,
        has_admin_user=False,
    ) is False


def test_missing_all_credentials_boots_when_admin_user_and_jwt_file_present():
    assert missing_all_credentials(
        admin_password_env="",
        jwt_secret_env="",
        jwt_secret_file_exists=True,
        has_admin_user=True,
    ) is False


def test_missing_all_credentials_boots_when_all_three_present():
    assert missing_all_credentials(
        admin_password_env="hunter2",
        jwt_secret_env="some-secret",
        jwt_secret_file_exists=True,
        has_admin_user=True,
    ) is False


def test_missing_all_credentials_file_existence_check_does_not_create_file(tmp_path):
    """The signal-3 check must be a pure existence check (os.path.exists),
    never get_jwt_secret()/load_or_create_jwt_secret(), which would create
    the file as a side effect and mask a genuinely absent signal on the
    very boot that is trying to detect its absence."""
    secret_file = tmp_path / ".jwt_secret"
    assert not secret_file.exists()

    result = missing_all_credentials(
        admin_password_env="",
        jwt_secret_env="",
        jwt_secret_file_exists=secret_file.exists(),
        has_admin_user=False,
    )

    assert result is True
    assert not secret_file.exists()  # the check itself created nothing


def test_get_jwt_secret_generates_lazily_not_on_import(monkeypatch, tmp_path):
    """Regression test: generation must not be a side effect of importing
    app.config (see get_jwt_secret's docstring for why - root-context
    entrypoint snippets import this module before privileges drop)."""
    from app import config as config_module

    secret_file = tmp_path / ".jwt_secret"
    monkeypatch.setattr(config_module.settings, "jwt_secret", "")
    monkeypatch.setattr(config_module.settings, "jwt_secret_file", str(secret_file))

    assert not secret_file.exists()

    secret = get_jwt_secret()

    assert secret_file.exists()
    assert secret
    assert get_jwt_secret() == secret  # cached, stable across calls
