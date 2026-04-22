# Stellarium Common Names Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-maintained COMMON_NAME_MAP with Stellarium's names.dat (~1,364 common name mappings) for reliable deep sky object name resolution.

**Architecture:** Bundle Stellarium's names.dat file, parse it into an in-memory dict at first access, integrate into `_get_simbad_id()` as a lookup step between the small override map and SIMBAD, and add a data migration to clear stale cache entries.

**Tech Stack:** Python 3.12, pytest, SQLAlchemy 2.0 (sync sessions in Celery tasks)

**Spec:** `guides/superpowers/specs/2026-04-21-stellarium-common-names-design.md`

---

## File Structure

### New files
- `backend/data/catalogs/names.dat` - Stellarium's common name database (bundled)
- `backend/app/services/stellarium_names.py` - Parser module with lazy singleton
- `backend/tests/test_stellarium_names.py` - Parser and integration tests

### Modified files
- `backend/app/services/simbad.py:298-428` - Reduce COMMON_NAME_MAP, integrate Stellarium lookup into `_get_simbad_id()`
- `backend/app/services/data_migrations.py:24,381-390` - Bump DATA_VERSION to 9, add migration function

---

### Task 1: Bundle Stellarium's names.dat

**Files:**
- Create: `backend/data/catalogs/names.dat`

- [ ] **Step 1: Download names.dat from Stellarium's repository**

Run: `cd backend/data/catalogs && curl -o names.dat https://raw.githubusercontent.com/Stellarium/stellarium/master/nebulae/default/names.dat`

Verify the file was downloaded and has content:
Run: `wc -l backend/data/catalogs/names.dat`
Expected: ~1584 lines

- [ ] **Step 2: Commit**

```bash
git add backend/data/catalogs/names.dat
git commit -m "feat: bundle Stellarium names.dat for common name resolution"
```

---

### Task 2: Parser Module with Tests

**Files:**
- Create: `backend/app/services/stellarium_names.py`
- Create: `backend/tests/test_stellarium_names.py`

- [ ] **Step 1: Write the parser tests**

Create `backend/tests/test_stellarium_names.py`:

