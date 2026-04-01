# OpenNGC Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich Target records with OpenNGC data (angular size, surface brightness, position angle, visual magnitude) and display these fields on the target detail page.

**Architecture:** Bundle OpenNGC CSV in `backend/data/catalogs/`, load into a PostgreSQL reference table via Alembic migration. A new `openngc.py` service handles CSV parsing and target enrichment. A data migration (DATA_VERSION 3) backfills existing targets. The API and frontend surface the 5 new fields inline with RA/Dec.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, Alembic, FastAPI, Pydantic, SolidJS, TypeScript

---

### Task 1: Download and bundle the OpenNGC CSV

**Files:**
- Create: `backend/data/catalogs/openngc.csv`

- [ ] **Step 1: Download the CSV**

```bash
cd backend/data
mkdir -p catalogs
curl -L -o catalogs/openngc.csv "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/NGC.csv"
```

- [ ] **Step 2: Verify the file**

```bash
head -3 backend/data/catalogs/openngc.csv
```

Expected: semicolon-delimited CSV with header row starting with `Name;Type;RA;Dec;...`

- [ ] **Step 3: Commit**

```bash
git add backend/data/catalogs/openngc.csv
git commit -m "data: bundle OpenNGC NGC.csv dataset"
```

---

### Task 2: Create the OpenNGCEntry model

**Files:**
- Create: `backend/app/models/openngc.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Write the model**

Create `backend/app/models/openngc.py`:

```python
from sqlalchemy import String, Float
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class OpenNGCEntry(Base):
    __tablename__ = "openngc_catalog"

    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ra: Mapped[float | None] = mapped_column(Float, nullable=True)
    dec: Mapped[float | None] = mapped_column(Float, nullable=True)
    major_axis: Mapped[float | None] = mapped_column(Float, nullable=True)
    minor_axis: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_angle: Mapped[float | None] = mapped_column(Float, nullable=True)
    b_mag: Mapped[float | None] = mapped_column(Float, nullable=True)
    v_mag: Mapped[float | None] = mapped_column(Float, nullable=True)
    surface_brightness: Mapped[float | None] = mapped_column(Float, nullable=True)
    common_names: Mapped[str | None] = mapped_column(String(500), nullable=True)
    messier: Mapped[str | None] = mapped_column(String(10), nullable=True)
```

- [ ] **Step 2: Register in models __init__.py**

Add to `backend/app/models/__init__.py`:

```python
from .openngc import OpenNGCEntry
```

And add `"OpenNGCEntry"` to the `__all__` list.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/openngc.py backend/app/models/__init__.py
git commit -m "feat: add OpenNGCEntry model for catalog reference data"
```

---

### Task 3: Add new fields to the Target model

**Files:**
- Modify: `backend/app/models/target.py`

- [ ] **Step 1: Add 5 new columns to Target**

Add these columns to the `Target` class in `backend/app/models/target.py`, after the `object_type` field (line 22) and before `merged_into_id`:

```python
    size_major: Mapped[float | None] = mapped_column(Float, nullable=True)
    size_minor: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_angle: Mapped[float | None] = mapped_column(Float, nullable=True)
    v_mag: Mapped[float | None] = mapped_column(Float, nullable=True)
    surface_brightness: Mapped[float | None] = mapped_column(Float, nullable=True)
```

The `Float` import already exists in the file.

- [ ] **Step 2: Commit**

```bash
git add backend/app/models/target.py
git commit -m "feat: add size, magnitude, surface brightness fields to Target model"
```

---

### Task 4: Create the Alembic migration

**Files:**
- Create: `backend/alembic/versions/0012_add_openngc_catalog_and_target_fields.py`

- [ ] **Step 1: Write the migration**

Create `backend/alembic/versions/0012_add_openngc_catalog_and_target_fields.py`:

