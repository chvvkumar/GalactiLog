<p align="center">
  <img src="images/logo-transparent.png" alt="GalactiLog" width="300">
</p>

<h3 align="center">Astrophotography FITS file catalog and session browser</h3>

<p align="center">
  Self-hosted web application that automatically ingests N.I.N.A. imaging sessions, resolves targets via SIMBAD, and provides detailed analytics for your astrophotography data.
</p>

---

## Features

### Automatic Ingestion
- Scans directories for FITS files and extracts metadata from headers
- Backfills extended metrics from N.I.N.A. CSV session logs (HFR, FWHM, detected stars, guiding RMS, ADU statistics)
- Configurable auto-scan scheduler with adjustable intervals
- Supports LIGHT, DARK, FLAT, and BIAS frame types

### Target Resolution
- Resolves object names to canonical designations via the SIMBAD astronomical database
- Maintains aliases, catalog IDs (Messier, NGC, IC, Caldwell, Sharpless, etc.), and common names
- Detects potential duplicate targets using trigram similarity scoring
- Merge and unmerge targets with full history tracking

### Image Processing
- Generates JPEG thumbnails from raw FITS data using MTF (Midtones Transfer Function) auto-stretch
- Stretch algorithm matches N.I.N.A. and PixInsight Auto STF output
- Per-channel processing with median/MAD-based shadow clipping and midtone balancing

### Session Analytics
- Per-session quality metrics: HFR, FWHM, eccentricity, detected stars, guiding RMS (total, RA, Dec)
- Environmental monitoring: ambient temperature, humidity, dew point, pressure, wind speed, cloud cover, sky quality
- Equipment tracking: sensor temperature, gain, focuser position/temperature, rotator position, pier side, airmass
- ADU statistics: mean, median, standard deviation, min, max
- Session insights with quality warnings and indicators

### Statistics Dashboard
- Total integration time, frame counts, and target summaries
- Filter usage distribution with per-filter integration hours
- Equipment inventory with frame counts per camera and telescope
- Monthly imaging timeline trends
- Storage breakdown across FITS data, thumbnails, and database
- Ingest history tracking

### Advanced Filtering
- Fuzzy target search with similarity scoring and alias matching
- Object type toggles (Galaxy, Emission Nebula, Planetary Nebula, Open Cluster, etc.)
- Date range filtering
- Optical filter selection (Ha, OIII, SII, L, R, G, B, and custom filters)
- Equipment filtering by camera and telescope
- Quality metric ranges (HFR, FWHM, eccentricity, detected stars, guiding RMS)
- Environmental metric ranges (ambient temperature, humidity, airmass)
- Raw FITS header query builder with operators (=, !=, >, <, contains, etc.)

### Customization
- 5 built-in themes: Default Dark, Nebula Glass, Aurora Glass, Nebula Cyan, Stellar Glass
- 9 filter badge display styles (solid, muted, outlined, text-only, indicator dots, and more)
- 4 text size presets
- Per-group metric visibility toggles (Quality, Guiding, ADU, Focuser, Weather, Mount)
- Filter and equipment name aliasing with color customization

## Screenshot

<p align="center">
  <img src="images/screenshots/dashboard.png" alt="GalactiLog Dashboard" width="100%">
</p>

## Requirements

