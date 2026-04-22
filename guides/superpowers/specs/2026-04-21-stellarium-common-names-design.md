# Stellarium Common Name Integration

## Problem

GalactiLog resolves common/colloquial deep sky object names (e.g., "Whirlpool Galaxy", "Horsehead Nebula") to catalog IDs via a hand-maintained `COMMON_NAME_MAP` dictionary in `simbad.py` with 93 entries. This map is error-prone: the "Question Mark Galaxy" was incorrectly mapped to NGC 4258 (M106) instead of NGC 5194 (M51), causing 381 frames across 4 imaging sessions to be assigned to the wrong target. The map also has limited coverage compared to what astrophotographers actually use.

## Solution

Replace the bulk of `COMMON_NAME_MAP` with a parsed version of Stellarium's `names.dat` file, which provides ~1,364 community-vetted common name to catalog ID mappings covering NGC, IC, Messier, Sharpless, Barnard, LBN, Collinder, and 30+ other catalogs. Keep a small (~15 entry) override map for abbreviations and edge cases.

## Scope

### In scope
- Bundle Stellarium's `names.dat` in `backend/data/catalogs/`
- New parser module to read the fixed-width format and build a lookup dict
- Convert Stellarium catalog prefixes to SIMBAD-compatible format during parsing
- Integrate into `_get_simbad_id()` as a lookup step between the override map and SIMBAD
- Reduce `COMMON_NAME_MAP` to abbreviations/edge cases only
- Data migration to clear stale SIMBAD cache entries

### Out of scope
- Automatic fetching/updating of names.dat from Stellarium's repo
- New database tables or schema changes
- Frontend changes
- Changes to the SIMBAD/Sesame resolution pipeline beyond the lookup order

---

## Design

### 1. Bundled Data File

`backend/data/catalogs/names.dat` - copied from Stellarium's GitHub repository at `nebulae/default/names.dat`. This is a ~1,584 line text file (~1,364 data lines, ~220 comment/header lines).

Updated manually by re-downloading from Stellarium's repo when needed. Follows the same pattern as existing bundled catalogs (openngc.csv, sac.csv, caldwell.csv).

### 2. Parser Module

New file: `backend/app/services/stellarium_names.py`

Exposes a single function: `get_stellarium_names() -> dict[str, str]`

Returns a lazy-initialized singleton dict mapping lowercase common names to SIMBAD-compatible catalog IDs. Parsed once on first access, cached in module state.

#### Parsing logic

The names.dat file uses fixed-width format:
- Bytes 0-4: catalog prefix (e.g., `NGC `, `SH2 `, `B   `)
- Bytes 5-19: object ID within catalog (space-padded)
- Bytes 20+: name in `_("Name Here")` format, optionally followed by `# SOURCE_CODES`

Parser steps per line:
1. Skip comment lines (starting with `#`) and blank lines
2. Extract prefix from bytes 0-4, strip whitespace
3. Extract ID from bytes 5-19, strip whitespace
4. Extract common name from `_("...")` wrapper using regex
5. Convert prefix + ID to SIMBAD-compatible format using prefix mapping
6. Store `{lowercase_name: simbad_id}` in the dict
7. If the same name already exists in the dict (duplicate common name for different objects), keep the first occurrence (Stellarium lists preferred entries first)

#### Prefix to SIMBAD format mapping

```python
PREFIX_MAP = {
    "NGC":  lambda id: f"NGC {id}",
    "IC":   lambda id: f"IC {id}",
    "M":    lambda id: f"M {id}",
    "SH2":  lambda id: f"Sh2-{id}",
    "B":    lambda id: f"Barnard {id}",
    "CR":   lambda id: f"Collinder {id}",
    "MEL":  lambda id: f"Melotte {id}",
    "LDN":  lambda id: f"LDN {id}",
    "LBN":  lambda id: f"LBN {id}",
    "RCW":  lambda id: f"RCW {id}",
    "VDB":  lambda id: f"vdB {id}",
    "CED":  lambda id: f"Ced {id}",
    "GUM":  lambda id: f"Gum {id}",
    "PAL":  lambda id: f"Palomar {id}",
    "ST":   lambda id: f"Stock {id}",
    "ACO":  lambda id: f"ACO {id}",
    "PGC":  lambda id: f"PGC {id}",
    "HCG":  lambda id: f"HCG {id}",
    "ARP":  lambda id: f"Arp {id}",
    "DWB":  lambda id: f"DWB {id}",
    "SNRG": lambda id: f"SNR G{id}",
}
```

Prefixes not in the map are formatted as `"{PREFIX} {ID}"` as a fallback.

### 3. Integration into `_get_simbad_id()`

Current lookup order in `_get_simbad_id()`:
1. Normalize input
2. Check `COMMON_NAME_MAP` (93 entries)
3. Format normalization (Sharpless regex, LBN regex, panel stripping)
4. Return to SIMBAD as-is

New lookup order:
1. Normalize input
2. Check `COMMON_NAME_MAP` (~15 entries, abbreviations and overrides only)
3. **Check Stellarium names dict** (~1,364 entries)
4. Format normalization (Sharpless regex, LBN regex, panel stripping)
5. Return to SIMBAD as-is

The Stellarium lookup is a single dict access, O(1).

### 4. Reduced COMMON_NAME_MAP

The current 93-entry map is reduced to entries that are:
- Abbreviations not in Stellarium (e.g., `"rho oph": "rho Oph"`)
- Format shortcuts that users type (e.g., catalog number without spaces)
- Corrections where GalactiLog needs to override Stellarium's mapping
- Names using the `"NAME ..."` SIMBAD format (e.g., `"markarian's chain": "NAME Markarian Chain"`)

All entries that duplicate what Stellarium provides are removed. The exact list will be determined during implementation by cross-referencing the current map against the parsed Stellarium data.

### 5. Data Migration

`DATA_VERSION` bumped to 9.

Migration v9 clears SIMBAD cache entries for common names that now resolve differently through the Stellarium lookup. Specifically:
- Iterate all entries in the Stellarium names dict
- For each common name, check if it exists in `simbad_cache` with a different `main_id` than what Stellarium maps to
- Delete mismatched cache entries so they get re-resolved on next smart rebuild

The automatic post-migration smart rebuild will then re-derive target aliases using the corrected name mappings.

### 6. Testing

- Unit test for the parser: verify it correctly parses sample lines from names.dat, handles all prefix formats, handles duplicate names, skips comments
- Unit test for prefix mapping: verify each prefix produces the correct SIMBAD-compatible format
- Integration test: verify `_get_simbad_id("Question Mark Galaxy")` returns `"NGC 5194"` (not `"NGC 4258"`)
- Integration test: verify `_get_simbad_id("Horsehead Nebula")` returns `"Barnard 33"`
- Verify COMMON_NAME_MAP entries still override Stellarium when both have an entry
