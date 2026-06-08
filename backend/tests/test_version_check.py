import json

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from app.services.version_check import (
    tag_for_version,
    fetch_remote_build,
    fetch_latest_release,
)


# ---------------------------------------------------------------------------
# tag_for_version
# ---------------------------------------------------------------------------

class TestTagForVersion:
    def test_snd_maps_to_snd(self):
        assert tag_for_version("snd") == "snd"

    def test_rc_maps_to_dev(self):
        assert tag_for_version("1.4.0-rc.3") == "dev"

    def test_semver_maps_to_latest(self):
        assert tag_for_version("1.4.0") == "latest"

    def test_dev_maps_to_none(self):
        assert tag_for_version("dev") is None

    def test_unknown_maps_to_none(self):
        assert tag_for_version("unknown") is None

    def test_empty_maps_to_none(self):
        assert tag_for_version("") is None


# ---------------------------------------------------------------------------
# fetch_remote_build (mocked registry-v2 flow)
# ---------------------------------------------------------------------------

REPO = "chvvkumar/galactilog"
AMD64_DIGEST = "sha256:amd64manifestdigest"
CONFIG_DIGEST = "sha256:configblobdigest"
GIT_SHA = "86f419da4615b8094cdff9eafdd2d615a86e9b49"

TOKEN_URL = "https://auth.docker.io/token"
REGISTRY = "https://registry-1.docker.io"
HUB = "https://hub.docker.com"


def _index_body():
    return {
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {
                "digest": "sha256:unknownattest",
                "platform": {"architecture": "unknown", "os": "unknown"},
            },
            {
                "digest": AMD64_DIGEST,
                "platform": {"architecture": "amd64", "os": "linux"},
            },
        ],
    }


def _manifest_body():
    return {
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {"digest": CONFIG_DIGEST},
        "layers": [],
    }


def _config_blob_env():
    return {
        "config": {
            "Env": [
                "PATH=/usr/local/bin",
                f"GALACTILOG_GIT_SHA={GIT_SHA}",
                "GALACTILOG_VERSION=snd",
            ]
        }
    }


def _config_blob_label():
    return {
        "config": {
            "Env": ["PATH=/usr/local/bin"],
            "Labels": {"GALACTILOG_GIT_SHA": GIT_SHA},
        }
    }


def _tags_body():
    # Mirror the real Docker Hub tags payload: published_at comes from
    # .last_updated (tag_last_pushed is an alias also present).
    return {
        "last_updated": "2026-06-07T13:47:39Z",
        "tag_last_pushed": "2026-06-07T13:47:39Z",
        "name": "snd",
    }


PUBLISHED_AT = "2026-06-07T13:47:39Z"


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeAsyncClient:
    """Routes GET calls by URL to a configured map of (status, payload)."""

    def __init__(self, routes, captured_kwargs, *args, **kwargs):
        self._routes = routes
        captured_kwargs.update(kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, params=None):
        for prefix, resp in self._routes:
            if url.startswith(prefix):
                return resp
        return FakeResponse(404, {})


def _make_client_factory(routes, captured_kwargs=None):
    if captured_kwargs is None:
        captured_kwargs = {}

    def factory(*args, **kwargs):
        return FakeAsyncClient(routes, captured_kwargs, *args, **kwargs)
    return factory


def _happy_routes(config_blob):
    return [
        (TOKEN_URL, FakeResponse(200, {"token": "abc"})),
        (f"{REGISTRY}/v2/{REPO}/blobs/", FakeResponse(200, config_blob)),
        (f"{REGISTRY}/v2/{REPO}/manifests/snd", FakeResponse(200, _index_body())),
        (f"{REGISTRY}/v2/{REPO}/manifests/{AMD64_DIGEST}", FakeResponse(200, _manifest_body())),
        (f"{HUB}/v2/repositories/{REPO}/tags/snd", FakeResponse(200, _tags_body())),
    ]