```python
import pytest
from app.services.stellarium_names import parse_names_dat, get_stellarium_names


class TestParseNamesDat:
    def test_parses_ngc_entry(self):
        lines = ['NGC  40              _("Bow-Tie Nebula") # ESKY, B500']
        result = parse_names_dat(lines)
        assert result["bow-tie nebula"] == "NGC 40"

    def test_parses_messier_entry(self):
        lines = ['M    8               _("Lagoon Nebula") # WK, DSW']
        result = parse_names_dat(lines)
        assert result["lagoon nebula"] == "M 8"

    def test_parses_sharpless_entry(self):
        lines = ['SH2  129             _("Flying Bat Nebula") # APOD']
        result = parse_names_dat(lines)
        assert result["flying bat nebula"] == "Sh2-129"

    def test_parses_barnard_entry(self):
        lines = ['B    33              _("Horsehead Nebula") # WK']
        result = parse_names_dat(lines)
        assert result["horsehead nebula"] == "Barnard 33"

    def test_parses_collinder_entry(self):
        lines = ['CR   69              _("Orion Cluster")']
        result = parse_names_dat(lines)
        assert result["orion cluster"] == "Collinder 69"

    def test_parses_ic_entry(self):
        lines = ['IC   405             _("Flaming Star Nebula") # WK']
        result = parse_names_dat(lines)
        assert result["flaming star nebula"] == "IC 405"

    def test_parses_lbn_entry(self):
        lines = ['LBN  437             _("Gecko Nebula") # WK']
        result = parse_names_dat(lines)
        assert result["gecko nebula"] == "LBN 437"

    def test_parses_ldn_entry(self):
        lines = ['LDN  1622            _("Boogie Man Nebula")']
        result = parse_names_dat(lines)
        assert result["boogie man nebula"] == "LDN 1622"

    def test_parses_rcw_entry(self):
        lines = ['RCW  114             _("Dragon\'s Heart Nebula") # APOD']
        result = parse_names_dat(lines)
        assert result["dragon's heart nebula"] == "RCW 114"

    def test_parses_vdb_entry(self):
        lines = ['VDB  142             _("Elephant\'s Trunk") # MISC']
        result = parse_names_dat(lines)
        assert result["elephant's trunk"] == "vdB 142"

    def test_parses_pgc_entry(self):
        lines = ['PGC  50779           _("Circinus Galaxy") # NED']
        result = parse_names_dat(lines)
        assert result["circinus galaxy"] == "PGC 50779"

    def test_parses_arp_entry(self):
        lines = ['ARP  244             _("Antennae Galaxies") # NED']
        result = parse_names_dat(lines)
        assert result["antennae galaxies"] == "Arp 244"

    def test_skips_comment_lines(self):
        lines = [
            "# This is a comment",
            'NGC  40              _("Bow-Tie Nebula")',
        ]
        result = parse_names_dat(lines)
        assert len(result) == 1
        assert "bow-tie nebula" in result

    def test_skips_blank_lines(self):
        lines = [
            "",
            'NGC  40              _("Bow-Tie Nebula")',
            "   ",
        ]
        result = parse_names_dat(lines)
        assert len(result) == 1

    def test_multiple_names_same_object(self):
        lines = [
            'NGC  40              _("Bow-Tie Nebula")',
            'NGC  40              _("Scarab Nebula")',
        ]
        result = parse_names_dat(lines)
        assert result["bow-tie nebula"] == "NGC 40"
        assert result["scarab nebula"] == "NGC 40"

    def test_duplicate_name_different_objects_keeps_first(self):
        lines = [
            'SH2  155             _("Cave Nebula")',
            'LBN  531             _("Cave Nebula")',
        ]
        result = parse_names_dat(lines)
        assert result["cave nebula"] == "Sh2-155"

    def test_unknown_prefix_uses_fallback(self):
        lines = ['XCAT 99              _("Test Object")']
        result = parse_names_dat(lines)
        assert result["test object"] == "XCAT 99"

    def test_question_mark_galaxy_is_m51(self):
        lines = ['NGC  5194            _("Question Mark Galaxy")']
        result = parse_names_dat(lines)
        assert result["question mark galaxy"] == "NGC 5194"


class TestGetStellariumNames:
    def test_returns_dict(self):
        names = get_stellarium_names()
        assert isinstance(names, dict)
        assert len(names) > 100

    def test_contains_well_known_objects(self):
        names = get_stellarium_names()
        assert "horsehead nebula" in names
        assert "andromeda galaxy" in names
        assert "pleiades" in names

    def test_singleton_returns_same_object(self):
        a = get_stellarium_names()
        b = get_stellarium_names()
        assert a is b
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_stellarium_names.py -v`
Expected: FAIL (module does not exist)

- [ ] **Step 3: Implement the parser module**

Create `backend/app/services/stellarium_names.py`:

