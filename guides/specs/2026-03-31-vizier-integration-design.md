# VizieR Integration Design

## Summary

Add VizieR TAP queries as a fallback enrichment source for targets not covered by OpenNGC (non-NGC/IC objects like Sharpless, Barnard, LBN, etc.). Also use OpenNGC's `common_names` field as a fallback when SIMBAD doesn't provide a common name.

## Background

OpenNGC covers NGC/IC/Messier objects. Targets from other catalogs (Sharpless, Barnard, LBN, LDN, vdB, RCW, Collinder, Melotte, Cederblad, Abell PNe) currently get no size, magnitude, or constellation enrichment. VizieR hosts the original catalogs for all of these.

## VizieR Catalogs

| Catalog | VizieR ID | Objects | Size columns | Brightness columns |
|---------|-----------|---------|-------------|-------------------|
| Sharpless HII | VII/20 | 313 | Diam | Bright (1-3) |
| LBN | VII/9 | 1,125 | Diam1/Diam2 | Bright (1-6) |
| RCW | VII/216 | 181 | MajAxis/MinAxis | Br (v/b/m/f) |
| vdB | VII/21 | 158 | BRadMax/RRadMax | SurfBr |
| Open clusters (Cr/Mel/Tr/etc.) | B/ocl | 2,167 | Diam | — |
| LDN | VII/7A | 1,791 | Area (sq deg) | Opacity (1-6) |
| Barnard | VII/220A | 349 | Diam | — |
| Planetary Nebulae (incl. Abell) | V/84 | 1,143 | oDiam (arcsec) | — |
| Cederblad | VII/231 | 330 | Dim1/Dim2 | — |
| Abell galaxy clusters | VII/110A | ~5,524 | — | m10 (mag) |

## Enrichment Flow (Updated)

```
Target resolved via SIMBAD
    |
    v
OpenNGC lookup (local DB, instant)
    |-- matched: populate size/mag/constellation + common_name fallback
    |-- no match:
    v
VizieR lookup (network, cached)
    |-- matched: populate size/constellation from catalog
    |-- no match: skip
    v
Target fields populated
```

## VizieR Cache Table

New `vizier_cache` table to persist results and avoid repeated network calls:

| Column | Type | Notes |
|--------|------|-------|
| `catalog_id` (PK) | `String(50)` | Target's catalog_id used as lookup key |
| `vizier_catalog` | `String(20)` | Which VizieR catalog matched (e.g. "VII/20") |
| `size_major` | `Float` | Arcminutes (converted from arcsec/sq deg where needed) |
| `size_minor` | `Float` | Arcminutes, nullable |
| `constellation` | `String(5)` | From VizieR `_RA.icrs`/`_DE.icrs` -> computed, or from catalog if available |
| `fetched_at` | `DateTime` | Cache timestamp |

Negative results are cached as rows with null size fields to prevent re-querying.

## Catalog Matching Logic

The service determines which VizieR catalog to query based on the target's `catalog_id` prefix:

| Prefix pattern | VizieR catalog | ADQL table |
|---------------|----------------|------------|
| `SH 2-*` / `Sh2-*` | VII/20 | `"VII/20/catalog"` |
| `LBN *` | VII/9 | `"VII/9/catalog"` |
| `RCW *` | VII/216 | `"VII/216/rcw"` |
| `vdB *` | VII/21 | `"VII/21/catalog"` |
| `Collinder *` / `Cr *` / `Melotte *` / `Mel *` / `Trumpler *` / `Tr *` / `Berkeley *` / `King *` / `Stock *` | B/ocl | `"B/ocl/clusters"` |
| `LDN *` | VII/7A | `"VII/7A/ldn"` |
| `B *` (Barnard) | VII/220A | `"VII/220A/barnard"` |
| `Abell *` / `PN A66 *` | V/84 | `"V/84/main"` + `"V/84/diam"` |
| `Ced *` / `Cederblad *` | VII/231 | `"VII/231/catalog"` |

Targets that don't match any prefix skip VizieR entirely.

## New Service: `vizier.py`

`backend/app/services/vizier.py`:

- `VIZIER_TAP_URL = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"`
- `determine_vizier_catalog(catalog_id) -> tuple[str, str, str] | None` — returns (vizier_id, adql_table, catalog_number_column) based on prefix matching
- `build_adql_query(catalog_id) -> str | None` — builds the ADQL SELECT for the matching catalog
- `query_vizier(catalog_id) -> dict | None` — executes TAP query, parses TSV response, returns dict with `size_major`, `size_minor`, `constellation`
- `enrich_target_from_vizier(session, target) -> bool` — check cache first, query if needed, populate Target fields
- Rate limit: 0.3s between queries (same as SIMBAD)
- Timeout: 15s per query

## OpenNGC Common Name Fallback

Currently `enrich_target_from_openngc` populates size/magnitude/constellation but ignores OpenNGC's `common_names` field. Update the enrichment to also set `target.common_name` from OpenNGC when:

1. The target has no `common_name` (SIMBAD didn't provide one)
2. The matching OpenNGC entry has a non-empty `common_names` field

OpenNGC stores common names semicolon-separated (e.g. `"North America Nebula"`). Take the first entry, title-case it.

After setting `common_name`, rebuild `primary_name` using the existing `build_primary_name(catalog_id, common_name)` function.

## Migration Strategy

### Alembic migration 0013

- Create `vizier_cache` table

### Data migration (DATA_VERSION 4)

- Backfill existing targets that have no `size_major` and whose `catalog_id` matches a VizieR-supported prefix
- Also backfill OpenNGC common names for targets that have no `common_name`
- Rate limit: 0.3s between VizieR queries

## Worker Changes

In `_resolve_or_cache_target` (after OpenNGC enrichment):

```python
if target.size_major is None:
    enrich_target_from_vizier(session, target)
```

Only calls VizieR if OpenNGC didn't already provide size data.

## No New Frontend Changes

VizieR populates the same Target fields (`constellation`, `size_major`, `size_minor`) that the frontend already displays from OpenNGC. No UI changes needed.

## Scope

### In scope
- VizieR TAP service with cache
- 10 catalog query builders
- Cache table (Alembic migration)
- Data migration v4 (backfill)
- Worker integration (fallback after OpenNGC)
- OpenNGC common name fallback
- Tests for catalog matching, ADQL building, response parsing

### Out of scope
- NED integration (galaxy-specific, low priority)
- MAST integration (observation archive, not a catalog)
- VizieR brightness values mapped to surface_brightness (qualitative scales don't convert cleanly)
- New UI for VizieR-specific data