```python
"""Add OpenNGC reference table and target enrichment fields."""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create OpenNGC reference table
    op.create_table(
        "openngc_catalog",
        sa.Column("name", sa.String(20), primary_key=True),
        sa.Column("type", sa.String(10), nullable=True),
        sa.Column("ra", sa.Float, nullable=True),
        sa.Column("dec", sa.Float, nullable=True),
        sa.Column("major_axis", sa.Float, nullable=True),
        sa.Column("minor_axis", sa.Float, nullable=True),
        sa.Column("position_angle", sa.Float, nullable=True),
        sa.Column("b_mag", sa.Float, nullable=True),
        sa.Column("v_mag", sa.Float, nullable=True),
        sa.Column("surface_brightness", sa.Float, nullable=True),
        sa.Column("common_names", sa.String(500), nullable=True),
        sa.Column("messier", sa.String(10), nullable=True),
    )

    # Add enrichment fields to targets
    op.add_column("targets", sa.Column("size_major", sa.Float, nullable=True))
    op.add_column("targets", sa.Column("size_minor", sa.Float, nullable=True))
    op.add_column("targets", sa.Column("position_angle", sa.Float, nullable=True))
    op.add_column("targets", sa.Column("v_mag", sa.Float, nullable=True))
    op.add_column("targets", sa.Column("surface_brightness", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("targets", "surface_brightness")
    op.drop_column("targets", "v_mag")
    op.drop_column("targets", "position_angle")
    op.drop_column("targets", "size_minor")
    op.drop_column("targets", "size_major")
    op.drop_table("openngc_catalog")
```

- [ ] **Step 2: Commit**

```bash
git add backend/alembic/versions/0012_add_openngc_catalog_and_target_fields.py
git commit -m "migration: add openngc_catalog table and target enrichment columns"
```

---

### Task 5: Create the OpenNGC service

**Files:**
- Create: `backend/app/services/openngc.py`
- Test: `backend/tests/test_openngc.py`

- [ ] **Step 1: Write tests for coordinate parsing and CSV loading**

Create `backend/tests/test_openngc.py`:

```python
import pytest
from app.services.openngc import parse_ra_hms, parse_dec_dms, normalize_ngc_name


def test_parse_ra_hms_valid():
    # 20:59:17.14 -> 20 + 59/60 + 17.14/3600 = 314.821416... degrees
    result = parse_ra_hms("20:59:17.14")
    assert abs(result - 314.8214) < 0.001


def test_parse_ra_hms_zero():
    result = parse_ra_hms("00:00:00.00")
    assert result == 0.0


def test_parse_ra_hms_empty():
    assert parse_ra_hms("") is None
    assert parse_ra_hms(None) is None


def test_parse_dec_dms_positive():
    # +44:31:43.6 -> 44 + 31/60 + 43.6/3600 = 44.5288...
    result = parse_dec_dms("+44:31:43.6")
    assert abs(result - 44.5288) < 0.001


def test_parse_dec_dms_negative():
    # -56:59:11.4 -> -(56 + 59/60 + 11.4/3600) = -56.9865
    result = parse_dec_dms("-56:59:11.4")
    assert abs(result - (-56.9865)) < 0.001


def test_parse_dec_dms_empty():
    assert parse_dec_dms("") is None
    assert parse_dec_dms(None) is None


def test_normalize_ngc_name():
    assert normalize_ngc_name("NGC0031") == "NGC 31"
    assert normalize_ngc_name("IC0002") == "IC 2"
    assert normalize_ngc_name("NGC7000") == "NGC 7000"
    assert normalize_ngc_name("IC1396") == "IC 1396"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_openngc.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.openngc'`

- [ ] **Step 3: Write the OpenNGC service**

Create `backend/app/services/openngc.py`:

