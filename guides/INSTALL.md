# Install Guide

## Prerequisites

- **Docker** (20.10+) and **Docker Compose v2** (`docker compose` command)
- Network access to [SIMBAD](https://simbad.cds.unistra.fr/) (used for target name resolution; results are cached locally after first lookup)
- A directory containing your FITS files from N.I.N.A. imaging sessions

## Install

### 1. Get the Compose File

Download the example compose file, or clone the repo:

```bash
# Option A: download just the compose file
curl -O https://raw.githubusercontent.com/chvvkumar/GalactiLog/main/docker-compose.example.yml
cp docker-compose.example.yml docker-compose.yml

# Option B: clone the full repository
git clone https://github.com/chvvkumar/GalactiLog.git
cd GalactiLog
cp docker-compose.example.yml docker-compose.yml
```

### 2. Edit docker-compose.yml

Open `docker-compose.yml` and update the lines marked with `<-- CHANGE`:

| Setting | What to change |
|---------|---------------|
| **FITS path** | Your host directory containing FITS files (mounted read-only) |
| **Admin password** | Password for the admin account (min 8 characters) |
| **Port** | Host port for the web UI (default: 8080) |

#### Platform-specific FITS paths

**Linux:**
```yaml
- /home/user/astro/data:/app/data/fits:ro
```

**Windows (Docker Desktop):**
```yaml
- D:/Astrophotography/Data:/app/data/fits:ro
```

**NAS / NFS mount:**
```bash
# Mount the NFS share on the host first
sudo mkdir -p /mnt/astro
sudo mount -t nfs nas.local:/volume1/astrophotography /mnt/astro
```
```yaml
- /mnt/astro:/app/data/fits:ro
```

To make the NFS mount persistent across reboots, add it to `/etc/fstab`:
```
nas.local:/volume1/astrophotography  /mnt/astro  nfs  ro,soft,timeo=30  0  0
```

#### Optional settings

The compose file also includes commented-out options for:

- **Host paths for postgres data and thumbnails** -- by default these use Docker named volumes; uncomment to use host directories for easier backups
- **JWT secret** -- set for persistent sessions across container restarts
- **Viewer account** -- read-only access for sharing without admin privileges

### 3. Start

```bash
docker compose up -d

# Watch first-start logs (migrations, admin account creation)
docker compose logs -f app
```

On first start, GalactiLog will:
1. Run database migrations to create all tables
2. Create the admin account from the credentials in the compose file
3. Start the web UI, API, and background worker

### 4. Verify

Open `http://localhost:8080` (or your configured port). You should see the GalactiLog login page.

```bash
# Verify the API is responding
curl http://localhost:8080/api/scan/status
# Expected: {"state":"idle","total":0,"completed":0,"failed":0,"failed_files":[]}
```

### 5. First Scan

Log in with your admin credentials, then navigate to **Settings > Scan & Ingest** and click **Start Scan**. GalactiLog will:

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
docker compose pull app
docker compose up -d
```

This pulls the latest image from DockerHub and restarts the application. Database migrations are applied automatically on startup.

To pin a specific version, edit the image tag in `docker-compose.yml`:

```yaml
image: chvvkumar/galactilog:1.0.1
```

## Building from Source

```bash
git clone https://github.com/chvvkumar/GalactiLog.git
cd GalactiLog
cp docker-compose.example.yml docker-compose.yml
# Edit docker-compose.yml, then change the app image line to:
#   build: .
# and remove or comment out the image: line
docker compose up -d --build
```

## Uninstalling

```bash
# Stop and remove containers and networks
docker compose down

# Also remove persistent volumes (database and thumbnails)
docker compose down -v

# Remove the Docker image
docker rmi chvvkumar/galactilog

# If using host paths, remove those directories manually
```

Your FITS source files are never modified or deleted.

## Troubleshooting

### Port 8080 already in use

Change the port mapping in `docker-compose.yml`:

```yaml
ports:
  - "9090:80"  # Change 8080 to any available port
```

### FITS files not found during scan

- Verify the FITS volume mount path in `docker-compose.yml` is correct
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

### Container won't start / migration loop

If the app container keeps restarting with "Running database migrations..." errors:

```bash
# Check what's happening
docker compose logs app

# Most common fix: clean start with fresh database
docker compose down -v
docker compose up -d
```

If you previously changed postgres credentials (user, password, or database name), you must delete the postgres data first -- PostgreSQL only creates the database on first initialization of the data directory. Changing credentials after that has no effect.

### Thumbnails not generating

- Calibration frames (DARK, FLAT, BIAS) do not generate thumbnails by design
- View worker logs for errors: `docker compose logs app | grep celery`