class TestFetchRemoteBuild:
    @pytest.mark.asyncio
    async def test_happy_path_env(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            _make_client_factory(_happy_routes(_config_blob_env()), captured),
        )
        result = await fetch_remote_build(REPO, "snd")
        assert result is not None
        assert result["git_sha"] == GIT_SHA
        assert result["published_at"] == PUBLISHED_AT
        # Config blob GET 307-redirects to a CDN; the client MUST follow it.
        assert captured.get("follow_redirects") is True

    @pytest.mark.asyncio
    async def test_happy_path_label_fallback(self, monkeypatch):
        monkeypatch.setattr(
            httpx, "AsyncClient", _make_client_factory(_happy_routes(_config_blob_label()))
        )
        result = await fetch_remote_build(REPO, "snd")
        assert result is not None
        assert result["git_sha"] == GIT_SHA

    @pytest.mark.asyncio
    async def test_token_failure_returns_none(self, monkeypatch):
        routes = [(TOKEN_URL, FakeResponse(500, {}))]
        monkeypatch.setattr(httpx, "AsyncClient", _make_client_factory(routes))
        assert await fetch_remote_build(REPO, "snd") is None

    @pytest.mark.asyncio
    async def test_manifest_failure_returns_none(self, monkeypatch):
        routes = [
            (TOKEN_URL, FakeResponse(200, {"token": "abc"})),
            (f"{REGISTRY}/v2/{REPO}/manifests/snd", FakeResponse(404, {})),
        ]
        monkeypatch.setattr(httpx, "AsyncClient", _make_client_factory(routes))
        assert await fetch_remote_build(REPO, "snd") is None

    @pytest.mark.asyncio
    async def test_config_blob_failure_returns_none(self, monkeypatch):
        routes = [
            (TOKEN_URL, FakeResponse(200, {"token": "abc"})),
            (f"{REGISTRY}/v2/{REPO}/blobs/", FakeResponse(500, {})),
            (f"{REGISTRY}/v2/{REPO}/manifests/snd", FakeResponse(200, _index_body())),
            (f"{REGISTRY}/v2/{REPO}/manifests/{AMD64_DIGEST}", FakeResponse(200, _manifest_body())),
        ]
        monkeypatch.setattr(httpx, "AsyncClient", _make_client_factory(routes))
        assert await fetch_remote_build(REPO, "snd") is None

    @pytest.mark.asyncio
    async def test_missing_git_sha_returns_none(self, monkeypatch):
        blob = {"config": {"Env": ["PATH=/usr/local/bin"], "Labels": {}}}
        monkeypatch.setattr(httpx, "AsyncClient", _make_client_factory(_happy_routes(blob)))
        assert await fetch_remote_build(REPO, "snd") is None

    @pytest.mark.asyncio
    async def test_single_arch_manifest(self, monkeypatch):
        """When manifests/{tag} is already an image manifest (no sub-manifests)."""
        routes = [
            (TOKEN_URL, FakeResponse(200, {"token": "abc"})),
            (f"{REGISTRY}/v2/{REPO}/blobs/", FakeResponse(200, _config_blob_env())),
            (f"{REGISTRY}/v2/{REPO}/manifests/snd", FakeResponse(200, _manifest_body())),
            (f"{HUB}/v2/repositories/{REPO}/tags/snd", FakeResponse(200, _tags_body())),
        ]
        monkeypatch.setattr(httpx, "AsyncClient", _make_client_factory(routes))
        result = await fetch_remote_build(REPO, "snd")
        assert result is not None
        assert result["git_sha"] == GIT_SHA

    @pytest.mark.asyncio
    async def test_tags_failure_still_returns_sha(self, monkeypatch):
        """published_at is best-effort; tags 500 should not nuke the result."""
        routes = [
            (TOKEN_URL, FakeResponse(200, {"token": "abc"})),
            (f"{REGISTRY}/v2/{REPO}/blobs/", FakeResponse(200, _config_blob_env())),
            (f"{REGISTRY}/v2/{REPO}/manifests/snd", FakeResponse(200, _index_body())),
            (f"{REGISTRY}/v2/{REPO}/manifests/{AMD64_DIGEST}", FakeResponse(200, _manifest_body())),
            (f"{HUB}/v2/repositories/{REPO}/tags/snd", FakeResponse(500, {})),
        ]
        monkeypatch.setattr(httpx, "AsyncClient", _make_client_factory(routes))
        result = await fetch_remote_build(REPO, "snd")
        assert result is not None
        assert result["git_sha"] == GIT_SHA
        assert result["published_at"] is None


# ---------------------------------------------------------------------------
# fetch_latest_release (mocked GitHub releases API)
# ---------------------------------------------------------------------------

GITHUB_REPO = "chvvkumar/GalactiLog"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def _release_body():
    return {
        "tag_name": "v1.4.0",
        "name": "GalactiLog 1.4.0",
        "html_url": "https://github.com/chvvkumar/GalactiLog/releases/tag/v1.4.0",
        "body": "## Changes\n- New thing\n- Fixed thing",
        "published_at": "2026-06-05T10:00:00Z",
    }