```python
"""OpenNGC catalog service — load CSV, lookup, and enrich targets."""

import csv
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.openngc import OpenNGCEntry

logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalogs" / "openngc.csv"

# Pattern to normalize NGC/IC names: strip leading zeros from the number
_NGC_IC_RE = re.compile(r"^(NGC|IC)\s*0*(\d+)([A-Z]?)$", re.IGNORECASE)


def normalize_ngc_name(name: str) -> str:
    """Normalize 'NGC0031' -> 'NGC 31', 'IC0002' -> 'IC 2'."""
    m = _NGC_IC_RE.match(name.strip())
    if m:
        prefix = m.group(1).upper()
        number = m.group(2)
        suffix = m.group(3)
        return f"{prefix} {number}{suffix}"
    return name.strip()


def parse_ra_hms(val: str | None) -> float | None:
    """Parse RA from HH:MM:SS.ss to decimal degrees."""
    if not val or not val.strip():
        return None
    parts = val.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
        return (h + m / 60 + s / 3600) * 15
    except ValueError:
        return None


def parse_dec_dms(val: str | None) -> float | None:
    """Parse Dec from +DD:MM:SS.s to decimal degrees."""
    if not val or not val.strip():
        return None
    text = val.strip()
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-")
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        d, m, s = float(parts[0]), float(parts[1]), float(parts[2])
        return sign * (d + m / 60 + s / 3600)
    except ValueError:
        return None


def _parse_float(val: str | None) -> float | None:
    """Parse a float from a CSV field, returning None for empty/invalid."""
    if not val or not val.strip():
        return None
    try:
        return float(val.strip())
    except ValueError:
        return None


def load_openngc_csv(session: Session) -> int:
    """Load the bundled OpenNGC CSV into the openngc_catalog table.

    Returns the number of rows loaded.
    """
    if not CSV_PATH.exists():
        logger.error("OpenNGC CSV not found at %s", CSV_PATH)
        return 0

    count = 0
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            raw_name = row.get("Name", "").strip()
            if not raw_name:
                continue

            name = normalize_ngc_name(raw_name)
            messier_raw = row.get("M", "").strip()
            messier = f"M {messier_raw}" if messier_raw else None

            entry = {
                "name": name,
                "type": row.get("Type", "").strip() or None,
                "ra": parse_ra_hms(row.get("RA")),
                "dec": parse_dec_dms(row.get("Dec")),
                "major_axis": _parse_float(row.get("MajAx")),
                "minor_axis": _parse_float(row.get("MinAx")),
                "position_angle": _parse_float(row.get("PosAng")),
                "b_mag": _parse_float(row.get("B-Mag")),
                "v_mag": _parse_float(row.get("V-Mag")),
                "surface_brightness": _parse_float(row.get("SurfBr")),
                "common_names": row.get("Common names", "").strip() or None,
                "messier": messier,
            }

            stmt = pg_insert(OpenNGCEntry).values(**entry).on_conflict_do_update(
                index_elements=["name"],
                set_=entry,
            )
            session.execute(stmt)
            count += 1

    session.flush()
    logger.info("Loaded %d OpenNGC entries", count)
    return count


def lookup_openngc(session: Session, catalog_id: str | None) -> OpenNGCEntry | None:
    """Look up an OpenNGC entry by catalog_id (NGC/IC/Messier).

    Tries matching against OpenNGCEntry.name first, then OpenNGCEntry.messier.
    """
    if not catalog_id:
        return None

    normalized = normalize_ngc_name(catalog_id)

    # Direct name match (NGC/IC)
    entry = session.execute(
        select(OpenNGCEntry).where(OpenNGCEntry.name == normalized)
    ).scalar_one_or_none()
    if entry:
        return entry

    # Messier cross-reference
    messier_match = re.match(r"^M\s*(\d+)$", catalog_id.strip(), re.IGNORECASE)
    if messier_match:
        m_name = f"M {messier_match.group(1)}"
        entry = session.execute(
            select(OpenNGCEntry).where(OpenNGCEntry.messier == m_name)
        ).scalar_one_or_none()
        if entry:
            return entry

    return None


def enrich_target_from_openngc(session: Session, target: Any) -> bool:
    """Look up OpenNGC data for a target and populate enrichment fields.

    Returns True if any fields were updated.
    """
    entry = lookup_openngc(session, target.catalog_id)
    if not entry:
        return False

    updated = False
    for target_field, ngc_field in [
        ("size_major", "major_axis"),
        ("size_minor", "minor_axis"),
        ("position_angle", "position_angle"),
        ("v_mag", "v_mag"),
        ("surface_brightness", "surface_brightness"),
    ]:
        ngc_val = getattr(entry, ngc_field)
        if ngc_val is not None and getattr(target, target_field, None) is None:
            setattr(target, target_field, ngc_val)
            updated = True

    return updated
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_openngc.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/openngc.py backend/tests/test_openngc.py
git commit -m "feat: add OpenNGC service with CSV loading, lookup, and enrichment"
```

