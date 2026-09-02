import { Component, For, Show } from "solid-js";
import { A } from "@solidjs/router";

// Static reference for the public /api/v1 API. Every URL is built from
// window.location.origin so the examples are copy-pasteable against whatever
// address this instance is reached on. Nothing here issues a live request.
//
// Every response sample and parameter range below is transcribed from
// backend/app/schemas/v1.py and backend/app/api/v1/routes.py (plus the shared
// models those routes reuse: schemas/export.py, schemas/stats_guiding.py,
// schemas/integration.py, schemas/common.py). Field names, nesting and
// nullability are the public contract -- when a v1 model changes, correct the
// matching sample here rather than approximating it.
const origin = () => window.location.origin;

type Method = "GET" | "POST" | "PUT";

interface Endpoint {
  method: Method;
  /** Path below /api/v1, e.g. "/targets/{id}". */
  path: string;
  desc: string;
  /** [name, meaning] pairs: query string or body fields. */
  params?: [string, string][];
  /** Response body sample, or a description for non-JSON responses. */
  example: string;
}

interface Section {
  id: string;
  title: string;
  blurb: string;
  endpoints: Endpoint[];
}

const SECTIONS: Section[] = [
  {
    id: "targets",
    title: "Targets",
    blurb:
      "Everything the catalog knows about an imaged object. A target id is a UUID; use it for every /targets/{id} call below. A target that has not been resolved to a catalog entry is left out of these routes entirely.",
    endpoints: [
      {
        method: "GET",
        path: "/targets",
        desc: "Lists targets with their cumulative totals, one page at a time. No per-session detail: use /targets/{id}/sessions for that.",
        params: [
          ["page", "Page number, 1 or greater. Defaults to 1."],
          ["page_size", "Targets per page, 1 to 200. Defaults to 50."],
          ["sort_by", "integration, lastSession, name, or equipment. Defaults to integration."],
          ["sort_dir", "asc or desc. Defaults to desc."],
        ],
        example: `{
  "items": [
    {
      "id": "b7f1c0d2-3a44-4f19-9a2e-51c0d7e88a10",
      "name": "SH 2-129 - Flying Bat Nebula",
      "other_names": ["OU 4", "SQUID"],
      "catalog_id": "SH 2-129",
      "common_name": "Flying Bat Nebula",
      "position": { "ra": 317.9583, "dec": 59.9472 },
      "object_type": "Emission Nebula",
      "total_integration_seconds": 151200.0,
      "total_frames": 421,
      "filter_totals": { "Ha": 89280.0, "OIII": 61920.0 },
      "equipment": ["Askar 107PHQ", "ZWO ASI2600MM Pro"],
      "first_night": "2025-08-14",
      "last_night": "2025-10-02"
    }
  ],
  "page": 1,
  "page_size": 50,
  "total": 137
}`,
      },
      {
        method: "GET",
        path: "/targets/{id}",
        desc: "Returns one target: the same fields as the listing, plus catalog data and the averaged frame-quality figures.",
        example: `{
  "id": "b7f1c0d2-3a44-4f19-9a2e-51c0d7e88a10",
  "name": "SH 2-129 - Flying Bat Nebula",
  "other_names": ["OU 4", "SQUID"],
  "catalog_id": "SH 2-129",
  "common_name": "Flying Bat Nebula",
  "position": { "ra": 317.9583, "dec": 59.9472 },
  "object_type": "Emission Nebula",
  "total_integration_seconds": 151200.0,
  "total_frames": 421,
  "filter_totals": { "Ha": 89280.0, "OIII": 61920.0 },
  "equipment": ["Askar 107PHQ", "ZWO ASI2600MM Pro"],
  "first_night": "2025-08-14",
  "last_night": "2025-10-02",
  "constellation": "Cepheus",
  "v_mag": null,
  "surface_brightness": null,
  "distance_pc": null,
  "size_major": 90.0,
  "size_minor": 60.0,
  "position_angle": null,
  "session_count": 9,
  "filters_used": ["Ha", "OIII"],
  "avg_hfr": 2.11,
  "avg_hfr_arcsec": 2.53,
  "avg_fwhm_arcsec": 2.41,
  "avg_eccentricity": 0.42,
  "avg_guiding_rms_arcsec": 0.58,
  "avg_detected_stars": 1863.0,
  "catalog_description": "Large emission nebula in Cepheus.",
  "catalog_notes": null,
  "notes": "Squid needs far more OIII than the bat."
}`,
      },
      {
        method: "GET",
        path: "/targets/{id}/sessions",
        desc: "Lists the imaging nights recorded for this target. The response is a bare array, not an object.",
        example: `[
  {
    "date": "2025-09-21",
    "frames": 62,
    "integration_seconds": 22320.0,
    "filters": ["Ha", "OIII"],
    "equipment": ["Askar 107PHQ", "ZWO ASI2600MM Pro"]
  }
]`,
      },
      {
        method: "GET",
        path: "/targets/{id}/sessions/{date}",
        desc: "Returns one night in detail. The date is the imaging night in YYYY-MM-DD form, not the calendar date each frame was written. A malformed date returns 400.",
        example: `{
  "target_name": "SH 2-129 - Flying Bat Nebula",
  "date": "2025-09-21",
  "frames": 62,
  "integration_seconds": 22320.0,
  "equipment": {
    "camera": "ZWO ASI2600MM Pro",
    "telescope": "Askar 107PHQ"
  },
  "filters": [
    {
      "filter": "Ha",
      "frames": 36,
      "integration_seconds": 12960.0,
      "exposure_seconds": 360.0,
      "median_hfr": 2.08,
      "median_eccentricity": 0.41
    },
    {
      "filter": "OIII",
      "frames": 26,
      "integration_seconds": 9360.0,
      "exposure_seconds": 360.0,
      "median_hfr": 2.19,
      "median_eccentricity": 0.44
    }
  ],
  "gain": 100,
  "offset": 50,
  "sensor_temp": -10.0,
  "exposure_seconds": [360.0],
  "first_frame_time": "2025-09-21T21:47:12",
  "last_frame_time": "2025-09-22T04:02:55",
  "median_hfr": 2.11,
  "hfr_arcsec": 2.53,
  "fwhm_arcsec": 2.41,
  "median_eccentricity": 0.42,
  "median_detected_stars": 1863.0,
  "median_guiding_rms_arcsec": 0.58,
  "median_airmass": 1.09,
  "median_ambient_temp": 7.4,
  "median_humidity": 68.0,
  "median_cloud_cover": 0.0,
  "notes": "Thin cloud after 03:10, last 8 subs rejected."
}`,
      },
      {
        method: "GET",
        path: "/targets/{id}/frames",
        desc: "Every LIGHT frame for the target in capture order, with its per-frame measurements. File paths and raw FITS headers are never included.",
        params: [
          ["page", "Page number, 1 or greater. Defaults to 1."],
          ["page_size", "Frames per page, 1 to 1000. Defaults to 200."],
        ],
        example: `{
  "items": [
    {
      "id": "f3a0b911-6c2d-4c7e-a0b8-2f5d9c1e4471",
      "capture_time": "2025-09-21T23:14:07",
      "session_date": "2025-09-21",
      "filter": "Ha",
      "exposure_seconds": 360.0,
      "telescope": "Askar 107PHQ",
      "camera": "ZWO ASI2600MM Pro",
      "hfr": 2.08,
      "hfr_stdev": 0.14,
      "fwhm_arcsec": 2.38,
      "eccentricity": 0.41,
      "eccentricity_source": "csv",
      "star_count": 1863,
      "guiding_rms_arcsec": 0.56,
      "guiding_rms_ra_arcsec": 0.39,
      "guiding_rms_dec_arcsec": 0.40,
      "guiding_rms_source": "phd2",
      "adu_mean": 1204.3,
      "adu_median": 1187.0,
      "adu_stdev": 96.2,
      "sky_quality": 20.8,
      "gain": 100,
      "sensor_temp": -10.0,
      "focuser_position": 21384,
      "focuser_temp": 8.1,
      "altitude_deg": 71.4,
      "airmass": 1.06,
      "ambient_temp": 7.4,
      "humidity": 68.0,
      "cloud_cover": 0.0
    }
  ],
  "page": 1,
  "page_size": 200,
  "total": 421
}`,
      },
      {
        method: "GET",
        path: "/targets/{id}/export",
        desc: "The acquisition summary used for write-ups and AstroBin uploads: one row per night and filter, plus calibration counts.",
        params: [["sessions", "Comma-separated YYYY-MM-DD dates to include. Omit for every night."]],
        example: `{
  "target_name": "SH 2-129 - Flying Bat Nebula",
  "catalog_id": "SH 2-129",
  "equipment": [
    { "telescope": "Askar 107PHQ", "camera": "ZWO ASI2600MM Pro" }
  ],
  "dates": ["2025-09-21", "2025-10-02"],
  "rows": [
    {
      "date": "2025-09-21",
      "filter": "Ha",
      "astrobin_filter_id": 4663,
      "frames": 36,
      "exposure_seconds": 360.0,
      "total_seconds": 12960.0,
      "gain": 100,
      "sensor_temp": -10,
      "fwhm_arcsec": 2.38,
      "sky_quality": 20.8,
      "ambient_temp": 7.4
    }
  ],
  "calibration": { "darks": 50, "flats": 40, "bias": 100 },
  "total_integration_seconds": 151200.0,
  "bortle": 6
}`,
      },
      {
        method: "GET",
        path: "/targets/{id}/thumbnail",
        desc: "The target's most recent frame thumbnail, falling back to the survey reference image. Returns image/jpeg, not JSON; 404 when neither exists. Point an <img> tag straight at it.",
        example: `HTTP/1.1 200 OK
Content-Type: image/jpeg

(binary JPEG data)`,
      },
    ],
  },
  {
    id: "catalog",
    title: "Search and catalog",
    blurb: "Cross-cutting reads that are not scoped to a single target. Three of these return bare arrays rather than an object with a wrapper key.",
    endpoints: [
      {
        method: "GET",
        path: "/search",
        desc: "Finds targets by primary name, catalog id, common name, or alias. Matching is fuzzy, so \"squid\" finds SH 2-129. Returns a bare array, best score first.",
        params: [
          ["q", "Search text, at least one character. Required."],
          ["limit", "Maximum hits, 1 to 50. Defaults to 10."],
        ],
        example: `[
  {
    "id": "b7f1c0d2-3a44-4f19-9a2e-51c0d7e88a10",
    "name": "SH 2-129 - Flying Bat Nebula",
    "other_names": ["OU 4", "SQUID"],
    "match": "SQUID",
    "score": 1.0
  }
]`,
      },
      {
        method: "GET",
        path: "/nights",
        desc: "One entry per imaging night, oldest first. Without a year this covers the last 365 days; pass a year for that whole calendar year instead. Returns a bare array.",
        params: [["year", "Four-digit year, e.g. 2025. Omit for the last 365 days."]],
        example: `[
  {
    "date": "2025-09-21",
    "integration_seconds": 22320.0,
    "targets": 1,
    "frames": 62
  }
]`,
      },
      {
        method: "GET",
        path: "/stats",
        desc: "Library-wide overview: totals, the biggest targets by integration, seconds per filter, and per-camera and per-telescope counts. The site block is null unless a location or Bortle class is configured.",
        example: `{
  "totals": {
    "targets": 137,
    "frames": 11482,
    "integration_seconds": 4127400.0,
    "nights": 214
  },
  "top_targets": [
    { "name": "SH 2-129 - Flying Bat Nebula", "integration_seconds": 151200.0 }
  ],
  "filter_usage": { "Ha": 1583280.0, "OIII": 1204560.0 },
  "cameras": [
    {
      "name": "ZWO ASI2600MM Pro",
      "frame_count": 8214,
      "integration_seconds": 2711160.0
    }
  ],
  "telescopes": [
    {
      "name": "Askar 107PHQ",
      "frame_count": 8214,
      "integration_seconds": 2711160.0
    }
  ],
  "site": { "latitude": 32.7767, "longitude": -96.797, "bortle": 6 }
}`,
      },
      {
        method: "GET",
        path: "/guiding",
        desc: "PHD2 guiding performance per telescope, plus the same figures split by target altitude. Every RMS is null when no session in the group had enough guide frames to measure.",
        example: `{
  "unmapped_session_count": 3,
  "rigs": [
    {
      "telescope": "Askar 107PHQ",
      "session_count": 96,
      "gated_session_count": 91,
      "guided_hours": 412.7,
      "rms_total_arcsec": 0.58,
      "rms_ra_arcsec": 0.41,
      "rms_dec_arcsec": 0.41,
      "rms_total_filtered_arcsec": 0.54,
      "ra_dec_ratio": 1.0,
      "settle_median_s": 6.2,
      "exposure_ms_values": [2000, 2500]
    }
  ],
  "altitude_bands": [
    {
      "telescope": "Askar 107PHQ",
      "band": "30-60",
      "session_count": 38,
      "rms_total_arcsec": 0.63,
      "rms_ra_arcsec": 0.45,
      "rms_dec_arcsec": 0.44
    }
  ]
}`,
      },
      {
        method: "GET",
        path: "/mosaics",
        desc: "Lists detected mosaics: sets of targets whose panels form one larger frame. Returns a bare array.",
        example: `[
  {
    "id": "2a6e5f70-9d31-4c88-b0f2-7c8e1a2b3c4d",
    "name": "Flying Bat and Squid",
    "notes": null,
    "panel_count": 2,
    "total_integration_seconds": 198000.0,
    "total_frames": 551,
    "completion_pct": 76.4,
    "first_session": "2025-08-14",
    "last_session": "2025-10-02"
  }
]`,
      },
      {
        method: "GET",
        path: "/mosaics/{id}",
        desc: "Returns one mosaic with each panel, its target, its position, and its per-filter integration.",
        example: `{
  "id": "2a6e5f70-9d31-4c88-b0f2-7c8e1a2b3c4d",
  "name": "Flying Bat and Squid",
  "notes": null,
  "total_integration_seconds": 198000.0,
  "total_frames": 551,
  "available_filters": ["Ha", "OIII"],
  "panels": [
    {
      "panel_id": "9c1d4e8b-77a2-4b30-8f61-0e2a5c9d1f33",
      "target_id": "b7f1c0d2-3a44-4f19-9a2e-51c0d7e88a10",
      "target_name": "SH 2-129 - Flying Bat Nebula",
      "panel_label": "Panel 1",
      "sort_order": 0,
      "position": { "ra": 317.9583, "dec": 59.9472 },
      "total_integration_seconds": 151200.0,
      "total_frames": 421,
      "filter_totals": { "Ha": 89280.0, "OIII": 61920.0 },
      "last_session_date": "2025-10-02"
    }
  ]
}`,
      },
      {
        method: "GET",
        path: "/scan/status",
        desc: "The state of the library scan. state is idle, scanning, ingesting, complete, or stalled; running is true for scanning, ingesting, and stalled. pending_rescan means a follow-up scan is already queued behind this one. Timestamps are Unix epoch seconds, not ISO strings.",
        example: `{
  "state": "ingesting",
  "running": true,
  "pending_rescan": false,
  "started_at": 1759600720.4,
  "completed_at": null,
  "discovered": 11482,
  "total": 11482,
  "completed": 8213,
  "failed": 2,
  "percent": 71.5,
  "message": "Ingesting frames"
}`,
      },
    ],
  },
  {
    id: "actions",
    title: "Actions",
    blurb: "These change something, so they need a key created with \"Allow actions\" ticked. A read-only key gets 403 here.",
    endpoints: [
      {
        method: "POST",
        path: "/scan",
        desc: "Starts a library scan and returns 202. If a scan is already running the response is \"queued\" instead, meaning one follow-up scan was recorded to run after it; triggering again while that one waits changes nothing.",
        example: `{ "status": "started" }

or, when a scan was already running:

{ "status": "queued" }`,
      },
      {
        method: "POST",
        path: "/targets/{id}/point/nina",
        desc: "Sends the target's coordinates, and its position angle when known, to a configured NINA instance. 409 if the target has no coordinates, 404 if no matching instance is enabled.",
        params: [["instance", "Name of the configured NINA instance. Optional; defaults to the first enabled one."]],
        example: `Request body (optional):
{ "instance": "Observatory NINA" }

Response:
{ "ok": true }`,
      },
      {
        method: "POST",
        path: "/targets/{id}/point/stellarium",
        desc: "Centers a configured Stellarium instance on the target. Same 409 and 404 conditions as the NINA route.",
        params: [["instance", "Name of the configured Stellarium instance. Optional; defaults to the first enabled one."]],
        example: `Request body (optional):
{ "instance": "Desk Stellarium" }

Response:
{ "ok": true }`,
      },
      {
        method: "PUT",
        path: "/targets/{id}/notes",
        desc: "Replaces the target's notes with the text you send. Send null or an empty string to clear them.",
        params: [["notes", "The full replacement note text, or null to clear."]],
        example: `Request body:
{ "notes": "Squid needs far more OIII than the bat." }

Response:
{ "status": "ok" }`,
      },
      {
        method: "PUT",
        path: "/targets/{id}/sessions/{date}/notes",
        desc: "Replaces the notes on one imaging night of that target. A malformed date returns 400.",
        params: [["notes", "The full replacement note text, or null to clear."]],
        example: `Request body:
{ "notes": "Thin cloud after 03:10, last 8 subs rejected." }

Response:
{ "status": "ok" }`,
      },
    ],
  },
];