class _SingleRouteClient:
    """AsyncClient stub that returns one configured response for any GET,
    or raises a configured exception."""

    def __init__(self, response=None, exc=None, *args, **kwargs):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, params=None):
        if self._exc is not None:
            raise self._exc
        return self._response


def _release_client_factory(response=None, exc=None):
    def factory(*args, **kwargs):
        return _SingleRouteClient(response=response, exc=exc, *args, **kwargs)
    return factory


class TestFetchLatestRelease:
    @pytest.mark.asyncio
    async def test_happy_path_maps_fields(self, monkeypatch):
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            _release_client_factory(FakeResponse(200, _release_body())),
        )
        result = await fetch_latest_release(GITHUB_REPO)
        assert result == {
            "tag": "v1.4.0",
            "name": "GalactiLog 1.4.0",
            "url": "https://github.com/chvvkumar/GalactiLog/releases/tag/v1.4.0",
            "body": "## Changes\n- New thing\n- Fixed thing",
            "published_at": "2026-06-05T10:00:00Z",
        }

    @pytest.mark.asyncio
    async def test_missing_body_becomes_empty_string(self, monkeypatch):
        payload = _release_body()
        payload["body"] = None
        monkeypatch.setattr(
            httpx, "AsyncClient", _release_client_factory(FakeResponse(200, payload))
        )
        result = await fetch_latest_release(GITHUB_REPO)
        assert result is not None
        assert result["body"] == ""

    @pytest.mark.asyncio
    async def test_non_200_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            httpx, "AsyncClient", _release_client_factory(FakeResponse(404, {}))
        )
        assert await fetch_latest_release(GITHUB_REPO) is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            _release_client_factory(exc=httpx.ConnectError("boom")),
        )
        assert await fetch_latest_release(GITHUB_REPO) is None


# ---------------------------------------------------------------------------
# GET /api/version/latest endpoint
# ---------------------------------------------------------------------------

class _FakeRedis:
    """In-memory redis stub implementing the subset used by the endpoint."""

    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = value

    async def aclose(self):
        pass


def _patch_redis(monkeypatch, fake):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx():
        yield fake

    monkeypatch.setattr("app.api.router.async_redis", _ctx)


