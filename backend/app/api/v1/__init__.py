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

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

from app.api.v1.routes import router

# CSS-only restyle of Swagger UI to GalactiLog's dark palette (values from
# frontend/src/index.css "Deep Neutral" fallbacks). Injected before </head>
# on the custom /docs route below; the Swagger assets themselves still come
# from get_swagger_ui_html's default CDN.
_DOCS_STYLE = """
<style>
:root {
  --glg-bg: #121212;
  --glg-surface: #1a1a1a;
  --glg-elevated: #242424;
  --glg-input: #161616;
  --glg-border: #1e1e1e;
  --glg-border-em: #252525;
  --glg-text: #f0f0f0;
  --glg-text-2: #999999;
  --glg-accent: #60a5fa;
  --glg-success: #4ade80;
  --glg-warning: #fbbf24;
  --glg-error: #f87171;
}
html, body { background: var(--glg-bg); }
body, .swagger-ui { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
.swagger-ui .topbar { display: none; }
.swagger-ui,
.swagger-ui .info .title, .swagger-ui .info p, .swagger-ui .info li,
.swagger-ui .info .base-url,
.swagger-ui .opblock .opblock-summary-description,
.swagger-ui .opblock-description-wrapper p,
.swagger-ui .opblock-tag, .swagger-ui .opblock-tag small,
.swagger-ui .opblock .opblock-section-header h4,
.swagger-ui table thead tr th, .swagger-ui table thead tr td,
.swagger-ui .parameter__name, .swagger-ui .parameter__type,
.swagger-ui .parameter__extension, .swagger-ui .parameter__in,
.swagger-ui .response-col_status, .swagger-ui .response-col_links,
.swagger-ui .responses-inner h4, .swagger-ui .responses-inner h5,
.swagger-ui .model, .swagger-ui .model-title,
.swagger-ui section.models h4, .swagger-ui section.models h5,
.swagger-ui .tab li, .swagger-ui label,
.swagger-ui .dialog-ux .modal-ux-content p,
.swagger-ui .dialog-ux .modal-ux-content h4,
.swagger-ui .dialog-ux .modal-ux-header h3,
.swagger-ui .auth-container .wrapper,
.swagger-ui .scheme-container .schemes > label,
.swagger-ui .loading-container .loading::after {
  color: var(--glg-text);
}
.swagger-ui .info .title small pre { color: var(--glg-text); }
.swagger-ui .opblock .opblock-summary-path,
.swagger-ui .opblock .opblock-summary-path__deprecated { color: var(--glg-text); }
.swagger-ui .markdown p, .swagger-ui .markdown li,
.swagger-ui .renderedMarkdown p { color: var(--glg-text-2); }
.swagger-ui .markdown code, .swagger-ui code, .swagger-ui .prop-format {
  color: var(--glg-accent);
  font-family: 'Fira Code', ui-monospace, monospace;
}
.swagger-ui .scheme-container {
  background: var(--glg-surface);
  box-shadow: none;
  border-bottom: 1px solid var(--glg-border-em);
}
.swagger-ui .opblock-tag { border-bottom: 1px solid var(--glg-border-em); }
.swagger-ui .opblock {
  background: var(--glg-surface);
  border-color: var(--glg-border-em);
  box-shadow: none;
}
.swagger-ui .opblock .opblock-section-header {
  background: var(--glg-elevated);
  box-shadow: none;
}
.swagger-ui .opblock.opblock-get { border-color: #164e63; background: rgba(34, 211, 238, 0.06); }
.swagger-ui .opblock.opblock-get .opblock-summary-method { background: #0e7490; }
.swagger-ui .opblock.opblock-get .opblock-summary { border-color: #164e63; }
.swagger-ui .opblock.opblock-post { border-color: #14532d; background: rgba(74, 222, 128, 0.06); }
.swagger-ui .opblock.opblock-post .opblock-summary-method { background: #15803d; }
.swagger-ui .opblock.opblock-post .opblock-summary { border-color: #14532d; }
.swagger-ui .opblock.opblock-put { border-color: #713f12; background: rgba(251, 191, 36, 0.06); }
.swagger-ui .opblock.opblock-put .opblock-summary-method { background: #a16207; }
.swagger-ui .opblock.opblock-put .opblock-summary { border-color: #713f12; }
.swagger-ui .opblock.opblock-delete { border-color: #7f1d1d; background: rgba(248, 113, 113, 0.06); }
.swagger-ui .opblock.opblock-delete .opblock-summary-method { background: #b91c1c; }
.swagger-ui .opblock.opblock-delete .opblock-summary { border-color: #7f1d1d; }
.swagger-ui .opblock-body pre.microlight,
.swagger-ui .highlight-code > .microlight {
  background: var(--glg-input) !important;
  color: var(--glg-text);
}
.swagger-ui .model-box, .swagger-ui section.models .model-container {
  background: var(--glg-elevated);
}
.swagger-ui section.models { border-color: var(--glg-border-em); }
.swagger-ui section.models.is-open h4 { border-bottom-color: var(--glg-border-em); }
.swagger-ui input[type=text], .swagger-ui input[type=password],
.swagger-ui input[type=search], .swagger-ui input[type=email],
.swagger-ui textarea, .swagger-ui select {
  background: var(--glg-input);
  border: 1px solid var(--glg-border-em);
  color: var(--glg-text);
}
.swagger-ui select { box-shadow: none; }
/* Swagger scopes the auth dialog's input more tightly than the rule above, so
   without this the one field you actually type a key into keeps a light border. */
.swagger-ui .auth-container input[type=text],
.swagger-ui .auth-container input[type=password] {
  background: var(--glg-input);
  border: 1px solid var(--glg-border-em);
  color: var(--glg-text);
}
.swagger-ui input:focus, .swagger-ui textarea:focus, .swagger-ui select:focus {
  outline: none;
  border-color: var(--glg-accent);
}
.swagger-ui input:disabled, .swagger-ui textarea:disabled, .swagger-ui select:disabled {
  background: var(--glg-bg);
  color: var(--glg-text-2);
  cursor: not-allowed;
}
/* Version and spec-format pills ship as bright stock chips; tone them to the
   palette so the page header is not the loudest thing on a dark page. */
.swagger-ui .info .title small,
.swagger-ui .info .title small.version-stamp { background: var(--glg-elevated); }
.swagger-ui .info a, .swagger-ui .info a:hover { color: var(--glg-accent); }
/* Swagger UI 5.x renders OAS 3.1 schemas with json-schema-2020-12 markup,
   which its stock stylesheet paints as light chips - re-ground it all dark. */
.swagger-ui .json-schema-2020-12,
.swagger-ui .json-schema-2020-12-head,
.swagger-ui .json-schema-2020-12-body,
.swagger-ui .json-schema-2020-12-accordion,
.swagger-ui .json-schema-2020-12-expand-deep-button,
.swagger-ui .json-schema-2020-12-property,
.swagger-ui .json-schema-2020-12__attribute,
.swagger-ui .model-box .json-schema-2020-12:hover,
.swagger-ui .json-schema-2020-12:hover {
  background: transparent;
  border-color: var(--glg-border-em);
  color: var(--glg-text);
}
.swagger-ui .json-schema-2020-12__title,
.swagger-ui .json-schema-2020-12-property .json-schema-2020-12__title,
.swagger-ui .json-schema-2020-12-keyword__name,
.swagger-ui .json-schema-2020-12-keyword__value { color: var(--glg-text); }
.swagger-ui .json-schema-2020-12-keyword__value--warning,
.swagger-ui .json-schema-2020-12__attribute--muted,
.swagger-ui .json-schema-2020-12-keyword__name--secondary,
.swagger-ui .json-schema-2020-12-keyword__value--secondary { color: var(--glg-text-2); }
.swagger-ui .json-schema-2020-12-keyword__value--const,
.swagger-ui .json-schema-2020-12-keyword__value--primary,
.swagger-ui .json-schema-2020-12__attribute--primary { color: var(--glg-accent); }
.swagger-ui .json-schema-2020-12-accordion,
.swagger-ui .json-schema-2020-12-expand-deep-button {
  color: var(--glg-accent);
}
.swagger-ui .json-schema-2020-12-accordion__icon svg,
.swagger-ui .json-schema-2020-12-accordion svg { fill: var(--glg-text); }
.swagger-ui .model-box, .swagger-ui .model-box .model-box { background: var(--glg-elevated); }
.swagger-ui section.models .model-container .model-box { background: transparent; }
.swagger-ui section.models .model-container,
.swagger-ui section.models .model-container:hover {
  background: var(--glg-elevated);
  border: 1px solid var(--glg-border-em);
}
.swagger-ui .model .property, .swagger-ui .model .property.primitive { color: var(--glg-text-2); }
.swagger-ui .btn { color: var(--glg-text); border-color: var(--glg-border-em); }
.swagger-ui .btn.try-out__btn {
  color: var(--glg-accent);
  border: 1px solid var(--glg-accent);
  background: transparent;
}
/* Stock cancel/clear buttons are grey-on-grey once the page goes dark, which
   reads as disabled - keep a border you can actually see. */
.swagger-ui .btn.try-out__btn.cancel, .swagger-ui .btn.btn-clear {
  color: var(--glg-text);
  border: 1px solid var(--glg-text-2);
  background: transparent;
}
.swagger-ui .btn.try-out__btn.cancel:hover, .swagger-ui .btn.btn-clear:hover,
.swagger-ui .btn.try-out__btn:hover, .swagger-ui .btn.authorize:hover {
  background: var(--glg-elevated);
}
.swagger-ui .btn.authorize {
  color: var(--glg-accent);
  border-color: var(--glg-accent);
  background: transparent;
}
.swagger-ui .btn.authorize svg { fill: var(--glg-accent); }
/* .btn above paints every button in light text; Execute is a filled accent
   button, so white-on-#60a5fa would land near 2:1. Ink it dark instead. */
.swagger-ui .btn.execute {
  background: var(--glg-accent);
  border-color: var(--glg-accent);
  color: #0b1220;
}
.swagger-ui .btn.execute:hover { background: #93c5fd; border-color: #93c5fd; }
.swagger-ui .dialog-ux .modal-ux {
  background: var(--glg-surface);
  border-color: var(--glg-border-em);
}
.swagger-ui .dialog-ux .modal-ux-header { border-bottom-color: var(--glg-border-em); }
.swagger-ui .dialog-ux .backdrop-ux { background: rgba(0, 0, 0, 0.7); }
.swagger-ui .auth-btn-wrapper { justify-content: flex-start; }
.swagger-ui svg.arrow, .swagger-ui .expand-operation svg,
.swagger-ui .model-toggle::after { filter: invert(0.85); }
.swagger-ui .responses-inner { color: var(--glg-text-2); }
.swagger-ui .response-col_description__inner div.markdown {
  background: var(--glg-input);
  color: var(--glg-text);
}
.swagger-ui .copy-to-clipboard { background: var(--glg-elevated); }
.swagger-ui ::placeholder { color: var(--glg-text-2); }
</style>
"""

