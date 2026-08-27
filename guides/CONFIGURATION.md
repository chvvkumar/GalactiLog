# Configuration Guide

## Environment Variables

All configuration is done via `GALACTILOG_*` environment variables in `docker-compose.yml`. See [`docker-compose.example.yml`](../docker-compose.example.yml) for the full template, and [`.env.example`](../.env.example) for the same variables in `.env` form with defaults and inline notes.

### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `GALACTILOG_DATABASE_URL` | `postgresql+asyncpg://galactilog:galactilog@postgres:5432/galactilog_catalog` | PostgreSQL connection string (async driver). Must match the postgres service credentials in docker-compose.yml. Only change if connecting to an external database. |
| `GALACTILOG_REDIS_URL` | `redis://redis:6379/0` | Redis connection string for task queue and caching. Default points to the redis container. Only change if using an external Redis instance. |
| `GALACTILOG_FITS_DATA_PATH` | `/app/data/fits` | Container-internal path where FITS files are mounted. Must match the volume mount target in docker-compose.yml. |
| `GALACTILOG_THUMBNAILS_PATH` | `/app/data/thumbnails` | Container-internal path for generated thumbnails. Must match the volume mount target in docker-compose.yml. |
| `GALACTILOG_THUMBNAIL_MAX_WIDTH` | `800` | Maximum thumbnail width in pixels. Larger values produce sharper thumbnails but use more disk space. |

### Volume Mounts

Default uses Docker named volumes; host path alternatives are commented out in the example compose file.

| Mount | Container Path | Description |
|-------|---------------|-------------|
| FITS data | `/app/data/fits` (read-only) | Your host directory containing FITS files. |
| Thumbnails | `/app/data/thumbnails` | Generated JPEG thumbnails. Grows over time. |
| PostgreSQL data | `/var/lib/postgresql/data` | Database storage. |

### Permissions and ownership

The container runs as a non-root `galactilog` user. Bind-mounted directories the container writes to must be owned by, or otherwise writable by, that user on the host.

| Container path | Access | Notes |
|---------------|--------|-------|
| `/app/data/fits` | read-only | FITS source tree. Read permission for the container user is sufficient. |
| `/app/data/thumbnails` | read-write | Generated JPEG thumbnails. Must be writable. |
| `/app/data/thumbnails/previews` | read-write | Larger preview renders. Must be writable. |

The `galactilog` user is remapped at entrypoint time to match the host ownership of these bind mounts. Use the following environment variables to control that behavior:

| Variable | Default | Description |
|----------|---------|-------------|
| `PUID` | `1000` | Host user ID the in-container `galactilog` user is remapped to. Set to match the host owner of the thumbnails directory. |
| `PGID` | `1000` | Host group ID the in-container `galactilog` user is remapped to. |
| `GALACTILOG_SKIP_CHOWN` | *(unset)* | Set to `1` to skip the first-boot recursive chown of `/app/data/thumbnails`. Use when ownership is already correct or when recursive chown is too slow. |