const CodeBlock: Component<{ children: string }> = (props) => (
  <pre class="overflow-x-auto rounded-[var(--radius-sm)] bg-theme-base border border-theme-border p-3 text-xs font-mono text-theme-text-primary leading-relaxed">
    <code>{props.children}</code>
  </pre>
);

const MethodChip: Component<{ method: Method }> = (props) => (
  <span
    class={`shrink-0 font-mono text-[11px] font-semibold px-1.5 py-0.5 rounded border ${
      props.method === "GET"
        ? "bg-theme-info/15 text-theme-info border-theme-info/30"
        : "bg-theme-warning/15 text-theme-warning border-theme-warning/30"
    }`}
  >
    {props.method}
  </span>
);

const EndpointCard: Component<{ endpoint: Endpoint }> = (props) => (
  <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-3">
    <div class="flex items-start gap-2 flex-wrap">
      <MethodChip method={props.endpoint.method} />
      <code class="font-mono text-xs text-theme-text-primary break-all">
        {origin()}/api/v1{props.endpoint.path}
      </code>
    </div>
    <p class="text-sm text-theme-text-secondary">{props.endpoint.desc}</p>
    <Show when={props.endpoint.params}>
      <dl class="text-xs space-y-1">
        <For each={props.endpoint.params}>
          {([name, meaning]) => (
            <div class="flex gap-2">
              <dt class="font-mono text-theme-text-primary shrink-0">{name}</dt>
              <dd class="text-theme-text-secondary">{meaning}</dd>
            </div>
          )}
        </For>
      </dl>
    </Show>
    <CodeBlock>{props.endpoint.example}</CodeBlock>
  </div>
);

