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

The compose file includes commented-out options for host paths (postgres data, thumbnails), JWT secret, and a read-only viewer account.

### 3. Start

```bash
docker compose up -d

# Watch first-start logs (migrations, admin account creation)
docker compose logs -f app
```

On first start, GalactiLog runs migrations, creates the admin account, and starts the web UI, API, and background worker.

### 4. Verify

Open `http://localhost:8080` (or your configured port).

```bash
# Verify the API is responding
curl http://localhost:8080/api/scan/status
# Expected: {"state":"idle","total":0,"completed":0,"failed":0,"failed_files":[]}
```

### 5. First Scan

Log in and go to **Settings > Library > Scan Directory**. GalactiLog discovers FITS files, extracts metadata, generates thumbnails, resolves targets via SIMBAD, and backfills metrics from any N.I.N.A. CSV files. Progress is shown in real-time.

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

## Running as non-root

The container runs as a non-root `galactilog` user (UID 1000, GID 1000 by default) for security. Any bind-mounted directory the container writes to must be accessible to that user. The FITS mount is read-only and only needs read access.

### Discover the host user and group ID

Run these on the host, as the user who owns the target directory:

```bash
id -u
id -g
```

To inspect the current owner of a bind-mount source:

```bash
stat -c '%u %g' /path/to/thumbnails
```

### Set PUID and PGID

Pass `PUID` and `PGID` to remap the in-container `galactilog` user to the host UID/GID at entrypoint time. Set them in the `environment:` block of the app service:

```yaml
services:
  app:
    environment:
      - PUID=1000
      - PGID=1000
```

Or via `.env` in the project root:

```
PUID=1000
PGID=1000
```

and reference them in `docker-compose.yml`:

```yaml
environment:
  - PUID=${PUID}
  - PGID=${PGID}
```

### Platform notes

- TrueNAS SCALE: the `apps` user is typically UID/GID 568. Set `PUID=568` and `PGID=568`, and ensure the dataset ACL grants that user write access to the thumbnails path.
- Unraid: the `nobody` user is UID 99, GID 100. Set `PUID=99` and `PGID=100`.
- Synology DSM: UIDs vary per user account. Check `id <username>` via SSH. For shared folders, use the UID/GID of the owning user.
- Generic Linux host: `PUID=1000` and `PGID=1000` match the first regular user on most distributions and are the default if `PUID`/`PGID` are omitted.

### First-boot chown

On the first start after upgrading to a non-root image, the entrypoint runs `chown -R` on `/app/data/thumbnails` to match the effective `PUID:PGID` if the existing ownership differs. This runs once and may take time on large thumbnail directories.

To skip the automatic chown (for example, if you have pre-set ownership yourself or run on a filesystem where recursive chown is expensive), set:

```yaml
environment:
  - GALACTILOG_SKIP_CHOWN=1
```

With this flag set, you are responsible for ensuring the thumbnail directories are writable by the `PUID:PGID` user.

## Updating

```bash
docker compose pull app
docker compose up -d
```

Migrations run automatically on startup. To pin a specific version:

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

SIMBAD may be slow or temporarily unavailable. Failed lookups are retried on subsequent scans, and resolved targets are cached locally. You can trigger a backfill from Settings > Library > Backfill Targets.

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