- **Docker** and **Docker Compose v2**
- **N.I.N.A.** (Nighttime Imaging 'N' Astronomy) for FITS file generation
- FITS files from N.I.N.A. imaging sessions
- Network access to [SIMBAD](https://simbad.cds.unistra.fr/) for target resolution (first-time only per target; results are cached locally)

## N.I.N.A. Dependencies

GalactiLog reads data produced by N.I.N.A. and its plugins. The table below lists what feeds into GalactiLog and what metrics it enables.

| Source | Required | Metrics Provided |
|--------|----------|-----------------|
| **N.I.N.A. Core** (FITS output) | Yes | Object name, exposure time, filter, camera, telescope, gain, sensor temp, capture date, image type |
| **FITS Headers** (HFR, FWHM) | No | Median HFR, FWHM, eccentricity (when written by N.I.N.A. to FITS headers) |
| **ImageMetaData.csv** | No | HFR stdev, FWHM, detected stars, guiding RMS (total/RA/Dec), ADU stats, focuser position/temp, rotator, pier side, airmass |
| **WeatherData.csv** | No | Ambient temperature, humidity, dew point, pressure, wind speed/direction/gust, cloud cover, sky quality |
| **Guiding Plugin** (PHD2, internal) | No | Guiding RMS data written to ImageMetaData.csv |
| **Weather Plugin** (OpenWeatherMap, station hardware) | No | Weather data written to WeatherData.csv |

See [N.I.N.A. Setup Guide](guides/NINA-SETUP.md) for detailed configuration instructions.

## Quickstart

### Using pre-built images (recommended)

```bash
# 1. Clone the repository (for docker-compose.yml and config files)
git clone https://github.com/chvvkumar/GalactiLog.git
cd GalactiLog

# 2. Run the setup script
bash setup.sh

# 3. Open the web UI
# Default: http://localhost:8080
```

The setup script pulls the latest image from [DockerHub](https://hub.docker.com/r/chvvkumar/galactilog), initializes the database, and starts all services. It expects your FITS files at `/astro_incoming` by default.

### Updating

```bash
cd GalactiLog
docker compose pull app
docker compose up -d
```

### Using a specific version

Pin to a specific release or pre-release tag in your `.env` or `docker-compose.yml`:

```yaml
# Stable release
image: chvvkumar/galactilog:1.0.0

# Pre-release (release candidate)
image: chvvkumar/galactilog:1.0.0-rc.1

# Latest stable (default)
image: chvvkumar/galactilog:latest

# Latest dev build
image: chvvkumar/galactilog:dev
```

For manual installation, custom paths, or building from source, see the [Install Guide](guides/INSTALL.md).

## Guides

- [Install Guide](guides/INSTALL.md) -- Installation, updating, uninstalling, and troubleshooting
- [N.I.N.A. Setup Guide](guides/NINA-SETUP.md) -- Configuring N.I.N.A. for use with GalactiLog
- [Configuration Guide](guides/CONFIGURATION.md) -- Environment variables, themes, filter/equipment aliases, and display settings

## CI/CD

GalactiLog uses GitHub Actions with a self-hosted runner for automated builds and releases.

| Workflow | Trigger | Action |
|----------|---------|--------|
| **Build & Push** | Merge to `dev` | Builds Docker image, pushes to DockerHub with pre-release tag (`1.0.0-rc.N`) and `dev` tag |
| **Build & Push** | Merge to `main` | Builds Docker image, pushes to DockerHub with release tag (`1.0.N`) and `latest` tag |
| **PR Description** | PR opened | Generates PR title and description using Gemini AI |
| **Release Notes** | Tag pushed | Creates GitHub Release with AI-generated release notes |

### Branch strategy

```
snd  -->  dev (pre-release builds)  -->  main (stable releases)
```

- `snd` -> `dev`: creates a pre-release Docker image and GitHub pre-release
- `dev` -> `main`: creates a stable Docker image and GitHub release
- Version tags are auto-incremented (patch for releases, rc number for pre-releases)

### Docker images

All images are published to [DockerHub](https://hub.docker.com/r/chvvkumar/galactilog):

| Tag | Description |
|-----|-------------|
| `latest` | Latest stable release |
| `dev` | Latest pre-release build from `dev` branch |
| `X.Y.Z` | Specific stable release (e.g., `1.0.0`) |
| `X.Y.Z-rc.N` | Specific pre-release (e.g., `1.0.0-rc.1`) |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | SolidJS, TypeScript, Tailwind CSS v4, Chart.js, Vite |
| Backend | FastAPI, SQLAlchemy 2.0 (async), asyncpg, PostgreSQL 16 |
| Task Queue | Celery, Redis |
| Infrastructure | Docker Compose, Nginx, Supervisor |

## License

This project is for personal use.
