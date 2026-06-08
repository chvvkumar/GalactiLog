"""Docker-tag based update check.

Reads the GALACTILOG_GIT_SHA baked into the published image for the running
build's channel tag (snd / dev / latest) via the anonymous Docker registry v2
API, so the running container can tell whether a newer build is available.
"""

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

IMAGE_REPO = os.environ.get("GALACTILOG_IMAGE_REPO", "chvvkumar/galactilog")
GITHUB_REPO = os.environ.get("GALACTILOG_GITHUB_REPO", "chvvkumar/GalactiLog")

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

_AUTH_URL = "https://auth.docker.io/token"
_REGISTRY = "https://registry-1.docker.io"
_HUB = "https://hub.docker.com"

# Accept both OCI and Docker media types for indexes/manifests.
_MANIFEST_ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])

_TIMEOUT = 5.0


def tag_for_version(version: str) -> str | None:
    """Map a running GALACTILOG_VERSION to its moving Docker tag.

    snd -> "snd"; any "-rc." prerelease -> "dev"; strict semver -> "latest";
    anything else (dev, unknown, empty) -> None (no remote tag to check).
    """
    if version == "snd":
        return "snd"
    if "-rc." in version:
        return "dev"
    if _SEMVER_RE.match(version):
        return "latest"
    return None


def _git_sha_from_config(config: dict) -> str | None:
    """Extract GALACTILOG_GIT_SHA from an image config blob.

    The Dockerfile bakes the sha as an ENV var, so it lands in config.Env as
    "GALACTILOG_GIT_SHA=...". Fall back to config.Labels.
    """
    cfg = config.get("config") or {}
    for entry in cfg.get("Env") or []:
        if isinstance(entry, str) and entry.startswith("GALACTILOG_GIT_SHA="):
            value = entry.split("=", 1)[1].strip()
            if value:
                return value
    labels = cfg.get("Labels") or {}
    value = labels.get("GALACTILOG_GIT_SHA")
    if value:
        return str(value).strip() or None
    return None


def _amd64_digest(index: dict) -> str | None:
    """Return the linux/amd64 sub-manifest digest from an index, or None if the
    payload is already a single image manifest (no sub-manifests)."""
    manifests = index.get("manifests")
    if not manifests:
        return None
    for sub in manifests:
        plat = sub.get("platform") or {}
        if plat.get("architecture") == "amd64" and plat.get("os") == "linux":
            return sub.get("digest")
    # Fall back to the first non-"unknown" arch manifest.
    for sub in manifests:
        plat = sub.get("platform") or {}
        if plat.get("architecture") not in (None, "unknown"):
            return sub.get("digest")
    return None


async def fetch_remote_build(repo: str, tag: str) -> dict | None:
    """Read the baked git_sha (and best-effort published_at) for repo:tag.

    Returns {"git_sha": str, "published_at": str | None} or None on any failure.
    """
    try:
        # follow_redirects is required: the config blob GET 307-redirects to a
        # CDN and httpx does NOT follow redirects by default (the body would be
        # empty otherwise).
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            # a. Anonymous pull token.
            resp = await client.get(
                _AUTH_URL,
                params={
                    "service": "registry.docker.io",
                    "scope": f"repository:{repo}:pull",
                },
            )
            if resp.status_code != 200:
                return None
            token = resp.json().get("token")
            if not token:
                return None
            headers = {"Authorization": f"Bearer {token}", "Accept": _MANIFEST_ACCEPT}

            # b. Index or image manifest for the tag.
            resp = await client.get(
                f"{_REGISTRY}/v2/{repo}/manifests/{tag}", headers=headers
            )
            if resp.status_code != 200:
                return None
            top = resp.json()

            # c. Resolve to the amd64 image manifest if this is an index.
            amd64 = _amd64_digest(top)
            if amd64:
                resp = await client.get(
                    f"{_REGISTRY}/v2/{repo}/manifests/{amd64}", headers=headers
                )
                if resp.status_code != 200:
                    return None
                manifest = resp.json()
            else:
                manifest = top

            config_digest = (manifest.get("config") or {}).get("digest")
            if not config_digest:
                return None

            # d. Config blob holds the baked Env / Labels.
            resp = await client.get(
                f"{_REGISTRY}/v2/{repo}/blobs/{config_digest}", headers=headers
            )
            if resp.status_code != 200:
                return None
            git_sha = _git_sha_from_config(resp.json())
            if not git_sha:
                return None

            # e. Best-effort published_at from the Hub tags API.
            published_at = None
            try:
                resp = await client.get(
                    f"{_HUB}/v2/repositories/{repo}/tags/{tag}"
                )
                if resp.status_code == 200:
                    body = resp.json()
                    published_at = body.get("last_updated") or body.get("tag_last_pushed")
            except Exception:
                logger.debug("Docker Hub tags lookup failed for %s:%s", repo, tag)

            return {"git_sha": git_sha, "published_at": published_at}
    except Exception:
        logger.debug("fetch_remote_build failed for %s:%s", repo, tag, exc_info=True)
        return None


async def fetch_latest_release(repo: str) -> dict | None:
    """Fetch the latest GitHub release notes for ``repo`` (owner/name).

    Hits the anonymous GitHub releases API (no auth needed). Returns a mapped
    dict on success, or None on any non-200, exception, or missing payload.
    This is isolated from the Docker-tag detection flow.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/releases/latest"
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            return {
                "tag": data.get("tag_name"),
                "name": data.get("name"),
                "url": data.get("html_url"),
                "body": data.get("body") or "",
                "published_at": data.get("published_at"),
            }
    except Exception:
        logger.debug("fetch_latest_release failed for %s", repo, exc_info=True)
        return None
