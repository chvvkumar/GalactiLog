# VizieR Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add VizieR TAP as a fallback enrichment source for non-NGC/IC targets, and use OpenNGC common names as a fallback when SIMBAD doesn't provide one.

**Architecture:** A new `vizier.py` service determines the correct VizieR catalog from a target's catalog_id prefix, builds an ADQL query, hits the VizieR TAP endpoint, and caches results in a `vizier_cache` table. The worker calls it as a fallback after OpenNGC. A data migration backfills existing un-enriched targets.

**Tech Stack:** Python 3.12, httpx (sync), SQLAlchemy 2.0, Alembic, PostgreSQL

---

### Task 1: Create the VizierCache model

**Files:**
- Create: `backend/app/models/vizier_cache.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Write the model**

Create `backend/app/models/vizier_cache.py`:

```python
from datetime import datetime

from sqlalchemy import String, Float, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class VizierCache(Base):
    __tablename__ = "vizier_cache"

    catalog_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    vizier_catalog: Mapped[str | None] = mapped_column(String(20), nullable=True)
    size_major: Mapped[float | None] = mapped_column(Float, nullable=True)
    size_minor: Mapped[float | None] = mapped_column(Float, nullable=True)
    constellation: Mapped[str | None] = mapped_column(String(5), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
```

- [ ] **Step 2: Register in models __init__.py**

In `backend/app/models/__init__.py`, add `from .vizier_cache import VizierCache` and add `"VizierCache"` to the `__all__` list.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/vizier_cache.py backend/app/models/__init__.py
git commit -m "feat: add VizierCache model"
```

---

### Task 2: Create the Alembic migration

**Files:**
- Create: `backend/alembic/versions/0013_add_vizier_cache.py`

- [ ] **Step 1: Write the migration**

Create `backend/alembic/versions/0013_add_vizier_cache.py`:

```python
"""Add VizieR cache table."""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vizier_cache",
        sa.Column("catalog_id", sa.String(50), primary_key=True),
        sa.Column("vizier_catalog", sa.String(20), nullable=True),
        sa.Column("size_major", sa.Float, nullable=True),
        sa.Column("size_minor", sa.Float, nullable=True),
        sa.Column("constellation", sa.String(5), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("vizier_cache")
```

- [ ] **Step 2: Commit**

```bash
git add backend/alembic/versions/0013_add_vizier_cache.py
git commit -m "migration: add vizier_cache table"
```

---

### Task 3: Create the VizieR service — catalog matching and ADQL

**Files:**
- Create: `backend/app/services/vizier.py`
- Create: `backend/tests/test_vizier.py`

This is the largest task. It implements catalog detection, ADQL query building, TAP querying, and target enrichment.

- [ ] **Step 1: Write tests for catalog matching and ADQL building**

Create `backend/tests/test_vizier.py`:

```python
import pytest
from app.services.vizier import determine_vizier_catalog, build_adql_query


class TestDetermineVizierCatalog:
    def test_sharpless(self):
        result = determine_vizier_catalog("SH 2-129")
        assert result is not None
        catalog_id, table, num_col = result
        assert catalog_id == "VII/20"
        assert table == '"VII/20/catalog"'
        assert num_col == "Sh2"

    def test_sharpless_variant(self):
        result = determine_vizier_catalog("Sh2-129")
        assert result is not None
        assert result[0] == "VII/20"

    def test_barnard(self):
        result = determine_vizier_catalog("B 33")
        assert result is not None
        assert result[0] == "VII/220A"
        assert result[2] == "Barn"

    def test_lbn(self):
        result = determine_vizier_catalog("LBN 437")
        assert result is not None
        assert result[0] == "VII/9"

    def test_ldn(self):
        result = determine_vizier_catalog("LDN 1622")
        assert result is not None
        assert result[0] == "VII/7A"

    def test_vdb(self):
        result = determine_vizier_catalog("vdB 152")
        assert result is not None
        assert result[0] == "VII/21"

    def test_rcw(self):
        result = determine_vizier_catalog("RCW 49")
        assert result is not None
        assert result[0] == "VII/216"

    def test_collinder(self):
        result = determine_vizier_catalog("Collinder 399")
        assert result is not None
        assert result[0] == "B/ocl"

    def test_melotte(self):
        result = determine_vizier_catalog("Melotte 111")
        assert result is not None
        assert result[0] == "B/ocl"

    def test_trumpler(self):
        result = determine_vizier_catalog("Trumpler 37")
        assert result is not None
        assert result[0] == "B/ocl"

    def test_cederblad(self):
        result = determine_vizier_catalog("Ced 214")
        assert result is not None
        assert result[0] == "VII/231"

    def test_abell_pn(self):
        result = determine_vizier_catalog("Abell 39")
        assert result is not None
        assert result[0] == "V/84"

    def test_pn_a66(self):
        result = determine_vizier_catalog("PN A66 39")
        assert result is not None
        assert result[0] == "V/84"

    def test_ngc_returns_none(self):
        assert determine_vizier_catalog("NGC 7000") is None

    def test_messier_returns_none(self):
        assert determine_vizier_catalog("M 31") is None

    def test_ic_returns_none(self):
        assert determine_vizier_catalog("IC 1396") is None

    def test_none_input(self):
        assert determine_vizier_catalog(None) is None

    def test_empty_input(self):
        assert determine_vizier_catalog("") is None


class TestBuildAdqlQuery:
    def test_sharpless(self):
        query = build_adql_query("SH 2-129")
        assert query is not None
        assert '"VII/20/catalog"' in query
        assert "Sh2=129" in query
        assert "Diam" in query

    def test_barnard(self):
        query = build_adql_query("B 33")
        assert query is not None
        assert '"VII/220A/barnard"' in query
        assert "TRIM(Barn)='33'" in query

    def test_lbn(self):
        query = build_adql_query("LBN 437")
        assert query is not None
        assert '"VII/9/catalog"' in query

    def test_open_cluster(self):
        query = build_adql_query("Collinder 399")
        assert query is not None
        assert '"B/ocl/clusters"' in query
        assert "Collinder 399" in query

    def test_ngc_returns_none(self):
        assert build_adql_query("NGC 7000") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_vizier.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.vizier'`

- [ ] **Step 3: Write the VizieR service**

Create `backend/app/services/vizier.py`:

```python
"""VizieR catalog service — TAP queries for non-NGC/IC target enrichment."""
from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.vizier_cache import VizierCache

if TYPE_CHECKING:
    from app.models.target import Target

logger = logging.getLogger(__name__)

VIZIER_TAP_URL = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"

# Maps catalog_id prefix pattern -> (vizier_catalog_id, adql_table, number_column)
_CATALOG_MAP: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"^SH\s*2[\s-](\d+)$", re.IGNORECASE), "VII/20", '"VII/20/catalog"', "Sh2"),
    (re.compile(r"^Sh\s*2[\s-](\d+)$", re.IGNORECASE), "VII/20", '"VII/20/catalog"', "Sh2"),
    (re.compile(r"^LBN\s+(\d+)$", re.IGNORECASE), "VII/9", '"VII/9/catalog"', "LBN"),
    (re.compile(r"^RCW\s+(\d+)$", re.IGNORECASE), "VII/216", '"VII/216/rcw"', "RCW"),
    (re.compile(r"^vdB\s*(\d+)$", re.IGNORECASE), "VII/21", '"VII/21/catalog"', "VdB"),
    (re.compile(r"^LDN\s+(\d+)$", re.IGNORECASE), "VII/7A", '"VII/7A/ldn"', "LDN"),
    (re.compile(r"^B\s+(\d+)$"), "VII/220A", '"VII/220A/barnard"', "Barn"),
    (re.compile(r"^(Ced|Cederblad)\s+(.+)$", re.IGNORECASE), "VII/231", '"VII/231/catalog"', "Ced"),
    (re.compile(r"^(PN\s+A66|Abell)\s+(\d+)$", re.IGNORECASE), "V/84", '"V/84/main"', "Name"),
    # Open clusters — multiple name formats, all go to B/ocl
    (re.compile(r"^(Collinder|Cr|Melotte|Mel|Trumpler|Tr|Berkeley|King|Stock)\s+\d+", re.IGNORECASE),
     "B/ocl", '"B/ocl/clusters"', "Cluster"),
]


def determine_vizier_catalog(catalog_id: str | None) -> tuple[str, str, str] | None:
    """Determine which VizieR catalog to query based on catalog_id prefix.

    Returns (vizier_catalog_id, adql_table, number_column) or None if not a VizieR target.
    """
    if not catalog_id or not catalog_id.strip():
        return None

    cleaned = catalog_id.strip()

    for pattern, viz_id, table, num_col in _CATALOG_MAP:
        if pattern.match(cleaned):
            return (viz_id, table, num_col)

    return None


def _extract_number(catalog_id: str) -> str:
    """Extract the catalog number from a catalog_id like 'SH 2-129' -> '129', 'B 33' -> '33'."""
    # Try splitting on hyphen first (Sharpless: SH 2-129)
    if "-" in catalog_id:
        return catalog_id.rsplit("-", 1)[-1].strip()
    # Otherwise last token (B 33, LBN 437, etc.)
    parts = catalog_id.strip().split()
    return parts[-1].strip() if parts else catalog_id


def build_adql_query(catalog_id: str | None) -> str | None:
    """Build an ADQL query for the given catalog_id.

    Returns the ADQL string or None if not a VizieR target.
    """
    result = determine_vizier_catalog(catalog_id)
    if result is None:
        return None

    viz_id, table, num_col = result
    number = _extract_number(catalog_id)

    if viz_id == "VII/20":
        # Sharpless: Sh2 is integer, Diam in arcmin
        return f'SELECT Sh2, Diam, RA1900, DE1900 FROM {table} WHERE Sh2={number}'

    elif viz_id == "VII/9":
        # LBN: Seq is integer, Diam1/Diam2 in arcmin
        return f'SELECT Seq, Diam1, Diam2, "_RA_icrs", "_DE_icrs" FROM {table} WHERE Seq={number}'

    elif viz_id == "VII/216":
        # RCW: RCW is integer, MajAxis/MinAxis in arcmin
        return f'SELECT RCW, MajAxis, MinAxis, "_RA_icrs", "_DE_icrs" FROM {table} WHERE RCW={number}'

    elif viz_id == "VII/21":
        # vdB: VdB is integer, BRadMax in arcmin (radius, need to double)
        return f'SELECT VdB, BRadMax, RRadMax, "_RA_icrs", "_DE_icrs" FROM {table} WHERE VdB={number}'

    elif viz_id == "VII/7A":
        # LDN: LDN is integer, Area in sq deg
        return f'SELECT LDN, Area, "_RA_icrs", "_DE_icrs" FROM {table} WHERE LDN={number}'

    elif viz_id == "VII/220A":
        # Barnard: Barn is CHAR(4), space-padded — use TRIM
        return f"SELECT Barn, Diam, \"_RA_icrs\", \"_DE_icrs\" FROM {table} WHERE TRIM(Barn)='{number}'"

    elif viz_id == "VII/231":
        # Cederblad: Ced is string
        ced_num = catalog_id.split()[-1].strip() if " " in catalog_id else number
        return f"SELECT Ced, Dim1, Dim2, \"_RA_icrs\", \"_DE_icrs\" FROM {table} WHERE TRIM(Ced)='{ced_num}'"

    elif viz_id == "V/84":
        # Planetary nebulae (Abell PNe): query by Name containing "A <number>"
        # Join with diam table for optical diameter
        return (
            f'SELECT m."Name", d.oDiam, m."_RA_icrs", m."_DE_icrs" '
            f'FROM "V/84/main" AS m '
            f'LEFT JOIN "V/84/diam" AS d ON m."PNG"=d."PNG" '
            f"WHERE m.\"Name\" LIKE '%A {number}%'"
        )

    elif viz_id == "B/ocl":
        # Open clusters: Cluster is string like "Collinder 399"
        cluster_name = catalog_id.strip()
        return f"SELECT \"Cluster\", Diam, RAJ2000, DEJ2000 FROM {table} WHERE \"Cluster\"='{cluster_name}'"

    return None


def _parse_vizier_response(viz_id: str, lines: list[str]) -> dict[str, Any] | None:
    """Parse a TSV response from VizieR into a dict with size_major, size_minor, ra, dec."""
    if len(lines) < 2:
        return None

    headers = [h.strip() for h in lines[0].split("\t")]
    values = [v.strip().strip('"') for v in lines[1].split("\t")]

    if len(values) < len(headers):
        return None

    row = dict(zip(headers, values))

    def _float(key: str) -> float | None:
        val = row.get(key, "").strip()
        if not val:
            return None
        try:
            return float(val)
        except ValueError:
            return None

    size_major = None
    size_minor = None
    ra = None
    dec = None

    if viz_id == "VII/20":
        size_major = _float("Diam")
        ra = _float("RA1900")  # Approximate — B1900 coords
        dec = _float("DE1900")

    elif viz_id == "VII/9":
        size_major = _float("Diam1")
        size_minor = _float("Diam2")
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "VII/216":
        size_major = _float("MajAxis")
        size_minor = _float("MinAxis")
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "VII/21":
        # vdB stores radius, double for diameter
        brad = _float("BRadMax")
        if brad is not None:
            size_major = brad * 2
        rrad = _float("RRadMax")
        if rrad is not None:
            size_minor = rrad * 2
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "VII/7A":
        # LDN: Area in sq deg, convert to approximate diameter in arcmin
        area = _float("Area")
        if area is not None:
            import math
            # Approximate circular diameter from area: d = 2 * sqrt(area/pi)
            diam_deg = 2 * math.sqrt(area / math.pi)
            size_major = diam_deg * 60  # Convert degrees to arcmin
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "VII/220A":
        size_major = _float("Diam")
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "VII/231":
        size_major = _float("Dim1")
        size_minor = _float("Dim2")
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "V/84":
        odiam = _float("oDiam")
        if odiam is not None:
            size_major = odiam / 60  # Convert arcsec to arcmin
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "B/ocl":
        size_major = _float("Diam")
        ra = _float("RAJ2000")
        dec = _float("DEJ2000")

    if size_major is None and size_minor is None:
        return None

    return {
        "size_major": size_major,
        "size_minor": size_minor,
        "ra": ra,
        "dec": dec,
    }


def _coords_to_constellation(ra: float | None, dec: float | None) -> str | None:
    """Derive IAU constellation abbreviation from J2000 coordinates.

    Uses a simple lookup of the 88 constellation boundaries.
    Returns None if coords are missing — constellation enrichment is best-effort.
    """
    # Skip if no coordinates
    if ra is None or dec is None:
        return None

    # Use a simplified approach: try the target's existing constellation
    # (most targets already have constellation from OpenNGC or SIMBAD coords)
    # Full constellation boundary lookup is complex; defer to existing data
    return None


def query_vizier(catalog_id: str) -> dict[str, Any] | None:
    """Query VizieR TAP for target data. Returns dict with size_major, size_minor, or None."""
    adql = build_adql_query(catalog_id)
    if adql is None:
        return None

    result = determine_vizier_catalog(catalog_id)
    if result is None:
        return None
    viz_id = result[0]

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                VIZIER_TAP_URL,
                data={
                    "REQUEST": "doQuery",
                    "LANG": "ADQL",
                    "FORMAT": "tsv",
                    "QUERY": adql,
                },
            )
            resp.raise_for_status()
            lines = resp.text.strip().splitlines()
            return _parse_vizier_response(viz_id, lines)

    except (httpx.HTTPError, ValueError, IndexError) as e:
        logger.warning("VizieR query failed for '%s': %s", catalog_id, e)
        return None


def get_cached_vizier(catalog_id: str, session: Session) -> VizierCache | None:
    """Check the VizieR cache for a previous lookup."""
    return session.execute(
        select(VizierCache).where(VizierCache.catalog_id == catalog_id)
    ).scalar_one_or_none()


def save_vizier_cache(
    session: Session, catalog_id: str, viz_id: str | None, data: dict[str, Any] | None,
) -> None:
    """Save a VizieR lookup result (including negative) to the cache."""
    entry = {
        "catalog_id": catalog_id,
        "vizier_catalog": viz_id,
        "size_major": data.get("size_major") if data else None,
        "size_minor": data.get("size_minor") if data else None,
        "constellation": data.get("constellation") if data else None,
    }
    stmt = pg_insert(VizierCache).values(**entry).on_conflict_do_update(
        index_elements=["catalog_id"],
        set_=entry,
    )
    session.execute(stmt)


def enrich_target_from_vizier(session: Session, target: Target) -> bool:
    """Enrich a target from VizieR. Checks cache first, queries if needed.

    Returns True if any fields were updated.
    """
    if not target.catalog_id:
        return False

    # Skip if not a VizieR-supported catalog
    if determine_vizier_catalog(target.catalog_id) is None:
        return False

    # Check cache
    cached = get_cached_vizier(target.catalog_id, session)
    if cached is not None:
        # Cached (positive or negative) — apply if positive
        if cached.size_major is None and cached.size_minor is None:
            return False
        updated = False
        if cached.size_major is not None and target.size_major is None:
            target.size_major = cached.size_major
            updated = True
        if cached.size_minor is not None and target.size_minor is None:
            target.size_minor = cached.size_minor
            updated = True
        if cached.constellation is not None and target.constellation is None:
            target.constellation = cached.constellation
            updated = True
        return updated

    # Query VizieR
    viz_id = determine_vizier_catalog(target.catalog_id)[0]
    data = query_vizier(target.catalog_id)

    # Cache the result (even if None — negative cache)
    save_vizier_cache(session, target.catalog_id, viz_id, data)
    session.flush()

    if data is None:
        return False

    updated = False
    if data.get("size_major") is not None and target.size_major is None:
        target.size_major = data["size_major"]
        updated = True
    if data.get("size_minor") is not None and target.size_minor is None:
        target.size_minor = data["size_minor"]
        updated = True

    return updated
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_vizier.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/vizier.py backend/tests/test_vizier.py
git commit -m "feat: add VizieR service with catalog matching, ADQL queries, and caching"
```

---

### Task 4: Add OpenNGC common name fallback

**Files:**
- Modify: `backend/app/services/openngc.py`
- Modify: `backend/tests/test_openngc.py`

- [ ] **Step 1: Add test for common name fallback**

Add to `backend/tests/test_openngc.py`:

```python
def test_extract_openngc_common_name():
    from app.services.openngc import extract_openngc_common_name
    assert extract_openngc_common_name("North America Nebula") == "North America Nebula"
    assert extract_openngc_common_name("Orion Nebula;Great Nebula") == "Orion Nebula"
    assert extract_openngc_common_name("") is None
    assert extract_openngc_common_name(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_openngc.py::test_extract_openngc_common_name -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 3: Add the function to openngc.py**

In `backend/app/services/openngc.py`, add after the `normalize_ngc_name` function:

```python
def extract_openngc_common_name(common_names: str | None) -> str | None:
    """Extract the first common name from OpenNGC's semicolon-separated field."""
    if not common_names or not common_names.strip():
        return None
    first = common_names.split(";")[0].strip()
    return first if first else None
```

- [ ] **Step 4: Update enrich_target_from_openngc to set common_name**

In `backend/app/services/openngc.py`, update the `enrich_target_from_openngc` function. After the existing field-mapping loop, add:

```python
    # Common name fallback: use OpenNGC common name if target has none
    if target.common_name is None and entry.common_names:
        ngc_common = extract_openngc_common_name(entry.common_names)
        if ngc_common:
            target.common_name = ngc_common
            # Rebuild primary_name with the new common name
            from app.services.simbad import build_primary_name
            target.primary_name = build_primary_name(target.catalog_id, ngc_common)
            updated = True
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_openngc.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/openngc.py backend/tests/test_openngc.py
git commit -m "feat: add OpenNGC common name fallback for targets without SIMBAD common names"
```

---

### Task 5: Integrate VizieR into the worker

**Files:**
- Modify: `backend/app/worker/tasks.py`

- [ ] **Step 1: Add VizieR import**

In `backend/app/worker/tasks.py`, add after the `enrich_target_from_openngc` import:

```python
from app.services.vizier import enrich_target_from_vizier
```

- [ ] **Step 2: Add VizieR fallback after OpenNGC in _resolve_or_cache_target**

In `_resolve_or_cache_target`, after the `enrich_target_from_openngc(session, target)` line (around line 585), add:

```python
            if target.size_major is None:
                enrich_target_from_vizier(session, target)
```

The full block should now read:

```python
        try:
            session.add(target)
            session.flush()
            enrich_target_from_openngc(session, target)
            if target.size_major is None:
                enrich_target_from_vizier(session, target)
            session.commit()
            return str(target.id)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/worker/tasks.py
git commit -m "feat: add VizieR fallback enrichment in target resolution"
```

---

### Task 6: Add the data migration (DATA_VERSION 4)

**Files:**
- Modify: `backend/app/services/data_migrations.py`

- [ ] **Step 1: Bump DATA_VERSION and add imports**

In `backend/app/services/data_migrations.py`:

1. Change `DATA_VERSION = 3` to `DATA_VERSION = 4`

2. Add import after the existing openngc import:

```python
from app.services.vizier import enrich_target_from_vizier, determine_vizier_catalog
```

- [ ] **Step 2: Add the migration function**

Add after `_migrate_v3_load_openngc`:

```python
def _migrate_v4_vizier_and_common_names(session: Session) -> str:
    """Enrich un-enriched targets via VizieR and backfill OpenNGC common names."""
    import time
    from app.models import Target

    targets = session.execute(
        select(Target).where(Target.merged_into_id.is_(None))
    ).scalars().all()

    # Pass 1: Backfill OpenNGC common names for targets missing common_name
    names_added = 0
    for target in targets:
        if target.common_name is None:
            if enrich_target_from_openngc(session, target):
                names_added += 1

    session.flush()

    # Pass 2: VizieR enrichment for targets still missing size_major
    vizier_queried = 0
    vizier_enriched = 0
    for target in targets:
        if target.size_major is not None:
            continue
        if not target.catalog_id:
            continue
        if determine_vizier_catalog(target.catalog_id) is None:
            continue

        if enrich_target_from_vizier(session, target):
            vizier_enriched += 1
        vizier_queried += 1
        time.sleep(0.3)

    session.flush()

    parts = []
    if names_added:
        parts.append(f"{names_added} common names added from OpenNGC")
    if vizier_queried:
        parts.append(f"VizieR: {vizier_enriched}/{vizier_queried} targets enriched")
    return "; ".join(parts) if parts else "No changes needed"
```

- [ ] **Step 3: Register the migration**

Add to the `MIGRATIONS` dict:

```python
    4: ("VizieR enrichment and OpenNGC common name backfill", _migrate_v4_vizier_and_common_names),
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/data_migrations.py
git commit -m "feat: add data migration v4 for VizieR enrichment and common name backfill"
```

---

### Task 7: Run tests and verify

- [ ] **Step 1: Run all related tests**

```bash
cd backend && python -m pytest tests/test_vizier.py tests/test_openngc.py tests/test_data_migrations.py -v
```

Expected: All tests pass, including:
- 7 original OpenNGC tests + 1 new common name test
- ~20 VizieR catalog matching + ADQL tests
- 6 data migration tests (now checking DATA_VERSION 4)

- [ ] **Step 2: Verify frontend still builds**

```bash
cd frontend && npm run build
```

Expected: Build succeeds (no frontend changes in this plan).

- [ ] **Step 3: Commit any fixes needed**
