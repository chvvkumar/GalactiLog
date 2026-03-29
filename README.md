<p align="center">
  <img src="images\logo-small.png" alt="GalactiLog" width="300">
</p>

<h3 align="center">Astrophotography FITS file catalog and session browser</h3>

<p align="center">
  Self-hosted web application that automatically ingests N.I.N.A. imaging sessions, resolves targets via SIMBAD, and provides detailed analytics for your astrophotography data.
</p>

<table align="center">
  <tr>
    <th></th>
    <th>main (stable)</th>
    <th>dev (pre-release)</th>
  </tr>
  <tr>
    <td><strong>Build</strong></td>
    <td><a href="https://github.com/chvvkumar/GalactiLog/actions/workflows/build-deploy.yml?query=branch%3Amain"><img src="https://github.com/chvvkumar/GalactiLog/actions/workflows/build-deploy.yml/badge.svg?branch=main" alt="main build"></a></td>
    <td><a href="https://github.com/chvvkumar/GalactiLog/actions/workflows/build-deploy.yml?query=branch%3Adev"><img src="https://github.com/chvvkumar/GalactiLog/actions/workflows/build-deploy.yml/badge.svg?branch=dev" alt="dev build"></a></td>
  </tr>
  <tr>
    <td><strong>Release</strong></td>
    <td><a href="https://github.com/chvvkumar/GalactiLog/releases/latest"><img src="https://img.shields.io/github/v/release/chvvkumar/GalactiLog?label=release" alt="Latest Release"></a></td>
    <td><a href="https://github.com/chvvkumar/GalactiLog/releases"><img src="https://img.shields.io/github/v/release/chvvkumar/GalactiLog?include_prereleases&label=pre-release" alt="Pre-release"></a></td>
  </tr>
  <tr>
    <td><strong>Docker Tag</strong></td>
    <td><a href="https://hub.docker.com/r/chvvkumar/galactilog"><img src="https://img.shields.io/docker/v/chvvkumar/galactilog/latest?label=latest" alt="Docker latest"></a></td>
    <td><a href="https://hub.docker.com/r/chvvkumar/galactilog"><img src="https://img.shields.io/docker/v/chvvkumar/galactilog/dev?label=dev" alt="Docker dev"></a></td>
  </tr>
  <tr>
    <td><strong>Image Size</strong></td>
    <td><a href="https://hub.docker.com/r/chvvkumar/galactilog"><img src="https://img.shields.io/docker/image-size/chvvkumar/galactilog/latest?label=size" alt="Docker Image Size (latest)"></a></td>
    <td><a href="https://hub.docker.com/r/chvvkumar/galactilog"><img src="https://img.shields.io/docker/image-size/chvvkumar/galactilog/dev?label=size" alt="Docker Image Size (dev)"></a></td>
  </tr>
</table>

<p align="center">
  <a href="https://hub.docker.com/r/chvvkumar/galactilog"><img src="https://img.shields.io/docker/pulls/chvvkumar/galactilog" alt="Docker Pulls"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/SolidJS-335d92?logo=solid&logoColor=white" alt="SolidJS">
  <img src="https://img.shields.io/badge/TypeScript-3178c6?logo=typescript&logoColor=white" alt="TypeScript">
  <img src="https://img.shields.io/badge/Tailwind_CSS-06b6d4?logo=tailwindcss&logoColor=white" alt="Tailwind CSS">
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/PostgreSQL-4169e1?logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Redis-dc382d?logo=redis&logoColor=white" alt="Redis">
  <img src="https://img.shields.io/badge/Docker-2496ed?logo=docker&logoColor=white" alt="Docker">
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
  
  <img src="images/screenshots/Statistics.png" alt="GalactiLog Statistics" width="100%">
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
| **[Session Metadata](https://github.com/tcpalmer/nina.plugin.sessionmetadata) plugin** | No | Per-frame CSV files with extended metrics (see below) |
| **Guiding Plugin** (PHD2, internal) | No | Guiding RMS data captured by Session Metadata plugin |
| **Weather source** (OpenWeatherMap, ASCOM station, etc.) | No | Weather data captured by Session Metadata plugin |

The **Session Metadata** plugin for N.I.N.A. generates the CSV files that GalactiLog uses for extended analytics:

| CSV File | Metrics |
|----------|---------|
| `ImageMetaData.csv` | HFR, HFR stdev, FWHM, eccentricity, detected stars, guiding RMS (total/RA/Dec), ADU stats (mean/median/stdev/min/max), focuser position/temp, rotator position, pier side, airmass |
| `WeatherData.csv` | Ambient temperature, humidity, dew point, pressure, wind speed/direction/gust, cloud cover, sky quality/brightness/temperature |

See [N.I.N.A. Setup Guide](guides/NINA-SETUP.md) for detailed configuration instructions.

## Quickstart

### Using pre-built images (recommended)

```bash
# 1. Clone the repository (for config files)
git clone https://github.com/chvvkumar/GalactiLog.git
cd GalactiLog

# 2. Copy the example files and edit for your system
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
# Edit .env to set your FITS, thumbnails, and database paths

# 3. Run the setup script
bash setup.sh

# 4. Open the web UI
# Default: http://localhost:8080
```

See [`.env.example`](.env.example) and [`docker-compose.example.yml`](docker-compose.example.yml) for all available configuration options.

The setup script pulls the latest image from [DockerHub](https://hub.docker.com/r/chvvkumar/galactilog), initializes the database, and starts all services.

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

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | SolidJS, TypeScript, Tailwind CSS v4, Chart.js, Vite |
| Backend | FastAPI, SQLAlchemy 2.0 (async), asyncpg, PostgreSQL 16 |
| Task Queue | Celery, Redis |
| Infrastructure | Docker Compose, Nginx, Supervisor |

## License

This project is for personal use.