v1_app = FastAPI(
    title="GalactiLog API v1",
    version="1.0.0",
    description=(
        "Read/act API for a GalactiLog library. Authenticate with an API key "
        "as `Authorization: Bearer glg_...`; keys are issued in Settings. "
        "Every route needs a key; POST/PUT routes need a write-enabled one."
    ),
    docs_url=None,
)


@v1_app.get("/docs", include_in_schema=False)
async def custom_swagger_ui(request: Request) -> HTMLResponse:
    """Stock Swagger UI page with GalactiLog's dark palette appended.

    Rebuilds what docs_url would have served (root_path-prefixed spec URL,
    same CDN assets) and splices the style block in before </head>.
    """
    root_path = request.scope.get("root_path", "").rstrip("/")
    page = get_swagger_ui_html(
        openapi_url=root_path + v1_app.openapi_url,
        title=f"{v1_app.title} - Swagger UI",
    )
    html = page.body.decode("utf-8").replace("</head>", _DOCS_STYLE + "</head>")
    return HTMLResponse(html)
# Included as a router (not FastAPI(dependencies=...)) so the key requirement
# covers the API routes only, leaving /api/v1/docs and /api/v1/openapi.json
# reachable without a key - Swagger has to load before it can authorize.
v1_app.include_router(router)

__all__ = ["router", "v1_app"]