See the [Install Guide](INSTALL.md#running-as-non-root) for discovery commands and platform-specific values.

#### Troubleshooting 403 responses

A 403 on `/preview/...` or `/thumbnails/...` paths indicates the container user cannot read the files. On the host, confirm ownership of the thumbnails directory matches `PUID:PGID`:

```bash
stat -c '%u %g' /path/to/thumbnails
```

If the values do not match, either adjust `PUID` and `PGID` to the existing owner, or `chown -R` the directory to the configured UID/GID.

### PostgreSQL Settings

Set in the postgres service's `environment:` block. Must match `GALACTILOG_DATABASE_URL`.

| Postgres Variable | Default | Description |
|-------------------|---------|-------------|
| `POSTGRES_USER` | `galactilog` | Database username. |
| `POSTGRES_PASSWORD` | `galactilog` | Database password. |
| `POSTGRES_DB` | `galactilog_catalog` | Database name. |

The repository's own `docker-compose.yml` sets all three from `GALACTILOG_POSTGRES_USER`, `GALACTILOG_POSTGRES_PASSWORD`, and `GALACTILOG_POSTGRES_DB`, and substitutes the same values into `GALACTILOG_DATABASE_URL`, so setting them once in `.env` keeps the service and the connection string in agreement.

PostgreSQL applies these values only when it initializes an empty data directory. Changing them against an existing database has no effect; the data volume must be deleted first.

### Authentication Settings

See the [Security Guide](security.md) for full details on authentication, cookie security, roles, rate limiting, and audit logging.

| Variable | Default | Description | When to Change |
|----------|---------|-------------|----------------|
| `GALACTILOG_ADMIN_PASSWORD` | *(none)* | Admin account password, used when the account named by `GALACTILOG_ADMIN_USERNAME` does not exist yet. See [Account creation on every boot](#account-creation-on-every-boot). | Required for first-time setup. Must be 8+ characters. |
| `GALACTILOG_ADMIN_USERNAME` | `admin` | Username of the account created from `GALACTILOG_ADMIN_PASSWORD`. Changing it later creates a second admin rather than renaming the first. | Only if you want a different admin username, and only before the first boot. |
| `GALACTILOG_VIEWER_USERNAME` | *(none)* | Optional read-only viewer account username, created alongside admin. Requires `GALACTILOG_VIEWER_PASSWORD`. | When you want to share access without admin privileges (e.g., family members, club members viewing your data). |
| `GALACTILOG_VIEWER_PASSWORD` | *(none)* | Password for the viewer account. | Required if `GALACTILOG_VIEWER_USERNAME` is set. Must be 8+ characters. |
| `GALACTILOG_HTTPS` | `true` | Controls the Secure flag on auth cookies. When true, cookies are only sent over HTTPS. | Set to `false` if accessing GalactiLog over plain HTTP (e.g., `http://localhost`, LAN without TLS). |
| `GALACTILOG_JWT_SECRET` | *(auto-generated)* | Secret key for signing JWT access tokens (HS256). When not set, a random key is generated at startup, invalidating all sessions on restart. | Set to a long random string (`openssl rand -hex 32`) for persistent sessions across container restarts. |
| `GALACTILOG_ACCESS_TOKEN_EXPIRY` | `1800` (30 min) | Access token lifetime in seconds. | Shorter values are more secure but cause more frequent silent refreshes. Increase if users report being logged out mid-session. |
| `GALACTILOG_REFRESH_TOKEN_EXPIRY` | `604800` (7 days) | Refresh token lifetime in seconds. Users must re-login after this period of inactivity. | Increase for less frequent logins. Decrease for tighter security. |

#### Account creation on every boot

The account-creation step is not a first-start-only step. It runs on every container boot whenever `GALACTILOG_ADMIN_PASSWORD` or `GALACTILOG_VIEWER_PASSWORD` is set, and it matches on username:

- If a user row with that username already exists, the step skips it and changes nothing. An existing account's password, role, and active status are never overwritten from the environment, so editing `GALACTILOG_ADMIN_PASSWORD` after the first boot has no effect on the existing account.
- If no user row with that username exists, the account is created with the configured password and role. Changing `GALACTILOG_ADMIN_USERNAME` after the first boot therefore adds a second admin account on the next boot; the original admin remains.

Change credentials from **Settings > Account**, and remove an unwanted account from **Settings > Users**. Removing the environment variables afterwards is optional and changes nothing on its own.

### Metrics and Integrations

| Variable | Default | Description | When to Change |
|----------|---------|-------------|----------------|
| `GALACTILOG_METRICS_TOKEN` | *(none)* | Bearer token required by `GET /api/metrics`. When set, the request must carry `Authorization: Bearer <token>`; the scheme must be exactly `Bearer`, the token must be non-empty, and it is compared in constant time. Anything else returns 401. When unset, the endpoint requires no token. | Set when the metrics endpoint is reachable from beyond the nginx allowlist, or when you want scraper-level authentication regardless. See the [Monitoring Guide](MONITORING.md). |
| `GALACTILOG_INTEGRATION_ALLOWED_HOSTS` | *(none)* | Comma-separated allowlist of hostnames the N.I.N.A. and Stellarium integration endpoints may connect to. Entries are whitespace-trimmed and lowercased, and the URL host must equal one of them exactly. There is no wildcard, prefix, or suffix matching, and the port is not part of the comparison. A host not on the list is rejected with 400. When unset, any host is allowed except loopback, link-local, and cloud metadata addresses, which are blocked in all cases. | Set when you want to pin the integrations to specific capture machines, for example `nina-pc.lan,192.168.1.50`. |
| `GALACTILOG_CELERY_CONCURRENCY` | `4` | Number of concurrent Celery worker processes. | Raise on hosts with spare cores to shorten scans; lower to reduce memory use. |

### CORS (Development Only)

| Variable | Default | Description | When to Change |
|----------|---------|-------------|----------------|
| `GALACTILOG_CORS_ORIGINS` | *(none)* | Comma-separated list of allowed origins for CORS. Not needed in production (same-origin behind nginx). | Set to `http://localhost:3000` when running the frontend dev server separately from the backend. |

## Auto-Scan

Configure from **Settings > Library**:

- **Enable/Disable** -- Toggle automatic scanning
- **Scan Interval** -- 1 to 24 hours
- **Include Calibration Frames** -- Whether to ingest DARK, FLAT, and BIAS frames

Manual scans can be triggered from **Settings > Library**.

## PHD2 Guide Logs

Guide logs are collected during the normal library scan. Any file named `PHD2_GuideLog_*.txt` under the library path is parsed and catalogued; `PHD2_DebugLog_*` files are ignored.

Configure from **Settings > Library**:

- **Scan PHD2 guide logs** -- Toggles discovery of guide logs on disk. Turning it off leaves already-catalogued logs in place, and does not block corrections applied to stored guiding data (a profile re-key or a timezone re-parse).
- **Observer Timezone** -- The IANA zone name of the machine that runs PHD2, for example `America/New_York`. Set it under **Settings > Library > Observer Location**. PHD2 writes guide-log timestamps as local wall-clock with no zone marker, so this value decides what absolute time each guiding session is stored at. An empty value means "not configured". It does not fall back to the server's own zone, and nothing is guessed from it. Guiding from a profile that has neither its own timezone nor a global one is still parsed and catalogued, but it is never matched to any frame: reading wall-clock times in the wrong zone would attach guiding measured hours away to whichever exposures happened to overlap, so the correlation pass declines rather than fill. The scan reports that case in the activity feed as `phd2_correlation_timezone_unset` and names the profiles it skipped. Fill this in even when the capture PC runs in the same zone as the server. Saving a different value re-parses every catalogued guide log, so existing sessions are corrected too.
- **Observer Longitude** -- Required for guide sessions to be grouped by imaging night. See below.

Map PHD2 equipment profiles onto telescope names from **Settings > Equipment > PHD2 Profiles**. The mapping is applied to stored sessions by a background task; no re-scan is required.

### Per-Rig PHD2 Profile Settings

PHD2 records an equipment profile name in every guide log. Each profile gets its own row under **Settings > Equipment > PHD2 Profiles** with four fields:

- **Telescope** -- The telescope this profile's guiding belongs to. Leave it on "Not mapped" to leave the guiding unattributed.
- **Timezone** -- The zone this rig's guide logs are read in. Leave it empty to inherit the global Observer Timezone.
- **Latitude** and **Longitude** -- The site this rig stands at, in decimal degrees, east and north positive. Leave them empty to inherit the global Observer Location.

Empty is the only inherit marker for the coordinates. Zero is a real coordinate, not a blank: a longitude of `0` means the Greenwich meridian and a latitude of `0` means the equator, and both are stored and used exactly as entered. Clear the field to go back to inheriting.

Each row reads back what is actually in effect, for example "Reads guide logs in Central Time (America/Chicago), from Observer Location" and "Site: 30.27 deg N, 97.74 deg W". Use that line to confirm inheritance rather than assuming it.

Use the per-profile fields when:

- A rig sits at a remote or travel site in a different timezone or at a different longitude from the home observatory. The site longitude decides which imaging night a session lands on, so a rig several timezones away is grouped wrongly under the global value.
- The PC running PHD2 for one rig keeps a different clock from the machine used for the rest of the library, for example an ASIAIR set to the site's zone while the desktop stays on home time.

Leave them empty for every rig that runs at the global location on the global clock. Inheriting is the normal case and keeps one value to maintain.

### What Re-Reads Stored Guide Logs

Changing a timezone, global or per-profile, is what re-parses stored guide logs. Each save that changes a resolved zone queues one forced pass over every catalogued log, which re-parses, re-keys and re-correlates. On a typical library that pass takes one to three minutes and runs in the background.

Running a library scan does not re-read them. A guide log whose size and modification time are unchanged is short-circuited as already ingested, whatever state its stored rows are in, so a scan cannot recover logs that were stored wrongly or could not be parsed. If stored guiding needs re-reading and no setting genuinely needs to change, change a timezone to a different value, save, then change it back and save again. Each of those two saves queues a forced pass.

Longitude changes are cheaper: saving a longitude re-keys stored guide sessions onto the correct imaging night without re-parsing anything. A latitude change alone changes no stored value; it is used as evidence on the next pass that parses guide-log sections.

### Sidereal Mismatch Warning

Guide logs that record where the mount was pointing carry their own clock evidence. Right ascension plus hour angle is local sidereal time, which together with the site longitude fixes the UTC offset the log was really written at. When that disagrees with the configured timezone by more than half an hour, the scan raises `phd2_timezone_sidereal_mismatch` in the activity feed and names the profiles involved.

The warning changes nothing. The configured timezone is still what was used to read those logs; the pass reports the disagreement and leaves the data alone.

How strongly it is worded depends on what the profile has configured:

- The profile carries its own longitude. The comparison is against a known site, so the disagreement is stated as fact, usually with the UTC offset the pointing implies. The likely cause is a wrong timezone on the profile or a wrong clock on the mount. A longitude entered with the wrong sign looks exactly like a timezone error, so check both.
- The profile inherits its longitude from Observer Location. The arithmetic is the same, but the site is an assumption, so the message offers the alternatives: the timezone is wrong, the rig is not at the configured longitude, or the mount clock is wrong. Entering that rig's own longitude is what tells them apart.
- The profile has no longitude at all, globally or its own. The comparison is against the whole timezone's standard meridian, so only gross errors show up and the message says "probably wrong" rather than stating it. When the direction is unambiguous the message suggests the longitude the pointing implies.

A disagreement close to 12 hours cannot be resolved for direction from pointing alone, and the message says so instead of picking a side.

Acting on the warning does not re-run the check immediately. Entering a longitude re-keys sessions but parses nothing, and entering a latitude dispatches nothing at all, so the warning row stands until the next pass that parses guide-log sections, either the next scan that finds new or changed logs or a forced pass from a timezone change.

### Observer Location and Guiding Nights

Set **Observer Latitude** and **Observer Longitude** under **Settings > Library > Observer Location** if imaging-night grouping is enabled, which it is by default.

Imaging-night grouping puts a whole night's data on one date by cutting the day at local solar noon instead of UTC midnight. Images can work that out on their own, because each FITS file carries the site longitude in its `SITELONG` header. A PHD2 guide log carries no coordinates, so the observer longitude setting is the only source it has.

With the longitude unset, guide sessions fall back to grouping by UTC midnight while images keep grouping by solar noon. West of Greenwich an evening session then lands one day after the frames it belongs with, so the session card for that night shows no guiding data at all. The scan logs a warning when this happens, and the activity feed reports the guiding nights that fall a day off.

Filling in the longitude fixes existing data as well as new: saving it re-keys every stored guide session and calibration onto the correct night. No re-scan is needed.

### Scan Filters and Guide-Log Discovery

Guide logs are tested against the same include and exclude rules as image files. A file-target include rule narrows every file the scan sees, not only images, so a rule such as `include` / `file` / `*.fits` suppresses guide-log discovery completely: no `PHD2_GuideLog_*.txt` name can match it. The scan reports zero guide logs found and raises no error, which is the expected result of the rule rather than a fault.

To keep both, either restrict the library with folder-target rules and include paths instead of a file-target include rule, or add a second file-target include rule for `PHD2_GuideLog_*.txt`.

## Filter Aliases

Different equipment or N.I.N.A. profiles may record the same filter under different names (e.g. "Ha", "H-alpha", "Hydrogen Alpha"). Aliases map these variants to a single canonical name.

Configure from **Settings > Filters**: set canonical names, add aliases, choose colors, and pick a badge style. GalactiLog auto-discovers filter names and suggests groupings.

### Available Badge Styles

| Style | Description |
|-------|-------------|
| Solid | Colored background, dark text |
| Muted Backgrounds | Light colored background, colored text |
| Frosted Glass | Translucent glass-effect background |
| Outlined (Hollow) | Transparent background, colored border and text |
| Colored Text Only | Neutral background, colored text (default) |
| Indicator Dots | Neutral background with small colored dot |
| Underline Accents | Neutral background with colored bottom border |
| Subtle Tint & Border | Light tinted background with subtle colored border |
| Subtle Tint & Border (Bright) | Medium tinted background with colored border |

## Equipment Aliases

Same concept as filter aliases -- the same camera may appear in FITS headers as "ZWO ASI533MC Pro", "ASI533MC Pro", etc. Configure from **Settings > Equipment** to set canonical names and add aliases.

## Themes

GalactiLog includes 14 built-in themes. Select your theme from **Settings > Display**.

| Theme | Description |
|-------|-------------|
| **Nebula Cyan** | Holographic star-chart glassmorphism |
| **Obsidian** | Near-black neutral glass with ice blue accent |
| **Deep Space** | Frosted translucent glass panels |
| **Void** | Dark glass with muted slate and indigo depth |
| **Dark** | Modern dark theme |
| **Deep Neutral** | Ultra-dark pure graphite grey |
| **Slate Blue** | Deep slate with muted blue tint |
| **Warm Stone** | Dark graphite with earthy undertones |
| **Dune** | Dark desert glass with terracotta warmth |
| **Soft Zinc** | Matte studio-grade dark grey |
| **Smoke** | Translucent warm smoke glass with steel accent |
| **Twilight** | Mid-tone grey with cool undertones |
| **Silver Mist** | Soft silver with muted blue accent |
| **Daylight** | Clean light theme for daytime use |

The first three are glass themes with backdrop blur and gradient backgrounds.

### Text Size

Four text size presets are available:

| Size | Base Font |
|------|-----------|
| Small | 13px |
| Medium | 14px (default) |
| Large | 16px |
| Extra Large | 18px |

## Display Settings

Toggle metric visibility from **Settings > Display**. Each group can be toggled as a whole or per-metric:

| Group | Metrics |
|-------|---------|
| **Quality** | HFR, HFR Stdev, FWHM, Eccentricity, Detected Stars |
| **Guiding** | Guiding RMS Total, Guiding RMS RA, Guiding RMS Dec |
| **ADU** | ADU Mean, ADU Median, ADU Stdev, ADU Min, ADU Max |
| **Focuser** | Focuser Position, Focuser Temperature |
| **Weather** | Ambient Temperature, Humidity, Dew Point, Pressure, Wind Speed, Wind Direction, Wind Gust, Cloud Cover, Sky Quality |
| **Mount** | Airmass, Pier Side, Rotator Position |

## Target Merging

After each scan, GalactiLog compares unresolved object names against resolved target aliases using trigram similarity. Names scoring above 0.4 are flagged as merge candidates.

Manage from **Settings > Target Merges**: review candidates, accept or dismiss merges, unmerge, or manually trigger detection. Merged targets are soft-deleted and can be restored.
