# Configuration Guide

## How Configuration Works

GalactiLog uses two configuration files in the project root:

- **`.env`** -- Defines all your settings: credentials, host paths, and application options.
- **`docker-compose.yml`** -- Defines the services (postgres, redis, app) and references `.env` variables for volume mounts and service configuration.

### Variable Flow

```
.env  ──→  docker-compose.yml (${VAR:-default} substitution for volumes, ports, credentials)
  │
  └──→  app container (env_file: .env passes all variables into the container)
              │
              └──→  environment: block overrides specific variables with
                    container-internal values (e.g., database hostname = "postgres")
```

Docker Compose loads `.env` automatically from the same directory. The `env_file: .env` directive on the app service passes every variable from `.env` into the container. The `environment:` block in docker-compose.yml overrides specific variables (like `ASTRO_DATABASE_URL`) with container-aware values -- for example, using `postgres` (the Docker service name) as the database hostname instead of `localhost`.

Variables in docker-compose.yml use `${VAR:-default}` syntax. If the variable is set in `.env`, that value is used. If not, the default after `:-` applies. This means you can run GalactiLog with minimal configuration -- only the host paths and admin password are strictly required.

## Environment Variables

All application environment variables use the `ASTRO_` prefix. These are set in the `.env` file in the project root.

### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ASTRO_DATABASE_URL` | `postgresql+asyncpg://astro:astro@postgres:5432/astro_catalog` | PostgreSQL connection string (async driver). Normally built from POSTGRES_USER/PASSWORD/DB in docker-compose.yml. Only set this directly if connecting to an external database. |
| `ASTRO_REDIS_URL` | `redis://redis:6379/0` | Redis connection string for task queue and caching. Default points to the redis container. Only change if using an external Redis instance. |
| `ASTRO_FITS_DATA_PATH` | `/app/data/fits` | Container-internal path where FITS files are mounted. Must match the volume mount target in docker-compose.yml. |
| `ASTRO_THUMBNAILS_PATH` | `/app/data/thumbnails` | Container-internal path for generated thumbnails. Must match the volume mount target in docker-compose.yml. |
| `ASTRO_THUMBNAIL_MAX_WIDTH` | `800` | Maximum thumbnail width in pixels. Larger values produce sharper thumbnails but use more disk space. |

### Docker Compose Host Paths

These variables map directories on your host machine into the Docker containers. They are referenced in docker-compose.yml via `${VAR:-fallback}` syntax. When not set, Docker named volumes are used as fallbacks (fine for testing, not recommended for production).

| Variable | Fallback | Description |
|----------|----------|-------------|
| `FITS_DATA_HOST_PATH` | `./sample_fits` | Host directory containing your FITS files. Mounted read-only into the container. Use an absolute path to your imaging data (e.g., `/mnt/nas/astrophotography`). |
| `THUMBNAILS_HOST_PATH` | `thumbnails_data` (named volume) | Host directory for thumbnail storage. GalactiLog creates JPEG thumbnails during ingest -- this directory grows over time. Set a host path for easy access and backups. |
| `POSTGRES_DATA_HOST_PATH` | `postgres_data` (named volume) | Host directory for PostgreSQL data persistence. Set this to persist the database in a known location for backups. Without it, data lives in a Docker named volume. |

### PostgreSQL Settings

These configure both the postgres container (which creates the database on first start) and are interpolated into the `ASTRO_DATABASE_URL` connection string in docker-compose.yml. They must stay in sync.

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_USER` | `astro` | Database username. |
| `POSTGRES_PASSWORD` | `astro` | Database password. Change this for any network-exposed deployment. |
| `POSTGRES_DB` | `astro_catalog` | Database name. |

### Authentication Settings

See the [Security Guide](security.md) for full details on authentication, cookie security, roles, rate limiting, and audit logging.

| Variable | Default | Description | When to Change |
|----------|---------|-------------|----------------|
| `ASTRO_ADMIN_PASSWORD` | *(none)* | Admin account password. On first start, if no users exist, an admin is auto-created with this password. Ignored once any user exists. | Required for first-time setup. Must be 12+ characters. |
| `ASTRO_ADMIN_USERNAME` | `admin` | Username for the auto-created admin account. | Only if you want a different admin username. |
| `ASTRO_VIEWER_USERNAME` | *(none)* | Optional read-only viewer account username, created on first start alongside admin. | When you want to share access without admin privileges (e.g., family members, club members viewing your data). |
| `ASTRO_VIEWER_PASSWORD` | *(none)* | Password for the viewer account. | Required if ASTRO_VIEWER_USERNAME is set. Must be 12+ characters. |
| `ASTRO_HTTPS` | `true` | Controls the Secure flag on auth cookies. When true, cookies are only sent over HTTPS. | Set to `false` if accessing GalactiLog over plain HTTP (e.g., `http://localhost`, LAN without TLS). |
| `ASTRO_JWT_SECRET` | *(auto-generated)* | Secret key for signing JWT access tokens (HS256). When not set, a random key is generated at startup, invalidating all sessions on restart. | Set to a long random string (`openssl rand -hex 32`) for persistent sessions across container restarts. |
| `ASTRO_ACCESS_TOKEN_EXPIRY` | `1800` (30 min) | Access token lifetime in seconds. | Shorter values are more secure but cause more frequent silent refreshes. Increase if users report being logged out mid-session. |
| `ASTRO_REFRESH_TOKEN_EXPIRY` | `604800` (7 days) | Refresh token lifetime in seconds. Users must re-login after this period of inactivity. | Increase for less frequent logins. Decrease for tighter security. |