---

### Task 6: Add the data migration (DATA_VERSION 3)

**Files:**
- Modify: `backend/app/services/data_migrations.py`

- [ ] **Step 1: Add the migration function and bump DATA_VERSION**

In `backend/app/services/data_migrations.py`:

1. Change `DATA_VERSION = 2` to `DATA_VERSION = 3`

2. Add a new import at the top, after the existing imports:

```python
from app.services.openngc import load_openngc_csv, enrich_target_from_openngc
```

3. Add the migration function after `_migrate_v1_fix_catalog_designations`:

```python
def _migrate_v3_load_openngc(session: Session) -> str:
    """Load OpenNGC catalog and enrich existing targets with size/magnitude data."""
    from app.models import Target

    # Load the CSV into the openngc_catalog table
    loaded = load_openngc_csv(session)

    # Enrich existing targets
    targets = session.execute(
        select(Target).where(Target.merged_into_id.is_(None))
    ).scalars().all()

    enriched = 0
    for target in targets:
        if enrich_target_from_openngc(session, target):
            enriched += 1

    session.flush()
    return f"Loaded {loaded} OpenNGC entries, enriched {enriched}/{len(targets)} targets"
```

4. Add the new entry to the `MIGRATIONS` dict:

```python
    3: ("Load OpenNGC catalog and enrich targets with size/magnitude", _migrate_v3_load_openngc),
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/data_migrations.py
git commit -m "feat: add data migration v3 to load OpenNGC and enrich targets"
```

---

### Task 7: Enrich targets during SIMBAD resolution

**Files:**
- Modify: `backend/app/worker/tasks.py`

- [ ] **Step 1: Add OpenNGC enrichment to _resolve_or_cache_target**

In `backend/app/worker/tasks.py`, add the import near the top with other service imports:

```python
from app.services.openngc import enrich_target_from_openngc
```

In `_resolve_or_cache_target`, after the target is created and committed (around line 583), add enrichment. Replace this block:

```python
        try:
            session.add(target)
            session.commit()
            return str(target.id)
```

With:

```python
        try:
            session.add(target)
            session.flush()
            enrich_target_from_openngc(session, target)
            session.commit()
            return str(target.id)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/worker/tasks.py
git commit -m "feat: enrich new targets with OpenNGC data during resolution"
```

---

### Task 8: Update the API schema and endpoint

**Files:**
- Modify: `backend/app/schemas/target.py`
- Modify: `backend/app/api/targets.py`

- [ ] **Step 1: Add fields to TargetDetailResponse**

In `backend/app/schemas/target.py`, add these 5 fields to `TargetDetailResponse` after the `dec` field (line 151):

```python
    size_major: float | None = None
    size_minor: float | None = None
    position_angle: float | None = None
    v_mag: float | None = None
    surface_brightness: float | None = None
```

- [ ] **Step 2: Pass the new fields in the API endpoint**

In `backend/app/api/targets.py`, in the `get_target_detail` function, add the new fields to the `TargetDetailResponse` constructor (around line 387, after the `dec` line):