export const ApiDocsTab: Component = () => (
  <div class="space-y-6">
    {/* Intro */}
    <div class="space-y-3">
      <h2 class="text-base font-medium text-theme-text-primary">API</h2>
      <p class="text-sm text-theme-text-secondary">
        GalactiLog exposes a read-mostly HTTP API at <code class="font-mono text-xs text-theme-text-primary">/api/v1</code> so scripts,
        dashboards, and observatory automation can use the same catalog the web interface shows. Responses are JSON, apart from the
        thumbnail endpoint which returns an image.
      </p>
      <p class="text-sm text-theme-text-secondary">
        Create a key on the{" "}
        <A href="/settings?tab=api-keys" class="text-theme-accent hover:underline">
          API Keys
        </A>{" "}
        tab, then send it on every request as a bearer token:
      </p>
      <CodeBlock>{`Authorization: Bearer glg_...`}</CodeBlock>
      <p class="text-sm text-theme-text-secondary">Listing your targets, in full:</p>
      <CodeBlock>{`curl -H "Authorization: Bearer glg_..." ${origin()}/api/v1/targets`}</CodeBlock>
      <p class="text-sm text-theme-text-secondary">
        A plain key reads. Triggering scans, pointing a telescope, and writing notes need a key created with "Allow actions" ticked.
      </p>
    </div>

    {/* Jump-to nav */}
    <div class="flex flex-wrap gap-2">
      <For each={SECTIONS}>
        {(s) => (
          <a
            href={`#api-${s.id}`}
            class="text-xs px-2.5 py-1 rounded-[var(--radius-sm)] bg-theme-surface border border-theme-border text-theme-text-secondary hover:text-theme-text-primary hover:bg-theme-hover transition-colors"
          >
            {s.title}
          </a>
        )}
      </For>
      <a
        href="#api-notes"
        class="text-xs px-2.5 py-1 rounded-[var(--radius-sm)] bg-theme-surface border border-theme-border text-theme-text-secondary hover:text-theme-text-primary hover:bg-theme-hover transition-colors"
      >
        Notes
      </a>
    </div>

    <For each={SECTIONS}>
      {(section) => (
        <section id={`api-${section.id}`} class="space-y-3 scroll-mt-20">
          <h3 class="text-sm font-semibold text-theme-text-primary">{section.title}</h3>
          <p class="text-sm text-theme-text-secondary">{section.blurb}</p>
          <div class="space-y-3">
            <For each={section.endpoints}>{(e) => <EndpointCard endpoint={e} />}</For>
          </div>
        </section>
      )}
    </For>

    {/* Footer notes */}
    <section id="api-notes" class="space-y-3 scroll-mt-20">
      <h3 class="text-sm font-semibold text-theme-text-primary">Notes</h3>
      <dl class="text-sm space-y-3">
        <div>
          <dt class="text-theme-text-primary font-medium">Versioning</dt>
          <dd class="text-theme-text-secondary">
            v1 is stable. Fields may be added to a response, but existing fields will not be renamed, retyped, or removed. Ignore
            fields you do not recognize rather than failing on them. Anything breaking would ship as /api/v2.
          </dd>
        </div>
        <div>
          <dt class="text-theme-text-primary font-medium">Errors</dt>
          <dd class="text-theme-text-secondary">
            Failures return the HTTP status plus a JSON body of the form{" "}
            <code class="font-mono text-xs text-theme-text-primary">{`{"detail": "..."}`}</code>. 401 means the bearer header is
            missing or the key is invalid or revoked. 403 means the key is valid but read-only and the endpoint changes something.
            404 means no such target, session, mosaic, thumbnail, or configured instance. 409 means the target has no coordinates to
            point at. 400 means a date was not YYYY-MM-DD.
          </dd>
        </div>
        <div>
          <dt class="text-theme-text-primary font-medium">Rate limit</dt>
          <dd class="text-theme-text-secondary">
            120 requests per key per 60 seconds. Going over returns 429 with{" "}
            <code class="font-mono text-xs text-theme-text-primary">{`{"detail": "Rate limit exceeded"}`}</code>; wait for the window
            to roll over and retry. Poll /scan/status every few seconds at most, not in a tight loop.
          </dd>
        </div>
        <div>
          <dt class="text-theme-text-primary font-medium">Revoking</dt>
          <dd class="text-theme-text-secondary">
            Revoking a key takes effect immediately: the next request with it gets 401. Keys are stored hashed, so a lost key cannot
            be recovered, only replaced.
          </dd>
        </div>
      </dl>
    </section>
  </div>
);

export default ApiDocsTab;
