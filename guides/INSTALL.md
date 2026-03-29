# Install Guide

## Prerequisites

- **Docker** (20.10+) and **Docker Compose v2** (`docker compose` command)
- **Git** for cloning the repository
- Network access to [SIMBAD](https://simbad.cds.unistra.fr/) (used for target name resolution; results are cached locally after first lookup)
- A directory containing your FITS files from N.I.N.A. imaging sessions

## Quick Install (Linux)

The included setup script automates the full installation:

```bash
git clone https://github.com/chvvkumar/GalactiLog.git
cd GalactiLog
bash setup.sh
```

The script will:
1. Verify Docker and Docker Compose are installed and running
2. Create data directories for thumbnails and the database
3. Generate the `.env` configuration file
4. Pull the latest Docker image from [DockerHub](https://hub.docker.com/r/chvvkumar/galactilog)
5. Start PostgreSQL and Redis, wait for health checks
6. Initialize the database schema
7. Start the application on port 8080

Default paths used by setup.sh:
- FITS files: `/astro_incoming`
- Thumbnails: `/docker/astro_cataloger/thumbnails`
- Database: `/docker/astro_cataloger/postgres`

Once complete, open `http://localhost:8080` and trigger your first scan from the Settings page.

## Manual Install

Use manual installation if you need custom paths or are on Windows/Mac.

### 1. Clone the Repository

```bash
git clone https://github.com/chvvkumar/GalactiLog.git
cd GalactiLog
```

### 2. Create Configuration Files

Copy the example files and edit for your system:

```bash
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
```

Edit `.env` with your paths (see [`.env.example`](../.env.example) for all options):

### 3. Configure Host Paths

Update the three `*_HOST_PATH` variables in `.env`:

| Variable | Description | Notes |
|----------|-------------|-------|
| `FITS_DATA_HOST_PATH` | Directory containing your FITS files | Mounted read-only in the container. Can be a nested directory structure; GalactiLog scans recursively. |
| `THUMBNAILS_HOST_PATH` | Where generated JPEG thumbnails are stored | Created automatically. Needs read/write access. |
| `POSTGRES_DATA_HOST_PATH` | PostgreSQL data directory | Created automatically. Persists your database across container restarts. |

**Windows (local paths):**
```
FITS_DATA_HOST_PATH=D:/Astrophotography/Data
THUMBNAILS_HOST_PATH=D:/GalactiLog/thumbnails
POSTGRES_DATA_HOST_PATH=D:/GalactiLog/postgres
```

**Linux (local paths):**
```
FITS_DATA_HOST_PATH=/home/user/astro/data
THUMBNAILS_HOST_PATH=/home/user/galactilog/thumbnails
POSTGRES_DATA_HOST_PATH=/home/user/galactilog/postgres
```

**Linux (NFS mount):**

If your FITS files are on a NAS or network share, mount the NFS export on the host first, then point `FITS_DATA_HOST_PATH` to the mount point:

```bash
# Mount the NFS share (add to /etc/fstab for persistence)
sudo mkdir -p /mnt/astro
sudo mount -t nfs nas.local:/volume1/astrophotography /mnt/astro
```

```
FITS_DATA_HOST_PATH=/mnt/astro
```

The FITS directory is mounted read-only into the container, so GalactiLog will never modify your source files. To make the NFS mount persistent across reboots, add it to `/etc/fstab`:

```
nas.local:/volume1/astrophotography  /mnt/astro  nfs  ro,soft,timeo=30  0  0
```

**Windows (network share):**

Map the network share to a drive letter or use the UNC path directly:

```
# Mapped drive
FITS_DATA_HOST_PATH=Z:/Astrophotography

# UNC path (use forward slashes)
FITS_DATA_HOST_PATH=//NAS/Astrophotography
```

### 4. Pull and Start

```bash
# Pull the latest image and start all services
docker compose up -d

# Watch the logs during first startup
docker compose logs -f app
```

The image is pulled from [DockerHub](https://hub.docker.com/r/chvvkumar/galactilog). To build from source instead, use `docker compose up -d --build`.

### 5. Initialize the Database

On first run, the application creates database tables automatically via its startup hook. Stamp Alembic to mark the schema as current:

```bash
docker compose run --rm app alembic stamp head
```

### 6. Verify

Open `http://localhost:8080` in your browser. You should see the GalactiLog dashboard.

To verify the backend is responding:

```bash
curl http://localhost:8080/api/scan/status
# Expected: {"state":"idle","total":0,"completed":0,"failed":0,"failed_files":[]}
```

### 7. Trigger Your First Scan

Navigate to **Settings > Scan & Ingest** in the web UI and click **Start Scan**. GalactiLog will:

1. Discover all FITS files in your configured directory
2. Extract metadata from FITS headers
3. Generate stretched JPEG thumbnails
4. Resolve target names via SIMBAD (with local caching)
5. Backfill additional metrics from any N.I.N.A. CSV files found alongside the FITS files

Progress is shown in real-time on the Settings page.

## Architecture

GalactiLog runs as a single Docker container managed by Supervisor, with PostgreSQL and Redis as separate containers:

```
Docker Compose
├── postgres (PostgreSQL 16)
├── redis (Redis 7)
└── app
    └── Supervisor
        ├── nginx (port 80 → exposed as 8080)
        │   ├── / → SolidJS SPA
        │   ├── /api → FastAPI (port 8000)
        │   └── /thumbnails → FastAPI (port 8000)
        ├── uvicorn (FastAPI on port 8000)
        ├── celery worker (4 concurrent workers)
        └── celery beat (periodic task scheduler)
```

## Updating

```bash
cd GalactiLog
docker compose pull app
docker compose up -d
```

This pulls the latest image from DockerHub and restarts the application. Database migrations are applied automatically on startup.

To update to a specific version, edit the image tag in `docker-compose.yml`:

```yaml
image: chvvkumar/galactilog:1.0.1
```

To build from source (e.g., after pulling the latest code):

```bash
git pull
docker compose up -d --build
```

If you need to run migrations manually:

```bash
docker compose run --rm app alembic upgrade head
```

## Uninstalling

### Using the Uninstall Script

```bash
bash uninstall.sh
```

This removes containers, networks, volumes, the Docker image, and data directories (thumbnails and database). Your FITS source files are never deleted.

### Manual Cleanup

```bash
# Stop and remove containers and networks
docker compose down

# Also remove persistent volumes
docker compose down -v

# Remove the Docker image
docker rmi galactilog-app

# Remove data directories (optional)
rm -rf /path/to/thumbnails /path/to/database
```

## Troubleshooting

### Port 8080 already in use

Another service is using port 8080. Change the port mapping in `docker-compose.yml`:

```yaml
ports:
  - "9090:80"  # Change 8080 to any available port
```

### FITS files not found during scan

- Verify `FITS_DATA_HOST_PATH` in `.env` points to the correct directory
- The path is mounted read-only; ensure the directory exists and is readable
- GalactiLog scans for files with extensions `.fits`, `.fit`, and `.fts` (case-insensitive)
- Check container logs: `docker compose logs app`

### SIMBAD resolution timeouts

SIMBAD is an external service and may be slow or temporarily unavailable. GalactiLog handles this gracefully:
- Failed lookups are retried on subsequent scans
- Successfully resolved targets are cached in the local database
- You can trigger a backfill from Settings > Scan & Ingest > Backfill Targets

### Database connection errors

```bash
# Check if PostgreSQL is healthy
docker compose ps postgres

# View PostgreSQL logs
docker compose logs postgres

# If the database is corrupted, reset it (WARNING: deletes all data)
docker compose down -v
docker compose up -d
```

### Thumbnails not generating

- Check that `THUMBNAILS_HOST_PATH` exists and is writable
- Calibration frames (DARK, FLAT, BIAS) do not generate thumbnails by design
- View worker logs for errors: `docker compose logs app | grep celery`

### Container won't start

```bash
# Check container status
docker compose ps

# View detailed logs
docker compose logs app

# Rebuild from scratch
docker compose down
docker compose up -d --build
```
