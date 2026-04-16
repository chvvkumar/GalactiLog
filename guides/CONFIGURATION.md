# Configuration Guide

## Environment Variables

All configuration is done via `GALACTILOG_*` environment variables in `docker-compose.yml`. See [`docker-compose.example.yml`](../docker-compose.example.yml) for the full template.

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

### Authentication Settings

See the [Security Guide](security.md) for full details on authentication, cookie security, roles, rate limiting, and audit logging.

| Variable | Default | Description | When to Change |
|----------|---------|-------------|----------------|
| `GALACTILOG_ADMIN_PASSWORD` | *(none)* | Admin account password. On first start, if no users exist, an admin is auto-created with this password. Ignored once any user exists. | Required for first-time setup. Must be 8+ characters. |
| `GALACTILOG_ADMIN_USERNAME` | `admin` | Username for the auto-created admin account. | Only if you want a different admin username. |
| `GALACTILOG_VIEWER_USERNAME` | *(none)* | Optional read-only viewer account username, created on first start alongside admin. | When you want to share access without admin privileges (e.g., family members, club members viewing your data). |
| `GALACTILOG_VIEWER_PASSWORD` | *(none)* | Password for the viewer account. | Required if `GALACTILOG_VIEWER_USERNAME` is set. Must be 8+ characters. |
| `GALACTILOG_HTTPS` | `true` | Controls the Secure flag on auth cookies. When true, cookies are only sent over HTTPS. | Set to `false` if accessing GalactiLog over plain HTTP (e.g., `http://localhost`, LAN without TLS). |
| `GALACTILOG_JWT_SECRET` | *(auto-generated)* | Secret key for signing JWT access tokens (HS256). When not set, a random key is generated at startup, invalidating all sessions on restart. | Set to a long random string (`openssl rand -hex 32`) for persistent sessions across container restarts. |
| `GALACTILOG_ACCESS_TOKEN_EXPIRY` | `1800` (30 min) | Access token lifetime in seconds. | Shorter values are more secure but cause more frequent silent refreshes. Increase if users report being logged out mid-session. |
| `GALACTILOG_REFRESH_TOKEN_EXPIRY` | `604800` (7 days) | Refresh token lifetime in seconds. Users must re-login after this period of inactivity. | Increase for less frequent logins. Decrease for tighter security. |

### CORS (Development Only)

| Variable | Default | Description | When to Change |
|----------|---------|-------------|----------------|
| `GALACTILOG_CORS_ORIGINS` | *(none)* | Comma-separated list of allowed origins for CORS. Not needed in production (same-origin behind nginx). | Set to `http://localhost:3000` when running the frontend dev server separately from the backend. |

## Auto-Scan

Configure from **Settings > General**:

- **Enable/Disable** -- Toggle automatic scanning
- **Scan Interval** -- 1 to 24 hours
- **Include Calibration Frames** -- Whether to ingest DARK, FLAT, and BIAS frames

Manual scans can be triggered from **Settings > Library**.

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

GalactiLog includes 11 built-in themes. Select your theme from **Settings > Display**.

| Theme | Description |
|-------|-------------|
| **Nebula Cyan** | Holographic star-chart glassmorphism |
| **Deep Space** | Frosted translucent glass panels |
| **Void** | Dark glass with muted slate and indigo depth |
| **Dark** | Modern dark theme |
| **Deep Neutral** | Ultra-dark pure graphite grey |
| **Slate Blue** | Deep slate with muted blue tint |
| **Warm Stone** | Dark graphite with earthy undertones |
| **Soft Zinc** | Matte studio-grade dark grey |
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