```python
        size_major=target_obj.size_major if target_obj else None,
        size_minor=target_obj.size_minor if target_obj else None,
        position_angle=target_obj.position_angle if target_obj else None,
        v_mag=target_obj.v_mag if target_obj else None,
        surface_brightness=target_obj.surface_brightness if target_obj else None,
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/target.py backend/app/api/targets.py
git commit -m "feat: expose OpenNGC enrichment fields in target detail API"
```

---

### Task 9: Update the frontend TypeScript types

**Files:**
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Add fields to TargetDetailResponse interface**

In `frontend/src/types/index.ts`, add these fields to the `TargetDetailResponse` interface, after the `dec` field (around line 115):

```typescript
  size_major: number | null;
  size_minor: number | null;
  position_angle: number | null;
  v_mag: number | null;
  surface_brightness: number | null;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat: add OpenNGC fields to TargetDetailResponse type"
```

---

### Task 10: Display the new fields on the target detail page

**Files:**
- Modify: `frontend/src/pages/TargetDetailPage.tsx`

- [ ] **Step 1: Add formatting helpers**

In `frontend/src/pages/TargetDetailPage.tsx`, add these helpers after the existing `formatCoord` function (after line 19):

```typescript
function formatSize(major: number | null, minor: number | null): string {
  if (major === null) return "";
  if (minor === null) return `${major.toFixed(1)}'`;
  return `${major.toFixed(1)}' \u00d7 ${minor.toFixed(1)}'`;
}
```

- [ ] **Step 2: Add the new fields to the hero subtitle**

In the target hero subtitle section (the `div` with class `text-xs text-theme-text-secondary mt-1 space-x-2`, around line 130), add these `Show` blocks after the Dec `Show` block (after line 140) and before the aliases `Show` block:

```tsx
                    <Show when={detail().size_major !== null}>
                      <span>·</span>
                      <span>{formatSize(detail().size_major, detail().size_minor)}</span>
                      <Show when={detail().position_angle !== null}>
                        <span>PA {detail().position_angle!.toFixed(0)}°</span>
                      </Show>
                    </Show>
                    <Show when={detail().v_mag !== null}>
                      <span>·</span>
                      <span>V {detail().v_mag!.toFixed(1)}</span>
                    </Show>
                    <Show when={detail().surface_brightness !== null}>
                      <span>SB {detail().surface_brightness!.toFixed(1)}</span>
                    </Show>
```

- [ ] **Step 3: Verify the frontend compiles**

```bash
cd frontend && npm run build
```

Expected: Build succeeds with no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/TargetDetailPage.tsx
git commit -m "feat: display size, magnitude, and surface brightness on target detail page"
```

---

### Task 11: Run the migration and verify end-to-end

- [ ] **Step 1: Apply the Alembic migration**

```bash
cd backend && alembic upgrade head
```

Expected: Migration `0012` applies, creating `openngc_catalog` table and adding 5 columns to `targets`.

- [ ] **Step 2: Trigger the data migration**

The data migration runs automatically on the next app startup (DATA_VERSION 3 > stored version 2). Alternatively, restart the app:

```bash
cd backend && uvicorn app.main:app --reload
```

Look for log output:
- `Loaded NNNN OpenNGC entries, enriched NN/NN targets`

- [ ] **Step 3: Verify via API**

```bash
curl -s http://localhost:8000/api/targets/<a-known-ngc-target-id>/detail | python -m json.tool | grep -E "size_major|size_minor|position_angle|v_mag|surface_brightness"
```

Expected: Fields populated for NGC/IC/Messier targets.

- [ ] **Step 4: Verify in the UI**

Open a target detail page for a known NGC target (e.g., NGC 7000). Verify the hero subtitle shows size, PA, V mag, and surface brightness after RA/Dec.

- [ ] **Step 5: Run backend tests**

```bash
cd backend && python -m pytest -v
```

Expected: All existing tests pass, plus the new `test_openngc.py` tests.
