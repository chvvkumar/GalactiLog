# Configuration Guide

## Environment Variables

All application environment variables use the `ASTRO_` prefix. These are set in the `.env` file in the project root.

### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ASTRO_DATABASE_URL` | `postgresql+asyncpg://astro:astro@postgres:5432/astro_catalog` | PostgreSQL connection string (async driver) |
| `ASTRO_REDIS_URL` | `redis://redis:6379/0` | Redis connection string for task queue and caching |
| `ASTRO_FITS_DATA_PATH` | `/app/data/fits` | Path to FITS files inside the container |
| `ASTRO_THUMBNAILS_PATH` | `/app/data/thumbnails` | Path for generated thumbnails inside the container |
| `ASTRO_THUMBNAIL_MAX_WIDTH` | `800` | Maximum thumbnail width in pixels |

### Docker Compose Host Paths

These variables map host directories into the container:

| Variable | Description |
|----------|-------------|
| `FITS_DATA_HOST_PATH` | Host directory containing FITS files (mounted read-only) |
| `THUMBNAILS_HOST_PATH` | Host directory for thumbnail storage (read-write) |
| `POSTGRES_DATA_HOST_PATH` | Host directory for PostgreSQL data persistence |

### PostgreSQL Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_USER` | `astro` | Database username |
| `POSTGRES_PASSWORD` | `astro` | Database password |
| `POSTGRES_DB` | `astro_catalog` | Database name |

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
