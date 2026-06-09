from app.main import _resolve_cors_config


def test_no_origins_returns_empty():
    origins, creds = _resolve_cors_config(None)
    assert origins == []
    assert creds is True


def test_valid_origins_pass_through():
    origins, creds = _resolve_cors_config("http://localhost:3000, https://app.example.com")
    assert origins == ["http://localhost:3000", "https://app.example.com"]
    assert creds is True


def test_wildcard_disables_credentials():
    origins, creds = _resolve_cors_config("*", allow_credentials=True)
    assert "*" in origins
    assert creds is False


def test_wildcard_among_others_disables_credentials():
    origins, creds = _resolve_cors_config("http://localhost:3000, *")
    assert creds is False


def test_malformed_origins_dropped():
    origins, creds = _resolve_cors_config(
        "http://good.example.com, not-a-url, ftp://bad.example.com, http://"
    )
    assert origins == ["http://good.example.com"]
    assert creds is True


def test_empty_entries_ignored():
    origins, creds = _resolve_cors_config("http://localhost:3000, , ")
    assert origins == ["http://localhost:3000"]
