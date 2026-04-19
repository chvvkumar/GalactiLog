import logging

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])

TIMEOUT = 5.0


class NinaRequest(BaseModel):
    url: str
    ra: float
    dec: float


class StellariumRequest(BaseModel):
    url: str
    ra: float
    dec: float
    target_name: str | None = None


@router.post("/nina/send-coordinates")
async def send_to_nina(req: NinaRequest):
    base = req.url.rstrip("/")
    endpoint = f"{base}/v2/api/framing/set-coordinates?RAangle={req.ra}&DecAngle={req.dec}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(endpoint)
            resp.raise_for_status()
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
                try:
                    resp = await client.post(
                        f"{base}/api/main/focus",
                        content=f"target={req.target_name}",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    resp.raise_for_status()
                    focused = True
                except Exception:
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
