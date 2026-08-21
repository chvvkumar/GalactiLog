import ipaddress
import logging
import os
import re
import socket
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.integration import IntegrationResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])

TIMEOUT = 5.0

# Exception text never goes back to the browser (py/stack-trace-exposure): an
# httpx failure carries internal URLs and library detail. The full exception is
# logged instead, and the log viewer is one page away for an operator.
_NINA_ERROR = "NINA request failed - see server logs for details."
_STELLARIUM_ERROR = "Stellarium request failed - see server logs for details."

# Short timeout for the SSRF DNS resolution probe so a slow/hostile resolver
# cannot hang the request.
_DNS_TIMEOUT = 2.0


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    """Return True if *ip* points at loopback, link-local, or the cloud
    metadata range (169.254.169.254 lives inside link-local 169.254.0.0/16).

    Covers IPv4 (127.0.0.0/8, 169.254.0.0/16) and IPv6 (::1, fe80::/10),
    including IPv4-mapped IPv6 forms which are unwrapped first.
    """
    # Unwrap IPv4-mapped / IPv4-compatible IPv6 (e.g. ::ffff:169.254.169.254).
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_link_local


def _validate_integration_url(url: str) -> None:
    """Validate a caller-supplied integration URL to mitigate SSRF.

    NINA/Stellarium typically run on the user's LAN, so normal private ranges
    (10/8, 172.16/12, 192.168/16) are intentionally allowed. This rejects
    non-http(s) schemes, loopback/link-local/metadata addresses (whether the
    host is a literal IP or a hostname that resolves to one), and enforces an
    optional host allowlist from GALACTILOG_INTEGRATION_ALLOWED_HOSTS.

    Resolving the host introduces a residual TOCTOU window (DNS could change
    between this check and the outbound request). That is accepted for this
    self-hosted, authenticated, LAN-integration threat model.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="URL scheme must be http or https")

    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="URL must include a host")

    # Literal IP (IPv4 or IPv6): block loopback/link-local/metadata directly.
    literal_ip = None
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    if literal_ip is not None and _is_blocked_ip(literal_ip):
        raise HTTPException(status_code=400, detail="URL host resolves to a blocked address")

    allowed = os.environ.get("GALACTILOG_INTEGRATION_ALLOWED_HOSTS")
    if allowed:
        allowed_hosts = {h.strip().lower() for h in allowed.split(",") if h.strip()}
        if host.lower() not in allowed_hosts:
            raise HTTPException(status_code=400, detail="URL host is not in the allowlist")

    # Hostname: resolve and reject if ANY address is blocked. On resolution
    # failure, only reject if it was a literal IP (already handled above);
    # otherwise allow, so air-gapped LAN names that don't resolve here still work.
    if literal_ip is None:
        old_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(_DNS_TIMEOUT)
            infos = socket.getaddrinfo(host, parsed.port, proto=socket.IPPROTO_TCP)
        except (socket.gaierror, OSError):
            infos = None
        finally:
            socket.setdefaulttimeout(old_timeout)
        if infos:
            for info in infos:
                addr = info[4][0]
                try:
                    resolved = ipaddress.ip_address(addr)
                except ValueError:
                    continue
                if _is_blocked_ip(resolved):
                    raise HTTPException(
                        status_code=400, detail="URL host resolves to a blocked address"
                    )

# `\s*(?:-\s*)?` rather than `\s*-?\s*`: the latter lets two adjacent `\s*`
# split a run of spaces every possible way when no digit follows, which is
# quadratic on a caller-supplied name like "M" + 50k spaces (py/polynomial-redos).
# Requiring the literal "-" before the second `\s*` removes the ambiguity while
# matching exactly the same strings.
_CATALOG_RE = re.compile(
    r"^(NGC|IC|M|Sh2|LDN|LBN|Abell|Ced|vdB|Cr|Mel|Barnard|PGC|UGC|Arp)\s*(?:-\s*)?\d+",
    re.IGNORECASE,
)


def _extract_catalog_name(name: str) -> str | None:
    m = _CATALOG_RE.match(name.strip())
    return m.group(0) if m else None


async def _stellarium_focus(client: httpx.AsyncClient, base: str, name: str) -> bool:
    resp = await client.post(
        f"{base}/api/main/focus",
        content=f"target={name}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    return resp.text.strip().lower() == "true"


class NinaRequest(BaseModel):
    url: str
    ra: float
    dec: float
    position_angle: float | None = None


class StellariumRequest(BaseModel):
    url: str
    ra: float
    dec: float
    target_name: str | None = None


@router.post("/nina/send-coordinates", response_model=IntegrationResponse, response_model_exclude_none=True)
async def send_to_nina(req: NinaRequest, current_user: User = Depends(get_current_user)):
    import asyncio

    _validate_integration_url(req.url)
    base = req.url.rstrip("/")
    endpoint = f"{base}/v2/api/framing/set-coordinates?RAangle={req.ra}&DecAngle={req.dec}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(endpoint)
            resp.raise_for_status()
            if req.position_angle is not None:
                # set-coordinates triggers a sky survey image reload which
                # resets rotation. Wait for the reload to complete before
                # applying rotation.
                await asyncio.sleep(2)
                rot_endpoint = f"{base}/v2/api/framing/set-rotation?rotation={req.position_angle}"
                try:
                    rot_resp = await client.get(rot_endpoint)
                    rot_resp.raise_for_status()
                except Exception as e:
                    logger.warning("NINA set-rotation failed for %s: %s", base, e)
        return {"ok": True}
    except Exception:
        logger.exception("NINA send-coordinates failed for %s", base)
        return {"ok": False, "error": _NINA_ERROR}


@router.post("/stellarium/send-coordinates", response_model=IntegrationResponse, response_model_exclude_none=True)
async def send_to_stellarium(req: StellariumRequest, current_user: User = Depends(get_current_user)):
    _validate_integration_url(req.url)
    base = req.url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            focused = False
            if req.target_name:
                catalog_name = _extract_catalog_name(req.target_name)
                names_to_try = []
                if catalog_name and catalog_name != req.target_name:
                    names_to_try.append(catalog_name)
                names_to_try.append(req.target_name)
                for name in names_to_try:
                    try:
                        focused = await _stellarium_focus(client, base, name)
                        if focused:
                            break
                    except Exception as e:
                        logger.debug("Stellarium focus attempt for %r failed: %s", name, e)
                if not focused:
                    logger.debug("Stellarium focus by name failed for %r, falling back to RA/Dec", req.target_name)

            if not focused:
                script = f'core.moveToRaDecJ2000("{req.ra:.6f}d", "{req.dec:.6f}d", 3);'
                resp = await client.post(
                    f"{base}/api/scripts/direct",
                    content=f"code={script}",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()

            await client.post(
                f"{base}/api/main/fov",
                content="fov=20",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        return {"ok": True}
    except Exception:
        logger.exception("Stellarium send-coordinates failed for %s", base)
        return {"ok": False, "error": _STELLARIUM_ERROR}