@pytest.fixture
def anon_client():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestVersionLatestEndpoint:
    @pytest.mark.asyncio
    async def test_is_newer_true_when_sha_differs(self, monkeypatch, anon_client):
        monkeypatch.setenv("GALACTILOG_VERSION", "snd")
        monkeypatch.setenv("GALACTILOG_GIT_SHA", "a5e0f4b6f1b173381cd4d86ab1bb024687a35596")
        _patch_redis(monkeypatch, _FakeRedis())
        monkeypatch.setattr(
            "app.api.router.fetch_remote_build",
            AsyncMock(return_value={"git_sha": GIT_SHA, "published_at": "2026-06-07T13:47:37Z"}),
        )
        monkeypatch.setattr(
            "app.api.router.fetch_latest_release", AsyncMock(return_value=None)
        )
        async with anon_client as c:
            resp = await c.get("/api/version/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert data["is_newer"] is True
        assert data["tag"] == "snd"
        assert data["remote_sha"] == GIT_SHA
        assert data["source"] == "dockerhub"
        assert data["compare_url"].endswith(f"a5e0f4b6f1b173381cd4d86ab1bb024687a35596...{GIT_SHA}")

    @pytest.mark.asyncio
    async def test_is_newer_false_when_sha_equal(self, monkeypatch, anon_client):
        monkeypatch.setenv("GALACTILOG_VERSION", "snd")
        monkeypatch.setenv("GALACTILOG_GIT_SHA", GIT_SHA)
        _patch_redis(monkeypatch, _FakeRedis())
        monkeypatch.setattr(
            "app.api.router.fetch_remote_build",
            AsyncMock(return_value={"git_sha": GIT_SHA, "published_at": None}),
        )
        monkeypatch.setattr(
            "app.api.router.fetch_latest_release", AsyncMock(return_value=None)
        )
        async with anon_client as c:
            resp = await c.get("/api/version/latest")
        data = resp.json()
        assert data["available"] is True
        assert data["is_newer"] is False

    @pytest.mark.asyncio
    async def test_unmapped_version_returns_unavailable(self, monkeypatch, anon_client):
        monkeypatch.setenv("GALACTILOG_VERSION", "dev")
        monkeypatch.setenv("GALACTILOG_GIT_SHA", "unknown")
        _patch_redis(monkeypatch, _FakeRedis())
        called = AsyncMock(return_value={"git_sha": GIT_SHA, "published_at": None})
        monkeypatch.setattr("app.api.router.fetch_remote_build", called)
        monkeypatch.setattr(
            "app.api.router.fetch_latest_release", AsyncMock(return_value=None)
        )
        async with anon_client as c:
            resp = await c.get("/api/version/latest")
        data = resp.json()
        assert data["available"] is False
        assert data["is_newer"] is False
        assert data["source"] == "dockerhub"
        called.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_none_no_crash(self, monkeypatch, anon_client):
        monkeypatch.setenv("GALACTILOG_VERSION", "snd")
        monkeypatch.setenv("GALACTILOG_GIT_SHA", "a5e0f4b")
        _patch_redis(monkeypatch, _FakeRedis())
        monkeypatch.setattr(
            "app.api.router.fetch_remote_build", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(
            "app.api.router.fetch_latest_release", AsyncMock(return_value=None)
        )
        async with anon_client as c:
            resp = await c.get("/api/version/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False
        assert data["is_newer"] is False

    @pytest.mark.asyncio
    async def test_unknown_running_sha_never_newer(self, monkeypatch, anon_client):
        monkeypatch.setenv("GALACTILOG_VERSION", "snd")
        monkeypatch.setenv("GALACTILOG_GIT_SHA", "unknown")
        _patch_redis(monkeypatch, _FakeRedis())
        monkeypatch.setattr(
            "app.api.router.fetch_remote_build",
            AsyncMock(return_value={"git_sha": GIT_SHA, "published_at": None}),
        )
        monkeypatch.setattr(
            "app.api.router.fetch_latest_release", AsyncMock(return_value=None)
        )
        async with anon_client as c:
            resp = await c.get("/api/version/latest")
        data = resp.json()
        assert data["is_newer"] is False

    @pytest.mark.asyncio
    async def test_release_populated_when_github_succeeds(self, monkeypatch, anon_client):
        monkeypatch.setenv("GALACTILOG_VERSION", "snd")
        monkeypatch.setenv("GALACTILOG_GIT_SHA", "a5e0f4b6f1b173381cd4d86ab1bb024687a35596")
        _patch_redis(monkeypatch, _FakeRedis())
        monkeypatch.setattr(
            "app.api.router.fetch_remote_build",
            AsyncMock(return_value={"git_sha": GIT_SHA, "published_at": "2026-06-07T13:47:37Z"}),
        )
        release = {
            "tag": "v1.4.0",
            "name": "GalactiLog 1.4.0",
            "url": "https://github.com/chvvkumar/GalactiLog/releases/tag/v1.4.0",
            "body": "## Changes\n- New thing",
            "published_at": "2026-06-05T10:00:00Z",
        }
        monkeypatch.setattr(
            "app.api.router.fetch_latest_release", AsyncMock(return_value=release)
        )
        async with anon_client as c:
            resp = await c.get("/api/version/latest")
        assert resp.status_code == 200
        data = resp.json()
        # Docker detection fields unaffected.
        assert data["is_newer"] is True
        assert data["remote_sha"] == GIT_SHA
        assert data["source"] == "dockerhub"
        # Release notes added.
        assert data["release"] == release

    @pytest.mark.asyncio
    async def test_release_null_when_github_fails(self, monkeypatch, anon_client):
        monkeypatch.setenv("GALACTILOG_VERSION", "snd")
        monkeypatch.setenv("GALACTILOG_GIT_SHA", GIT_SHA)
        _patch_redis(monkeypatch, _FakeRedis())
        monkeypatch.setattr(
            "app.api.router.fetch_remote_build",
            AsyncMock(return_value={"git_sha": GIT_SHA, "published_at": None}),
        )
        monkeypatch.setattr(
            "app.api.router.fetch_latest_release", AsyncMock(return_value=None)
        )
        async with anon_client as c:
            resp = await c.get("/api/version/latest")
        assert resp.status_code == 200
        data = resp.json()
        # Docker fields still present and correct.
        assert data["available"] is True
        assert data["is_newer"] is False
        assert data["remote_sha"] == GIT_SHA
        # Release is null on GitHub failure.
        assert data["release"] is None