### CORS (Development Only)

| Variable | Default | Description | When to Change |
|----------|---------|-------------|----------------|
| `ASTRO_CORS_ORIGINS` | *(none)* | Comma-separated list of allowed origins for CORS. Not needed in production (same-origin behind nginx). | Set to `http://localhost:3000` when running the frontend dev server separately from the backend. |

## Auto-Scan

GalactiLog can automatically scan your FITS directory for new files on a schedule.

Configure auto-scan from the **Settings > General** tab in the web UI:

- **Enable/Disable** -- Toggle automatic scanning on or off
- **Scan Interval** -- How often to check for new files (1 hour to 24 hours)
- **Include Calibration Frames** -- Whether to ingest DARK, FLAT, and BIAS frames

The auto-scan scheduler runs via Celery Beat, which checks every 60 seconds whether a scan is due based on your configured interval.

You can also trigger a manual scan at any time from **Settings > Scan & Ingest**.

## Filter Aliases

GalactiLog lets you normalize filter names and assign colors for consistent display across your data.

### Why Use Aliases

Different equipment or N.I.N.A. profiles may record the same filter under different names. For example:
- "Ha", "H-alpha", "Hydrogen Alpha" all refer to the same filter
- "L", "Lum", "Luminance" are all the luminance filter

Aliases map these variants to a single canonical name.

### Configuring Filters

Navigate to **Settings > Filters** to:

1. **Set canonical names** -- The display name used throughout the UI
2. **Add aliases** -- Raw filter names from FITS headers that should map to this filter
3. **Choose colors** -- Pick a color for each filter (used in badges, charts, and palette displays)
4. **Set badge style** -- Choose from 9 display styles for filter badges

GalactiLog auto-discovers filter names from your data and suggests groupings. Check the suggestions banner at the top of the Filters settings tab.

### Available Badge Styles

| Style | Description |
|-------|-------------|
| Solid | Colored background, dark text |
| Muted | Light colored background, colored text |
| Muted Bright | Medium colored background, dark text |
| Outlined | Transparent background, colored border and text |
| Text Only | Neutral background, colored text |
| Indicator Dots | Neutral background with small colored dot |
| Underline | Neutral background with colored bottom border |
| Tint Border | Light tinted background with subtle colored border |
| Tint Border Bright | Medium tinted background with colored border |

## Equipment Aliases

Similar to filter aliases, equipment aliases normalize camera and telescope names.

### Why Use Aliases

The same camera may appear in FITS headers as:
- "ZWO ASI533MC Pro", "ASI533MC Pro", "ZWO ASI533MC"

Equipment aliases map all variants to one canonical name for clean display and accurate grouping.

### Configuring Equipment

Navigate to **Settings > Equipment** to:

1. Set canonical names for cameras and telescopes
2. Add aliases for each piece of equipment
3. Review auto-discovered equipment suggestions

## Themes

GalactiLog includes 5 built-in themes. Select your theme from **Settings > Display**.

| Theme | Description |
|-------|-------------|
| **Default Dark** | Clean dark theme with indigo accents |
| **Nebula Glass** | Purple/violet glassmorphism with holographic deep-space aesthetic |
| **Aurora Glass** | Green/teal glassmorphism inspired by northern lights |
| **Nebula Cyan** | Cyan/blue glassmorphism with a holographic star-chart feel |
| **Stellar Glass** | Warm orange/gold glassmorphism with cosmic tones |

Glass themes use backdrop blur and gradient backgrounds for a frosted-glass appearance.

### Text Size

Four text size presets are available:

| Size | Base Font |
|------|-----------|
| Small | 13px |
| Medium | 14px (default) |
| Large | 16px |
| X-Large | 18px |

## Display Settings

Control which metric groups and individual fields appear in session views and charts.

Navigate to **Settings > Display** to toggle visibility for:

| Group | Metrics |
|-------|---------|
| **Quality** | HFR, HFR Stdev, FWHM, Eccentricity, Detected Stars |
| **Guiding** | Guiding RMS Total, Guiding RMS RA, Guiding RMS Dec |
| **ADU** | ADU Mean, ADU Median, ADU Stdev, ADU Min, ADU Max |
| **Focuser** | Focuser Position, Focuser Temperature |
| **Weather** | Ambient Temperature, Humidity, Dew Point, Pressure, Wind Speed, Wind Direction, Wind Gust, Cloud Cover, Sky Quality |
| **Mount** | Airmass, Pier Side, Rotator Position |

Each group can be toggled as a whole, or individual metrics within a group can be enabled or disabled.

## Target Merging

GalactiLog includes automatic duplicate detection for astronomical targets.

### How It Works

After each scan, GalactiLog runs a duplicate detection pass:

1. Collects all unresolved object names (names not yet linked to a resolved target)
2. Compares each name against all resolved target aliases using trigram similarity
3. Names with a similarity score above 0.4 are flagged as merge candidates

### Managing Merges

Navigate to **Settings > Target Merges** to:

- **Review merge candidates** -- See suggested matches with similarity scores
- **Accept a merge** -- Combine two targets into one, transferring all images to the winner
- **Dismiss a candidate** -- Hide a suggestion you've reviewed and rejected
- **Unmerge** -- Restore a previously merged target (soft-deleted targets are recoverable)
- **Trigger detection** -- Manually run the duplicate detection algorithm

Merged targets are soft-deleted (not permanently removed), so they can always be restored.