```python
import re
import os
from pathlib import Path

_NAME_RE = re.compile(r'_\("(.+?)"\)')

PREFIX_MAP = {
    "NGC":  "NGC",
    "IC":   "IC",
    "M":    "M",
    "SH2":  "Sh2-",
    "B":    "Barnard",
    "CR":   "Collinder",
    "MEL":  "Melotte",
    "LDN":  "LDN",
    "LBN":  "LBN",
    "RCW":  "RCW",
    "VDB":  "vdB",
    "CED":  "Ced",
    "GUM":  "Gum",
    "PAL":  "Palomar",
    "ST":   "Stock",
    "ACO":  "ACO",
    "PGC":  "PGC",
    "HCG":  "HCG",
    "ARP":  "Arp",
    "DWB":  "DWB",
    "SNRG": "SNR G",
}

_HYPHENATED = {"Sh2-"}


def _to_simbad_id(prefix: str, obj_id: str) -> str:
    mapped = PREFIX_MAP.get(prefix.upper(), prefix)
    if mapped in _HYPHENATED:
        return f"{mapped}{obj_id}"
    return f"{mapped} {obj_id}"


def parse_names_dat(lines: list[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for line in lines:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if len(line) < 21:
            continue
        prefix = line[0:5].strip()
        obj_id = line[5:20].strip()
        remainder = line[20:]
        match = _NAME_RE.search(remainder)
        if not match or not prefix or not obj_id:
            continue
        common_name = match.group(1).lower()
        if common_name not in names:
            simbad_id = _to_simbad_id(prefix, obj_id)
            names[common_name] = simbad_id
    return names


_cache: dict[str, str] | None = None


def get_stellarium_names() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache
    dat_path = Path(__file__).resolve().parent.parent.parent / "data" / "catalogs" / "names.dat"
    with open(dat_path, encoding="utf-8") as f:
        _cache = parse_names_dat(f.readlines())
    return _cache
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_stellarium_names.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/stellarium_names.py backend/tests/test_stellarium_names.py
git commit -m "feat: add Stellarium names.dat parser with lazy singleton"
```

---

### Task 3: Integrate into `_get_simbad_id()` and Reduce COMMON_NAME_MAP

**Files:**
- Modify: `backend/app/services/simbad.py:298-428`
- Modify: `backend/tests/test_simbad.py`

- [ ] **Step 1: Write integration tests**

Add to `backend/tests/test_simbad.py`:

```python
from app.services.simbad import _get_simbad_id


class TestGetSimbadId:
    def test_stellarium_common_name(self):
        assert _get_simbad_id("Horsehead Nebula") == "Barnard 33"

    def test_stellarium_case_insensitive(self):
        assert _get_simbad_id("horsehead nebula") == "Barnard 33"

    def test_override_map_takes_precedence(self):
        assert _get_simbad_id("rho oph") == "rho Oph"

    def test_question_mark_galaxy_resolves_to_m51(self):
        result = _get_simbad_id("Question Mark Galaxy")
        assert result == "NGC 5194"

    def test_catalog_id_passes_through(self):
        assert _get_simbad_id("NGC 7000") == "NGC 7000"

    def test_whirlpool_galaxy(self):
        assert _get_simbad_id("Whirlpool Galaxy") == "NGC 5194"

    def test_andromeda_galaxy(self):
        assert _get_simbad_id("Andromeda Galaxy") == "NGC 224"

    def test_lagoon_nebula(self):
        assert _get_simbad_id("Lagoon Nebula") == "M 8"
```

- [ ] **Step 2: Run tests to see which pass already**

Run: `cd backend && python -m pytest tests/test_simbad.py::TestGetSimbadId -v`
Expected: Some may pass (names already in COMMON_NAME_MAP), others fail (Stellarium-only names)

- [ ] **Step 3: Reduce COMMON_NAME_MAP and integrate Stellarium lookup**

In `backend/app/services/simbad.py`:

First, reduce `COMMON_NAME_MAP` (lines 298-390) to only entries that are abbreviations, format shortcuts, or names not in Stellarium. Read the current map and cross-reference against Stellarium names to determine which to keep. The remaining map should be ~15 entries including:
- `"rho oph": "rho Oph"` (abbreviation)
- `"markarian's chain": "NAME Markarian Chain"` (SIMBAD NAME format)
- Any entries using special SIMBAD identifiers not resolvable via standard catalog IDs
- Remove all Caldwell entries (Stellarium has them or they resolve via NGC)
- Remove all common galaxy/nebula names that Stellarium covers

Then modify `_get_simbad_id()` (lines 400-428) to add the Stellarium lookup after the override map check:

```python
def _get_simbad_id(object_name: str) -> str:
    base = normalize_object_name(object_name, upper=False)
    key = base.lower()

    # 1. Small override map (abbreviations, edge cases)
    if key in COMMON_NAME_MAP:
        return COMMON_NAME_MAP[key]

    # 2. Stellarium common names (~1,364 entries)
    from app.services.stellarium_names import get_stellarium_names
    stellarium = get_stellarium_names()
    if key in stellarium:
        return stellarium[key]

    # 3. Strip suffix after " - " and check both maps
    if " - " in base:
        prefix = base.split(" - ", 1)[0].strip()
        prefix_key = prefix.lower()
        if prefix_key in COMMON_NAME_MAP:
            return COMMON_NAME_MAP[prefix_key]
        if prefix_key in stellarium:
            return stellarium[prefix_key]

    # 4. Existing format normalization (Sharpless, LBN, panel stripping)
    # ... keep existing regex handling unchanged ...

    return base
```

The import is inside the function to avoid circular imports and to keep the lazy initialization pattern.

- [ ] **Step 4: Run all simbad tests**

Run: `cd backend && python -m pytest tests/test_simbad.py -v`
Expected: All tests PASS including the new TestGetSimbadId tests

- [ ] **Step 5: Run the stellarium tests too**

Run: `cd backend && python -m pytest tests/test_stellarium_names.py tests/test_simbad.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/simbad.py backend/tests/test_simbad.py
git commit -m "feat: integrate Stellarium names into _get_simbad_id, reduce COMMON_NAME_MAP"
```

---

### Task 4: Data Migration

**Files:**
- Modify: `backend/app/services/data_migrations.py:24,381-390`

- [ ] **Step 1: Add migration function**

In `backend/app/services/data_migrations.py`, add a new migration function before the MIGRATIONS dict. Read the file first to understand exact structure and imports.

```python
def _migrate_v9_stellarium_names(session: Session) -> str:
    """Clear SIMBAD cache entries for common names that now resolve differently via Stellarium."""
    from app.services.stellarium_names import get_stellarium_names
    from app.models.simbad_cache import SimbadCache

    stellarium = get_stellarium_names()
    cleared = 0

    for common_name, simbad_id in stellarium.items():
        normalized = normalize_object_name(common_name)
        cached = session.execute(
            select(SimbadCache).where(SimbadCache.query_name == normalized)
        ).scalar_one_or_none()

        if cached and cached.main_id and cached.main_id != simbad_id:
            session.delete(cached)
            cleared += 1

    if cleared:
        session.flush()

    return f"Cleared {cleared} stale SIMBAD cache entries for Stellarium name corrections"
```

- [ ] **Step 2: Bump DATA_VERSION and register the migration**

Change `DATA_VERSION = 8` to `DATA_VERSION = 9` (line 24).

Add the new migration to the MIGRATIONS dict:

```python
9: ("Stellarium common name cache refresh", _migrate_v9_stellarium_names),
```

- [ ] **Step 3: Run existing tests to verify nothing breaks**

Run: `cd backend && python -m pytest tests/ -v --timeout=30 -x`
Expected: No new failures

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/data_migrations.py
git commit -m "feat: add data migration v9 for Stellarium name cache refresh"
```

---

### Task 5: Final Verification

**Files:** No changes

- [ ] **Step 1: Run the full test suite**

Run: `cd backend && python -m pytest tests/test_stellarium_names.py tests/test_simbad.py -v`
Expected: All tests PASS

- [ ] **Step 2: Verify key name resolutions**

Run a quick Python check:

```bash
cd backend && python -c "
from app.services.simbad import _get_simbad_id
checks = {
    'Question Mark Galaxy': 'NGC 5194',
    'Horsehead Nebula': 'Barnard 33',
    'Andromeda Galaxy': 'NGC 224',
    'Flying Bat Nebula': 'Sh2-129',
    'Whirlpool Galaxy': 'NGC 5194',
    'rho oph': 'rho Oph',
    'NGC 7000': 'NGC 7000',
}
for name, expected in checks.items():
    result = _get_simbad_id(name)
    status = 'OK' if result == expected else f'FAIL (got {result})'
    print(f'{name}: {status}')
"
```

Expected: All OK

- [ ] **Step 3: Check git log**

Run: `git log --oneline -5`
Expected: 4 clean commits for this feature
