# Catalog Integration Implementation Plan

Target enrichment beyond SIMBAD, VizieR, and OpenNGC. Organized into three tiers plus static catalog memberships, with a unified build sequence at the end.

## Table of Contents

- [Tier 1: NED, HyperLEDA, SAC](#tier-1-ned-hyperleda-sac)
- [Tier 2: CDS xMatch, DSS/SkyView, USNO, Aladin Lite, Gaia DR3](#tier-2-cds-xmatch-dssskyview-usno-aladin-lite-gaia-dr3)
- [Static Catalogs: Caldwell, Herschel 400, Arp, Abell](#static-catalogs)
- [Unified Build Sequence](#unified-build-sequence)
- [Schema Summary](#schema-summary)

---

## Tier 1: NED, HyperLEDA, SAC

### 1.1 NED (NASA Extragalactic Database)

**Purpose**: Hubble morphological type, redshift, distances, activity type for galaxies.

**API**: TAP/ADQL at `https://ned.ipac.caltech.edu/tap/sync`. Same POST pattern as VizieR (`REQUEST=doQuery, LANG=ADQL, FORMAT=tsv`).

**Galaxy gate**: Only query NED when `object_type` contains galaxy-related SIMBAD codes: `G`, `GiG`, `GiC`, `BiC`, `Sy1`, `Sy2`, `LINER`, `AGN`, `rG`, `HzG`, `BClG`, `GiP`, `PaG`, `SBG`, `SyG`. Split the `object_type` string on comma/space and check against a `frozenset`.

**Files to create**:

| File | Description |
|---|---|
| `backend/app/models/ned_cache.py` | Cache table: `catalog_id` (PK), `ned_morphology`, `redshift`, `distance_mpc`, `activity_type`, `fetched_at` |
| `backend/app/services/ned.py` | `_is_galaxy_type()`, `query_ned()`, `get_cached_ned()`, `save_ned_cache()`, `enrich_target_from_ned()` |

**ADQL query** (verify column names against live schema with `SELECT TOP 1 * FROM NED_Main`):
```sql
SELECT objname, morph_type, z, distance, activity FROM NED_Main WHERE objname = 'NGC 4258'
```

**Critical**: NED TAP schema column names must be verified before implementation. Run `SELECT * FROM TAP_SCHEMA.tables` first.

### 1.2 HyperLEDA

**Purpose**: Numerical morphological type (T parameter, -5 to +10), galaxy inclination.

**API**: HTTP GET to `http://leda.univ-lyon1.fr/fG.cgi` with SQL in params:
```
?n=meandata&c=o&of=csv&nrow=1&sql=SELECT pgc,t,incl FROM meandata WHERE objname='NGC4258'
```

**Name format**: HyperLEDA typically uses lowercase with no space (`ngc4258`). Test both formats against the live endpoint before implementing.

**Files to create**:

| File | Description |
|---|---|
| `backend/app/models/hyperleda_cache.py` | Cache table: `catalog_id` (PK), `t_type`, `inclination`, `fetched_at` |
| `backend/app/services/hyperleda.py` | `_hyperleda_name()`, `query_hyperleda()`, cache functions, `enrich_target_from_hyperleda()` |

**Fallback**: If the direct HTTP interface is unreliable, use VizieR catalog VII/237 via the existing TAP pattern.

### 1.3 SAC (Saguaro Astronomy Club) Database

**Purpose**: Observing descriptions, difficulty ratings, notes for ~10,000 deep sky objects.

**Source**: Downloadable CSV from `https://www.saguaroastro.org/sac-downloads/`. No API.

**Integration pattern**: Identical to OpenNGC (bundled CSV, loaded into DB table, matched to targets).

**Files to create**:

| File | Description |
|---|---|
| `backend/data/catalogs/sac.csv` | Downloaded and placed manually. Encoding: likely Windows-1252, open with `latin-1` fallback |
| `backend/app/models/sac_catalog.py` | `object_name` (PK), `description` (Text), `notes` (Text), `object_type`, `constellation`, `magnitude`, `size` |
| `backend/app/services/sac.py` | `load_sac_csv()`, `lookup_sac()`, `enrich_target_from_sac()` |

**CSV column mapping**: Inspect the downloaded file. Typical SAC format: `Object`, `Other`, `Type`, `Con`, `RA`, `Dec`, `Mag`, `SBrightness`, `Size`, `Notes`. The `Notes` column maps to `sac_description`.

### 1.4 Tier 1 Target Model Fields

All nullable, added to `backend/app/models/target.py`:

| Field | Type | Source |
|---|---|---|
| `ned_morphology` | `String(50)` | NED |
| `redshift` | `Float` | NED |
| `distance_mpc` | `Float` | NED |
| `activity_type` | `String(100)` | NED |
| `hubble_t_type` | `Float` | HyperLEDA |
| `inclination` | `Float` | HyperLEDA |
| `sac_description` | `Text` | SAC |
| `sac_notes` | `Text` | SAC |

### 1.5 Tier 1 Pipeline Integration

In `backend/app/services/target_resolver.py` `_create_target`, after existing OpenNGC/VizieR enrichment:

```python
enrich_target_from_sac(session, target)      # all targets
enrich_target_from_ned(session, target)       # galaxy gate inside
enrich_target_from_hyperleda(session, target) # galaxy gate inside
```

### 1.6 Tier 1 Frontend

**TargetDetailPage**: Galaxy properties inline with existing metadata row (morphology, redshift, distance, activity type, T-type, inclination). SAC description as a card below the stats bar:

```tsx
<Show when={detail().sac_description || detail().sac_notes}>
  <div class="rounded-[var(--radius-sm)] bg-theme-elevated border ...">
    <div class="text-xs font-medium ...">Observing Notes</div>
    <p class="text-sm ...">{detail().sac_description}</p>
  </div>
</Show>
```

---

## Tier 2: CDS xMatch, DSS/SkyView, USNO, Aladin Lite, Gaia DR3

### 2.1 CDS xMatch (Bulk Enrichment)

**Purpose**: Batch cross-match entire target list against any VizieR catalog in one POST. More efficient than per-target VizieR TAP queries.

**API**: `http://cdsxmatch.u-strasbg.fr/xmatch/api/v1/sync`. Accepts `multipart/form-data` with `cat1` (user CSV with `ra,dec,id` columns) and `cat2` (VizieR catalog ID).

**Files to create**:

| File | Description |
|---|---|
| `backend/app/services/xmatch.py` | `bulk_xmatch_targets(targets, vizier_catalog, radius_arcsec)` returns dict mapping catalog_id to enrichment data |

**Files to modify**:

| File | Change |
|---|---|
| `backend/app/worker/tasks.py` | Add `run_xmatch_enrichment` Celery task |
| `frontend/src/components/MaintenanceActions.tsx` | Add "Run xMatch Enrichment" trigger button |

**Notes**: Max upload ~50K rows (typical installs have <1000 targets). Default radius: 60 arcsec for most objects, 300 arcsec for large nebulae. Results write directly to Target fields and vizier_cache.

### 2.2 DSS/SkyView Reference Thumbnails

**Purpose**: Professional survey reference images for every target. Every target has RA/Dec so 100% coverage.

**API**: `https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl?Survey=DSS2+Red&Position={ra},{dec}&Size={fov}&Pixels=512&Return=JPEG`

**FOV calculation**: `target.size_major * 1.5 / 60` degrees, clamped to [0.1, 5.0]. Default 0.5 deg when size is unknown.

**Storage**: `{FITS_DATA_PATH}/.galactilog/ref_thumbnails/{target_uuid}.jpg`. Store relative path in `Target.reference_thumbnail_path`.

**Files to create**:

| File | Description |
|---|---|
| `backend/app/services/skyview.py` | `fetch_reference_thumbnail(target, output_dir)` returns relative path or None |

**Files to modify**:

| File | Change |
|---|---|
| `backend/app/models/target.py` | Add `reference_thumbnail_path: String(1024)` |
| `backend/app/worker/tasks.py` | Add `generate_reference_thumbnails` Celery task (batch with 1s delay) |
| `backend/app/api/targets.py` | Add `GET /api/targets/{id}/reference-thumbnail` endpoint to stream JPEG |
| `frontend/src/pages/TargetDetailPage.tsx` | Render reference thumbnail in hero section |
| `frontend/src/components/MaintenanceActions.tsx` | Add "Generate Reference Thumbnails" button |

### 2.3 USNO Astronomical Applications API

**Purpose**: Moon phase, astronomical twilight windows, darkness periods for imaging planning. Environmental data, not object data.

**API**: REST/JSON at `https://aa.usno.navy.mil/api/`
- `GET /api/rstt/oneday?date={date}&coords={lat},{lon}&tz=0` (twilight times)
- `GET /api/moon/phases/date?date={date}&nump=1` (moon phase)

**Requires**: Observer location (lat/lon) stored in settings.

**Files to create**:

| File | Description |
|---|---|
| `backend/app/services/usno.py` | `get_night_ephemeris(date_iso, lat, lon)` returns dict with `astro_dusk`, `astro_dawn`, `moon_phase`, `moon_illumination`, `moon_rise`, `moon_set` |
| `backend/app/api/planning.py` | `GET /api/planning/night?date=YYYY-MM-DD`. Reads observer location from settings. Returns 400 if location not configured |

**Files to modify**:

| File | Change |
|---|---|
| `backend/app/schemas/settings.py` | Add `observer_latitude`, `observer_longitude`, `observer_name` to `GeneralSettings` (nullable floats, no DB migration needed since JSONB) |
| `backend/app/api/router.py` | Register `planning_router` |
| `frontend/src/pages/SettingsPage.tsx` | Add "Observer Location" inputs under General settings |
| `frontend/src/types/index.ts` | Add `NightEphemeris` interface, observer fields to `GeneralSettings` |
| `frontend/src/api/client.ts` | Add `getNightEphemeris(date)` |

**Notes**: No DB persistence for ephemeris data (it is date/location-specific). Graceful fallback when USNO API is unavailable (`source_available: false` flag).

### 2.4 Aladin Lite (Frontend Only)

**Purpose**: Embeddable interactive sky viewer with multi-survey image overlays. Zero backend changes.

**Loading**: CDN script tag in `index.html`:
```html
<script type="module" src="https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js"></script>
```
Alternative: npm `aladin-lite` package if Vite bundles it cleanly (test first; the widget has WebAssembly internals).

**Files to create**:

| File | Description |
|---|---|
| `frontend/src/components/AladinViewer.tsx` | SolidJS wrapper. Props: `ra`, `dec`, `fov` (degrees). Uses `onMount` to initialize. Survey selector dropdown (DSS2, 2MASS, PanSTARRS). Fixed height `h-64` |

**Files to modify**:

| File | Change |
|---|---|
| `frontend/index.html` | Add Aladin CDN script tag |
| `frontend/src/pages/TargetDetailPage.tsx` | Embed `AladinViewer` in a collapsible "Sky View" section, gated on `ra !== null && dec !== null` |

**Notes**: Widget is not reactive. Use SolidJS `key` prop to force remount on target navigation. FOV from `size_major * 1.5 / 60` degrees.

### 2.5 Gaia DR3 (Star Cluster Distances)

**Purpose**: Precise distances to star clusters via median member parallax.

**API**: TAP at `https://gea.esac.esa.int/tap-server/tap/sync`.

**ADQL**:
```sql
SELECT median(parallax) FROM gaiadr3.gaia_source
WHERE 1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {radius_deg}))
  AND parallax > 0 AND parallax_over_error > 5
```

Distance: `1000.0 / parallax_mas` (parsecs). Use `parallax_over_error > 10` for globular clusters (higher contamination).

**Cone radius**: `target.size_major / 60.0 * 0.5` degrees, floor 0.1 degrees.

**Files to create**:

| File | Description |
|---|---|
| `backend/app/services/gaia.py` | `query_cluster_distance(ra, dec, radius_arcmin)` returns `(distance_pc, star_count)` or None |
| `backend/app/models/gaia_cache.py` | `target_id` (UUID PK), `distance_pc`, `parallax_count`, `fetched_at` |

**Files to modify**:

| File | Change |
|---|---|
| `backend/app/models/target.py` | Add `distance_pc: Float` |
| `frontend/src/pages/TargetDetailPage.tsx` | Show "Distance {n} pc (based on {n} stars)" in metadata row |

**Notes**: Gaia TAP queries are slow (3-10s each). Log progress every 10 targets. Use `time.sleep(0.5)` between queries.

---

## Static Catalogs

### Storage Architecture

**Join table approach**: A single `target_catalog_memberships` table links targets to catalog entries. Catalog-specific metadata (Arp category, Abell richness) stored in a `metadata` JSONB column.

```
target_catalog_memberships
  id            INTEGER PRIMARY KEY
  target_id     UUID FK targets.id (indexed)
  catalog_name  VARCHAR(30)         -- "caldwell", "herschel400", "arp", "abell"
  catalog_number VARCHAR(20)        -- "C31", "H400", "Arp 77", "Abell 426"
  metadata      JSONB nullable      -- catalog-specific extras
  UNIQUE(target_id, catalog_name)
```

Each catalog also gets its own source-of-truth table (CSV mirror), following the OpenNGC pattern.

### 3.1 Caldwell Catalog

109 objects. CSV columns: `catalog_id` (C1-C109), `ngc_ic_id`, `object_type`, `constellation`, `common_name`.

**Matching**: Normalize `ngc_ic_id` with `normalize_ngc_name()`, join on `targets.catalog_id`. Fallback: check `targets.aliases` array.

**Metadata JSONB**: `{"caldwell_number": 31, "ngc_ic": "NGC 224"}`

### 3.2 Herschel 400

400 objects, all NGC. CSV columns: `ngc_id`, `object_type`, `constellation`, `magnitude`.

**Matching**: Same as Caldwell (NGC designation match + alias fallback).

**Metadata JSONB**: `{"constellation": "And", "type": "Gx", "magnitude": 3.4}`

### 3.3 Arp Peculiar Galaxies

338 entries. CSV columns: `arp_id` (Arp 1-338), `ngc_ic_ids` (comma-separated, may reference multiple NGC objects), `peculiarity_class`, `peculiarity_description`.

**Matching**: Split `ngc_ic_ids`, normalize each, match against `targets.catalog_id` and aliases. Multiple targets can match a single Arp entry.

**Metadata JSONB**: `{"arp_number": 77, "peculiarity_class": "Spiral with companions"}`

### 3.4 Abell Clusters

4,073 entries. CSV columns: `abell_id`, `ra`, `dec`, `richness_class` (0-5), `distance_class` (1-7), `bm_type` (Bautz-Morgan I through III), `redshift`.

**Matching** (three stages):
1. `catalog_id` prefix match: `Target.catalog_id ILIKE 'Abell %'` or `'ACO %'`
2. Alias match: check `targets.aliases` for `Abell \d+` or `ACO \d+` patterns
3. Coordinate proximity (0.025 deg / ~90 arcsec): only for cluster-type targets (`ClG`, `GrG`, `CGG`). Flat-sky approximation is sufficient.

**Metadata JSONB**: `{"abell_number": 426, "richness": 2, "distance_class": 1, "bm_type": "II-III"}`

### 3.5 Static Catalog Files

All CSV files placed at `backend/data/catalogs/`:

| File | Rows | Size | Source |
|---|---|---|---|
| `caldwell.csv` | 109 | ~5 KB | Patrick Moore's catalogue compilations |
| `herschel400.csv` | 400 | ~15 KB | Astronomical League H400 list |
| `arp.csv` | 338 | ~20 KB | NED cross-reference / Arp Atlas compilations |
| `abell.csv` | ~4,073 | ~260 KB | HEASARC ABELLZCAT |

All NGC/IC IDs pre-normalized to match `normalize_ngc_name()` format (`NGC 31`, not `NGC0031`).

### 3.6 Static Catalog Files to Create

| File | Description |
|---|---|
| `backend/app/models/catalog_membership.py` | Join table model |
| `backend/app/models/caldwell_catalog.py` | Caldwell source table |
| `backend/app/models/herschel400_catalog.py` | Herschel 400 source table |
| `backend/app/models/arp_catalog.py` | Arp source table |
| `backend/app/models/abell_catalog.py` | Abell source table |
| `backend/app/services/caldwell.py` | `load_caldwell_csv()`, `match_caldwell_targets()` |
| `backend/app/services/herschel400.py` | `load_herschel400_csv()`, `match_herschel400_targets()` |
| `backend/app/services/arp.py` | `load_arp_csv()`, `match_arp_targets()` |
| `backend/app/services/abell.py` | `load_abell_csv()`, `match_abell_targets()` |
| `backend/app/services/catalog_membership.py` | `load_catalog_memberships()` dispatcher, `upsert_memberships()` |

### 3.7 Static Catalog Frontend

**Target detail page**: Catalog membership badges (small rounded pills) after the alias row:
- Caldwell: "C31"
- Herschel 400: "H400"
- Arp: "Arp 77" (tooltip shows peculiarity class)
- Abell: "Abell 426" (tooltip shows richness + BM type)

**Dashboard sidebar**: New "Catalog Membership" filter section with toggles for each catalog. Radio semantics (one at a time). Adds `catalog=caldwell` URL param.

**Schema**: New `CatalogMembershipEntry` in Pydantic schemas, `catalog_memberships: list[CatalogMembershipEntry] = []` on `TargetDetailResponse`.

---

## Unified Build Sequence

### Phase 1: Data Files (manual, no code)

- [ ] Download SAC CSV from saguaroastro.org, inspect format, place at `backend/data/catalogs/sac.csv`
- [ ] Source and prepare `backend/data/catalogs/caldwell.csv` (109 rows)
- [ ] Source and prepare `backend/data/catalogs/herschel400.csv` (400 rows)
- [ ] Source and prepare `backend/data/catalogs/arp.csv` (338 rows)
- [ ] Source and prepare `backend/data/catalogs/abell.csv` (~4,073 rows from HEASARC)
- [ ] Verify NED TAP column names: `SELECT TOP 1 * FROM NED_Main`
- [ ] Verify HyperLEDA name format: test `NGC4258` vs `NGC 4258`
- [ ] Test Aladin Lite CDN loading vs npm package in Vite

### Phase 2: Backend Models and Migrations

- [ ] Add 10 new columns to `backend/app/models/target.py` (8 Tier 1 + `reference_thumbnail_path` + `distance_pc`)
- [ ] Create cache models: `ned_cache.py`, `hyperleda_cache.py`, `gaia_cache.py`
- [ ] Create catalog models: `sac_catalog.py`, `caldwell_catalog.py`, `herschel400_catalog.py`, `arp_catalog.py`, `abell_catalog.py`
- [ ] Create `catalog_membership.py` (join table model)
- [ ] Update `backend/app/models/__init__.py` with all new imports
- [ ] Create Alembic migration `0007_catalog_enrichment.py`: all new tables + all new Target columns

### Phase 3: Backend Services (parallelizable)

These are independent of each other:

- [ ] `backend/app/services/ned.py` (NED TAP queries)
- [ ] `backend/app/services/hyperleda.py` (HyperLEDA HTTP SQL)
- [ ] `backend/app/services/sac.py` (SAC CSV load + lookup)
- [ ] `backend/app/services/skyview.py` (reference thumbnail fetch)
- [ ] `backend/app/services/xmatch.py` (CDS bulk cross-match)
- [ ] `backend/app/services/usno.py` (USNO ephemeris)
- [ ] `backend/app/services/gaia.py` (Gaia DR3 parallax)
- [ ] `backend/app/services/caldwell.py`, `herschel400.py`, `arp.py`, `abell.py` (CSV loaders + matchers)
- [ ] `backend/app/services/catalog_membership.py` (dispatcher)

### Phase 4: Backend API and Tasks

- [ ] Create `backend/app/api/planning.py` (USNO night ephemeris endpoint)
- [ ] Register planning router in `backend/app/api/router.py`
- [ ] Add observer location fields to `GeneralSettings` in `backend/app/schemas/settings.py`
- [ ] Add all new fields to `TargetDetailResponse` in `backend/app/schemas/target.py`
- [ ] Add `CatalogMembershipEntry` schema
- [ ] Update `backend/app/api/targets.py`: populate new detail fields, add reference thumbnail endpoint, add catalog filter, load memberships
- [ ] Update `backend/app/worker/tasks.py`: add `generate_reference_thumbnails` and `run_xmatch_enrichment` tasks
- [ ] Integrate NED/HyperLEDA/SAC into `target_resolver.py` enrichment pipeline

### Phase 5: Data Migrations

- [ ] Add `_migrate_v8_tier1_and_catalogs` to `data_migrations.py`: load SAC + static catalogs, match memberships, enrich from NED/HyperLEDA, compute Gaia distances
- [ ] Bump `DATA_VERSION` to 8
- [ ] Run `alembic upgrade head` + verify migration

### Phase 6: Frontend

- [ ] Add all new TypeScript interfaces to `frontend/src/types/index.ts`
- [ ] Add API methods to `frontend/src/api/client.ts`
- [ ] Create `frontend/src/components/AladinViewer.tsx`
- [ ] Add Aladin CDN script to `frontend/index.html`
- [ ] Update `frontend/src/pages/TargetDetailPage.tsx`: galaxy metadata, SAC notes, catalog badges, Aladin viewer, reference thumbnail, distance, planning section
- [ ] Update `frontend/src/pages/SettingsPage.tsx`: observer location inputs
- [ ] Update `frontend/src/components/MaintenanceActions.tsx`: xMatch and thumbnail generation buttons
- [ ] Update `frontend/src/components/Sidebar.tsx`: catalog membership filter section
- [ ] Update `frontend/src/components/DashboardFilterProvider.tsx`: wire catalog filter param

### Phase 7: Verification

- [ ] Deploy and verify DATA_VERSION 8 migration completes
- [ ] Check galaxy targets for NED/HyperLEDA data
- [ ] Check NGC/IC targets for SAC descriptions
- [ ] Check catalog membership badges on known Caldwell/Herschel targets
- [ ] Trigger reference thumbnail generation, verify JPEGs
- [ ] Test Aladin viewer on a target with coordinates
- [ ] Test planning endpoint with observer location set
- [ ] Verify cluster targets have Gaia distances

---

## Schema Summary

### New Target Model Columns (10 total)

| Column | Type | Source | Applies To |
|---|---|---|---|
| `ned_morphology` | String(50) | NED | Galaxies |
| `redshift` | Float | NED | Galaxies |
| `distance_mpc` | Float | NED | Galaxies |
| `activity_type` | String(100) | NED | Galaxies |
| `hubble_t_type` | Float | HyperLEDA | Galaxies |
| `inclination` | Float | HyperLEDA | Galaxies |
| `sac_description` | Text | SAC | All DSOs |
| `sac_notes` | Text | SAC | All DSOs |
| `reference_thumbnail_path` | String(1024) | SkyView | All targets |
| `distance_pc` | Float | Gaia DR3 | Star clusters |

### New Tables (12 total)

| Table | Purpose | PK |
|---|---|---|
| `ned_cache` | NED query cache | `catalog_id` |
| `hyperleda_cache` | HyperLEDA query cache | `catalog_id` |
| `gaia_cache` | Gaia DR3 query cache | `target_id` |
| `sac_catalog` | Bundled SAC CSV mirror | `object_name` |
| `caldwell_catalog` | Bundled Caldwell CSV | `catalog_id` |
| `herschel400_catalog` | Bundled H400 CSV | `ngc_id` |
| `arp_catalog` | Bundled Arp CSV | `arp_id` |
| `abell_catalog` | Bundled Abell CSV | `abell_id` |
| `target_catalog_memberships` | Target-to-catalog join table | `id` (auto), unique on `target_id + catalog_name` |

### New Settings Fields (no DB migration)

| Field | Type | Location |
|---|---|---|
| `observer_latitude` | Float, nullable | `GeneralSettings` JSONB |
| `observer_longitude` | Float, nullable | `GeneralSettings` JSONB |
| `observer_name` | String, nullable | `GeneralSettings` JSONB |

### New API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/planning/night` | GET | USNO ephemeris for a date |
| `/api/targets/{id}/reference-thumbnail` | GET | Stream reference JPEG |
| `/api/tasks/xmatch-enrichment` | POST | Trigger bulk xMatch |
| `/api/tasks/generate-reference-thumbnails` | POST | Trigger thumbnail generation |

### Rate Limits

| Service | Delay Between Requests |
|---|---|
| NED TAP | 0.5s |
| HyperLEDA | 0.3s |
| VizieR / CDS xMatch | 0.3s |
| SkyView | 1.0s |
| Gaia TAP | 0.5s |
