# CSV Metrics Backfill

`POST /api/scan/backfill-csv` is an admin-only, curl-only maintenance
operation. It is not exposed anywhere in the frontend by design; it exists to
backfill frame-quality and weather metrics for images that were ingested
before their N.I.N.A. Session Metadata CSV files were present or readable
(e.g. the CSV plugin was added after a run of imports, or a share was
temporarily unavailable during scan).

## What it does

The Celery task (`backfill_csv_metrics` in `backend/app/worker/tasks.py`)
walks the configured FITS data directory (`GALACTILOG_FITS_DATA_PATH`) for
every subdirectory containing an `ImageMetaData.csv` file. For each directory:

1. Parses `ImageMetaData.csv` (per-frame metrics) and, if present,
   `WeatherData.csv` (ambient conditions), joined by the `ExposureStartUTC`
   column.
2. Finds `images` rows under that directory whose `detected_stars` column is
   still `NULL` (the signal that they never got CSV-derived metrics).
3. Updates each matching row's metric columns from the CSV data.

It only touches rows that look like they never received CSV metrics; frames
already backfilled (or ingested with the CSV already in place) are left
alone.

## Expected CSV layout

Both files are produced by the N.I.N.A. Session Metadata plugin and must live
in the same directory as the FITS frames they describe.

`ImageMetaData.csv` columns consumed (others are ignored):

| CSV column | Image column | Notes |
|---|---|---|
| `FilePath` | (used to match the frame by filename) | required |
| `HFR` | `median_hfr` | `0.0` is treated as a failed detection and stored as `NULL` |
| `HFRStDev` | `hfr_stdev` | |
| `FWHM` | `fwhm` | |
| `Eccentricity` | `eccentricity` | |
| `DetectedStars` | `detected_stars` | |
| `GuidingRMSArcSec` | `guiding_rms_arcsec` | |
| `GuidingRMSRAArcSec` | `guiding_rms_ra_arcsec` | |
| `GuidingRMSDECArcSec` | `guiding_rms_dec_arcsec` | |
| `ADUStDev` | `adu_stdev` | |
| `ADUMean` | `adu_mean` | |
| `ADUMedian` | `adu_median` | |
| `ADUMin` / `ADUMax` | `adu_min` / `adu_max` | |
| `FocuserPosition` | `focuser_position` | |
| `FocuserTemp` | `focuser_temp` | |
| `RotatorPosition` | `rotator_position` | |
| `PierSide` | `pier_side` | |
| `Airmass` | `airmass` | |
| `ExposureStartUTC` | (join key into `WeatherData.csv`) | |

`WeatherData.csv` columns consumed, joined by matching `ExposureStartUTC`:

| CSV column | Image column |
|---|---|
| `Temperature` | `ambient_temp` |
| `DewPoint` | `dew_point` |
| `Humidity` | `humidity` |
| `Pressure` | `pressure` |
| `WindSpeed` | `wind_speed` |
| `WindDirection` | `wind_direction` |
| `WindGust` | `wind_gust` |
| `CloudCover` | `cloud_cover` |
| `SkyQuality` | `sky_quality` |

Empty cells, blank strings, and `NaN` are all stored as `NULL`. A directory
missing `WeatherData.csv` still gets its `ImageMetaData.csv` fields applied.

## Invocation

Admin auth uses an httpOnly cookie set by `/api/auth/login`, so authenticate
first with a cookie jar and reuse it on the backfill call:

```bash
# 1. Log in as an admin user, keeping the session cookie
curl -c cookies.txt -X POST https://galactilog.example.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "chvvkumar", "password": "<admin password>"}'

# 2. Kick off the backfill (dispatches the Celery task and returns immediately)
curl -b cookies.txt -X POST https://galactilog.example.com/api/scan/backfill-csv
```

Response: `{"status": "accepted"}`, or `{"status": "already_running", "state": "scanning" | "ingesting"}`
if a scan/ingest is already in progress (the backfill shares the same
scan-state Redis key and progress cascade, so it won't run concurrently with
one).

## Progress and completion

The task reuses the normal scan-state machinery (`kind="csv_backfill"`), so
progress shows up the same way an ordinary scan's ingest phase does (poll
`GET /api/scan/status`). Failures per CSV directory are logged
(`backfill_csv_metrics: failed to process CSV directory ...`) with the full
traceback rather than silently skipped, so check `app_logs` / the Activity
Log if a directory's frames don't end up updated.
