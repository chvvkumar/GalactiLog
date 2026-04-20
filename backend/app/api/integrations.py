import logging
import re

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])

TIMEOUT = 5.0

_CATALOG_RE = re.compile(
    r"^(NGC|IC|M|Sh2|LDN|LBN|Abell|Ced|vdB|Cr|Mel|Barnard|PGC|UGC|Arp)\s*[-]?\s*\d+",
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


@router.post("/nina/send-coordinates")
async def send_to_nina(req: NinaRequest):
    import asyncio

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
    except Exception as e:
        logger.warning("NINA send-coordinates failed for %s: %s", base, e)
        return {"ok": False, "error": str(e)}


@router.post("/stellarium/send-coordinates")
async def send_to_stellarium(req: StellariumRequest):
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
                    except Exception:
                        pass
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
    except Exception as e:
        logger.warning("Stellarium send-coordinates failed for %s: %s", base, e)
        return {"ok": False, "error": str(e)}
