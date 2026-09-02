"""The public v1 API as a self-contained FastAPI sub-application.

app.main mounts ``v1_app`` at /api/v1, which is what nginx already forwards,
so /api/v1/targets and friends keep the exact paths they had when the router
was included under the /api prefix. Being its own application is what gives
v1 its own OpenAPI document: /api/v1/openapi.json describes only these routes
(no /api/auth, /api/scan, /api/settings) and /api/v1/docs is a Swagger UI
limited to them.

The schema's paths are prefix-free ("/targets"). FastAPI's openapi route reads
the ASGI root_path the mount sets ("/api/v1") and inserts it into `servers`,
so try-out and generated clients resolve /api/v1/targets - and keep resolving
if the whole app is ever served under a further prefix.
"""

from fastapi import FastAPI

from app.api.v1.routes import router

v1_app = FastAPI(
    title="GalactiLog API v1",
    version="1.0.0",
    description=(
        "Read/act API for a GalactiLog library. Authenticate with an API key "
        "as `Authorization: Bearer glg_...`; keys are issued in Settings. "
        "Every route needs a key; POST/PUT routes need a write-enabled one."
    ),
)
# Included as a router (not FastAPI(dependencies=...)) so the key requirement
# covers the API routes only, leaving /api/v1/docs and /api/v1/openapi.json
# reachable without a key - Swagger has to load before it can authorize.
v1_app.include_router(router)

__all__ = ["router", "v1_app"]
