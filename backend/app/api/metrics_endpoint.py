import hmac
import os

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

router = APIRouter(prefix="/api")

_BEARER_PREFIX = "Bearer "


@router.get("/metrics", include_in_schema=False)
async def metrics(authorization: str | None = Header(default=None)):
    # Optional bearer-token guard. When GALACTILOG_METRICS_TOKEN is set, require
    # a matching `Authorization: Bearer <token>` header. When unset, no token is
    # required (default behavior; access is restricted by the nginx allowlist).
    expected_token = os.environ.get("GALACTILOG_METRICS_TOKEN")
    if expected_token:
        unauthorized = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing metrics token",
        )
        # Require the "Bearer " scheme and a non-empty token; reject other
        # schemes (e.g. "Basic ...") and a bare/empty bearer value.
        if not authorization or not authorization.startswith(_BEARER_PREFIX):
            raise unauthorized
        presented_token = authorization[len(_BEARER_PREFIX):]
        if not presented_token:
            raise unauthorized
        # Constant-time comparison to avoid a timing side-channel.
        if not hmac.compare_digest(presented_token, expected_token):
            raise unauthorized

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
