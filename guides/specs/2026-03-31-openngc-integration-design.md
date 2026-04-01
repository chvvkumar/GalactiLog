# OpenNGC Integration Design

## Summary

Integrate the OpenNGC dataset to enrich Target records with angular size, surface brightness, position angle, and visual magnitude. Data is stored in a PostgreSQL reference table loaded from a bundled CSV, and surfaced on the target detail page alongside existing RA/Dec values.

## Background

GalactiLog uses SIMBAD for target name resolution and basic metadata (coordinates, object type, aliases). SIMBAD does not provide angular size, surface brightness, or visual magnitude for deep-sky objects. These are critical for astrophotography planning.

OpenNGC is a community-curated dataset of ~13,000 NGC/IC objects (CC-BY-SA-4.0) that includes exactly these fields. It covers all Messier, NGC, and IC objects — the primary targets for astrophotographers.

## Data Layer

### New model: `OpenNGCEntry`

Reference table loaded from the bundled CSV. Read-only after initial load.

| Column | Type | Source CSV field | Notes |
|--------|------|-----------------|-------|
| `name` (PK) | `String(20)` | `Name` | e.g. "NGC 7000", "IC 1396" |
| `type` | `String(10)` | `Type` | e.g. "HII", "Gx", "OC" |
| `ra` | `Float` | `RA` | Converted from HMS to decimal degrees |
| `dec` | `Float` | `Dec` | Converted from DMS to decimal degrees |
| `major_axis` | `Float` | `MajAx` | Arcminutes, nullable |
| `minor_axis` | `Float` | `MinAx` | Arcminutes, nullable |
| `position_angle` | `Float` | `PosAng` | Degrees, nullable |
| `b_mag` | `Float` | `B-Mag` | Nullable |
| `v_mag` | `Float` | `V-Mag` | Nullable |
| `surface_brightness` | `Float` | `SurfBr` | mag/arcsec², nullable |
| `common_names` | `String` | `Common names` | Semicolon-separated, nullable |
| `messier` | `String(10)` | `M` | Cross-reference, nullable |

### New fields on `Target` model

| Column | Type | Display example |
|--------|------|-----------------|
| `size_major` | `Float` | "26.9'" (arcmin) |
| `size_minor` | `Float` | "17.4'" (arcmin) |
| `position_angle` | `Float` | "35°" |
| `v_mag` | `Float` | "8.3" |
| `surface_brightness` | `Float` | "22.1" (mag/arcsec²) |

## CSV Bundling

The OpenNGC `NGC.csv` file (~2.5 MB) is committed at `backend/data/catalogs/openngc.csv`. This is small enough that compression is unnecessary. The Dockerfile picks it up via the existing `COPY backend/ .` directive.

## Enrichment Flow

During target resolution (in `_resolve_or_cache_target` or after `curate_simbad_result`):

1. Take the target's `catalog_id` (e.g. "NGC 7000", "M 101")
2. Look up in `openngc_catalog` table:
   - Match `catalog_id` against `OpenNGCEntry.name` (for NGC/IC targets)
   - Match against `OpenNGCEntry.messier` (for Messier targets)
3. If found, populate the 5 new Target fields (`size_major`, `size_minor`, `position_angle`, `v_mag`, `surface_brightness`)

Existing targets are backfilled via the data migration. New targets are enriched at scan time.

## Migration Strategy

### Alembic migration

- Create `openngc_catalog` table
- Add 5 nullable columns to `targets` table: `size_major`, `size_minor`, `position_angle`, `v_mag`, `surface_brightness`

### Data migration (DATA_VERSION 3)

- Load `backend/data/catalogs/openngc.csv` into `openngc_catalog` table (upsert)
- Parse RA from HMS (HH:MM:SS.ss) to decimal degrees
- Parse Dec from DMS (+DD:MM:SS.s) to decimal degrees
- For each existing Target with a `catalog_id` matching an OpenNGC entry, populate the 5 new fields

## New Service: `openngc.py`

`backend/app/services/openngc.py` — small service module:

- `load_openngc_csv(session)` — parse CSV, insert/update rows in `openngc_catalog`
- `lookup_openngc(session, catalog_id)` — find matching OpenNGC entry by name or Messier cross-ref
- `enrich_target_from_openngc(session, target)` — look up and populate target fields

## API Changes

Add 5 new optional fields to `TargetDetailResponse` in `backend/app/schemas/target.py`:

```python
size_major: float | None = None
size_minor: float | None = None
position_angle: float | None = None
v_mag: float | None = None
surface_brightness: float | None = None
```

No new endpoints needed.

## Frontend Changes

In `TargetDetailPage.tsx`, add the new values inline in the target hero subtitle (the `text-xs text-theme-text-secondary` line), after RA/Dec:

```
H2G,GiG,GiP · RA 210.802° Dec 54.349° · 26.9' x 17.4' PA 35° · V 8.3 SB 22.1
```

- Size displayed as `major' x minor'` (arcmin symbol)
- PA only shown when non-null
- V mag and surface brightness only shown when non-null

Add corresponding fields to the `TargetDetailResponse` TypeScript interface in `frontend/src/types/index.ts`.

## Scope

### In scope
- OpenNGC CSV bundling and DB table
- Target model enrichment (5 new fields)
- Data migration to backfill existing targets
- API schema updates
- Frontend display on target detail page

### Out of scope
- VizieR integration for non-NGC/IC objects (future work)
- NED integration for galaxy-specific data (future work)
- Dashboard-level size/magnitude columns
- Filtering/sorting by size or magnitude
