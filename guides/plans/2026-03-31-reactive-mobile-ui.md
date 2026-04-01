# Reactive & Mobile-Friendly UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard load in <500ms (down from 2-4s) by moving aggregation to SQL, and make the entire UI mobile-friendly with responsive breakpoints and a hamburger/drawer pattern.

**Architecture:** The backend `GET /targets` endpoint currently fetches all Image rows and aggregates in Python. We replace it with a two-phase SQL approach: Phase 1 does GROUP BY with HAVING clauses and LIMIT/OFFSET for the paginated target list; Phase 2 does a lightweight aggregate-only query for sidebar stats. The frontend gets responsive Tailwind breakpoints across all pages, a hamburger menu for nav, and a slide-in drawer for the filter sidebar on small screens.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async (backend), SolidJS + Tailwind CSS v4 (frontend)

**Spec:** `guides/specs/2026-03-31-reactive-mobile-ui-design.md`

---

## File Structure

### Backend Changes
- **Modify:** `backend/app/api/targets.py` -- rewrite `list_targets_aggregated()` (lines 412-877) to use SQL aggregation
- **Create:** `backend/alembic/versions/0014_add_metric_indexes.py` -- indexes for metric columns used in HAVING clauses

### Frontend Changes
- **Modify:** `frontend/src/components/NavBar.tsx` -- add hamburger menu for < lg screens
- **Modify:** `frontend/src/pages/DashboardPage.tsx` -- add sidebar drawer state and responsive layout
- **Modify:** `frontend/src/components/Sidebar.tsx` -- support drawer mode with close button and backdrop
- **Modify:** `frontend/src/components/StatsOverview.tsx` -- responsive grid breakpoints
- **Modify:** `frontend/src/pages/StatisticsPage.tsx` -- responsive grid breakpoints
- **Modify:** `frontend/src/components/TargetFeed.tsx` -- skeleton loading placeholder

---

### Task 1: Rewrite Backend Targets Query -- SQL Aggregation

This is the core performance fix. Replace the Python-side aggregation with SQL GROUP BY, HAVING, and LIMIT/OFFSET.

**Files:**
- Modify: `backend/app/api/targets.py:412-877`

- [ ] **Step 1: Replace the `list_targets_aggregated` function body**

Replace everything from line 450 (after the function signature and parameter declarations) through line 877 (end of function) with the new SQL-based implementation. The function signature (lines 412-449) stays exactly the same.

```python
    """Return targets with aggregated session data, filtered by query params."""
    filter_map, cam_map, tel_map = await load_alias_maps(session)

    # ── Base WHERE clause (shared by both phases) ──────────────────
    base_filter = [Image.image_type == "LIGHT"]
    base_filter.append(
        or_(
            Image.resolved_target_id.is_(None),
            Target.merged_into_id.is_(None),
        )
    )

    if camera:
        cam_variants = expand_canonical(camera, cam_map)
        base_filter.append(Image.camera.in_(cam_variants))
    if telescope:
        tel_variants = expand_canonical(telescope, tel_map)
        base_filter.append(Image.telescope.in_(tel_variants))
    if filters:
        filter_list = [f.strip() for f in filters.split(",")]
        all_filter_variants = []
        for f in filter_list:
            all_filter_variants.extend(expand_canonical(f, filter_map))
        base_filter.append(Image.filter_used.in_(all_filter_variants))
    if date_from:
        base_filter.append(Image.capture_date >= date_from)
    if date_to:
        base_filter.append(Image.capture_date <= date_to)
    if search:
        escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_search}%"
        aliases_str = func.array_to_string(Target.aliases, ' ')
        searchable_text = func.concat(
            func.coalesce(Target.catalog_id, ''), ' ',
            func.coalesce(Target.common_name, ''), ' ',
            aliases_str,
        )
        base_filter.append(
            or_(
                Target.primary_name.ilike(pattern),
                Target.catalog_id.ilike(pattern),
                Target.common_name.ilike(pattern),
                aliases_str.ilike(pattern),
                func.similarity(searchable_text, search) > 0.3,
                Image.raw_headers["OBJECT"].astext.ilike(pattern),
            )
        )

    if object_type:
        type_list = [t.strip() for t in object_type.split(",")]
        has_unresolved = "Unresolved" in type_list
        categories = [t for t in type_list if t != "Unresolved"]
        if categories:
            matching_codes = set()
            for code, category in _SIMBAD_CATEGORY_MAP.items():
                if category in categories:
                    matching_codes.add(code)
            type_conditions = [
                Target.object_type.like(f"{code},%") | (Target.object_type == code)
                for code in matching_codes
            ]
            if "Other" in categories:
                mapped_prefixes = list(_SIMBAD_CATEGORY_MAP.keys())
                other_conditions = [
                    ~Target.object_type.like(f"{code},%") & (Target.object_type != code)
                    for code in mapped_prefixes
                ]
                type_conditions.append(and_(*other_conditions))
            if has_unresolved:
                type_conditions.append(Image.resolved_target_id.is_(None))
            base_filter.append(or_(*type_conditions))
        elif has_unresolved:
            base_filter.append(Image.resolved_target_id.is_(None))

    if fits_key and fits_op and fits_val:
        for key, op_str, val in zip(fits_key, fits_op, fits_val):
            if not re.match(r'^[A-Za-z0-9_-]{1,20}$', key):
                continue
            json_field = Image.raw_headers[key].astext
            if op_str == "eq":
                base_filter.append(json_field == val)
            elif op_str == "neq":
                base_filter.append(json_field != val)
            elif op_str == "gt":
                base_filter.append(cast(json_field, Float) > float(val))
            elif op_str == "lt":
                base_filter.append(cast(json_field, Float) < float(val))
            elif op_str == "gte":
                base_filter.append(cast(json_field, Float) >= float(val))
            elif op_str == "lte":
                base_filter.append(cast(json_field, Float) <= float(val))
            elif op_str == "contains":
                base_filter.append(json_field.ilike(f"%{val}%"))

    # ── Grouping key ───────────────────────────────────────────────
    # Resolved targets group by target ID; unresolved group by OBJECT header
    group_key = func.coalesce(
        cast(Image.resolved_target_id, sa.String),
        func.concat(sa.literal("obj:"), func.coalesce(Image.raw_headers["OBJECT"].astext, "__uncategorized__")),
    )

    # ── HAVING clauses for metric filters ──────────────────────────
    having_clauses = []
    metric_col_map = {
        "hfr": Image.median_hfr,
        "fwhm": Image.fwhm,
        "eccentricity": Image.eccentricity,
        "stars": Image.detected_stars,
        "guiding_rms": Image.guiding_rms_arcsec,
        "adu_mean": Image.adu_mean,
        "focuser_temp": Image.focuser_temp,
        "ambient_temp": Image.ambient_temp,
        "humidity": Image.humidity,
        "airmass": Image.airmass,
    }

    # Collect all metric min/max params into a dict for uniform handling
    metric_params = {
        "hfr": (hfr_min, hfr_max),
        "fwhm": (fwhm_min, fwhm_max),
        "eccentricity": (eccentricity_min, eccentricity_max),
        "stars": (stars_min, stars_max),
        "guiding_rms": (guiding_rms_min, guiding_rms_max),
        "adu_mean": (adu_mean_min, adu_mean_max),
        "focuser_temp": (focuser_temp_min, focuser_temp_max),
        "ambient_temp": (ambient_temp_min, ambient_temp_max),
        "humidity": (humidity_min, humidity_max),
        "airmass": (airmass_min, airmass_max),
    }

    for metric_name, (m_min, m_max) in metric_params.items():
        col = metric_col_map[metric_name]
        if m_min is not None:
            having_clauses.append(func.avg(col) >= m_min)
        if m_max is not None:
            having_clauses.append(func.avg(col) <= m_max)

    # ── Phase 1: Paginated target list ─────────────────────────────
    base_join = (
        select(
            group_key.label("group_key"),
            func.min(Target.primary_name).label("primary_name"),
            func.sum(func.coalesce(Image.exposure_time, 0)).label("total_seconds"),
            func.count().label("total_frames"),
            func.min(Image.capture_date).label("oldest_date"),
            func.max(Image.capture_date).label("newest_date"),
            func.count(func.distinct(cast(Image.capture_date, Date))).label("session_count"),
        )
        .outerjoin(Target, Image.resolved_target_id == Target.id)
        .where(*base_filter)
        .group_by(group_key)
    )
    if having_clauses:
        base_join = base_join.having(and_(*having_clauses))

    # Count total before pagination
    count_q = select(func.count()).select_from(base_join.subquery())
    total_count = (await session.execute(count_q)).scalar() or 0

    # Paginated targets ordered by integration time desc
    paginated_q = (
        base_join
        .order_by(func.sum(func.coalesce(Image.exposure_time, 0)).desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    paginated_rows = (await session.execute(paginated_q)).all()

    # ── Collect target IDs for detail queries ──────────────────────
    page_group_keys = [row.group_key for row in paginated_rows]

    if not page_group_keys:
        return TargetAggregationResponse(
            targets=[],
            aggregates=AggregateStats(
                total_integration_seconds=0,
                target_count=0,
                total_frames=0,
                disk_usage_bytes=0,
            ),
            total_count=0,
            page=page,
            page_size=page_size,
        )

    # ── Filter distribution per target (current page only) ─────────
    filter_dist_q = (
        select(
            group_key.label("group_key"),
            Image.filter_used,
            func.sum(func.coalesce(Image.exposure_time, 0)).label("seconds"),
        )
        .outerjoin(Target, Image.resolved_target_id == Target.id)
        .where(*base_filter, group_key.in_(page_group_keys))
        .group_by(group_key, Image.filter_used)
    )
    filter_dist_rows = (await session.execute(filter_dist_q)).all()
    filter_dist_map: dict[str, dict[str, float]] = defaultdict(dict)
    for row in filter_dist_rows:
        f_name = normalize_filter(row.filter_used, filter_map) or row.filter_used or "Unknown"
        filter_dist_map[row.group_key][f_name] = (
            filter_dist_map[row.group_key].get(f_name, 0) + float(row.seconds)
        )

    # ── Equipment per target (current page only) ───────────────────
    equip_q = (
        select(
            group_key.label("group_key"),
            func.array_agg(func.distinct(Image.camera)).label("cameras"),
            func.array_agg(func.distinct(Image.telescope)).label("telescopes"),
        )
        .outerjoin(Target, Image.resolved_target_id == Target.id)
        .where(*base_filter, group_key.in_(page_group_keys))
        .group_by(group_key)
    )
    equip_rows = (await session.execute(equip_q)).all()
    equip_map: dict[str, list[str]] = {}
    for row in equip_rows:
        items = set()
        for c in (row.cameras or []):
            if c:
                items.add(normalize_equipment(c, cam_map) or c)
        for t in (row.telescopes or []):
            if t:
                items.add(normalize_equipment(t, tel_map) or t)
        equip_map[row.group_key] = sorted(items)

    # ── Sessions per target (current page only) ────────────────────
    session_q = (
        select(
            group_key.label("group_key"),
            cast(Image.capture_date, Date).label("session_date"),
            func.sum(func.coalesce(Image.exposure_time, 0)).label("integration_seconds"),
            func.count().label("frame_count"),
            func.array_agg(func.distinct(Image.filter_used)).label("filters_raw"),
        )
        .outerjoin(Target, Image.resolved_target_id == Target.id)
        .where(*base_filter, group_key.in_(page_group_keys))
        .group_by(group_key, cast(Image.capture_date, Date))
        .order_by(cast(Image.capture_date, Date).desc())
    )
    session_rows = (await session.execute(session_q)).all()
    sessions_map: dict[str, list[SessionSummary]] = defaultdict(list)
    for row in session_rows:
        normalized_filters = sorted(
            normalize_filter(f, filter_map) or f
            for f in (row.filters_raw or [])
            if f is not None
        )
        sessions_map[row.group_key].append(SessionSummary(
            session_date=str(row.session_date) if row.session_date else "unknown",
            integration_seconds=float(row.integration_seconds),
            frame_count=row.frame_count,
            filters_used=normalized_filters,
        ))

    # ── FITS OBJECT aliases per target (current page only) ─────────
    alias_q = (
        select(
            group_key.label("group_key"),
            func.array_agg(func.distinct(Image.raw_headers["OBJECT"].astext)).label("aliases"),
        )
        .outerjoin(Target, Image.resolved_target_id == Target.id)
        .where(*base_filter, group_key.in_(page_group_keys))
        .group_by(group_key)
    )
    alias_rows = (await session.execute(alias_q)).all()
    alias_map: dict[str, list[str]] = {}
    for row in alias_rows:
        alias_map[row.group_key] = sorted(a for a in (row.aliases or []) if a)

    # ── Build target list ──────────────────────────────────────────
    target_list = []
    for row in paginated_rows:
        gk = row.group_key
        name = row.primary_name
        if not name:
            # Unresolved: extract name from group key
            name = gk.removeprefix("obj:") if gk.startswith("obj:") else gk
            if name == "__uncategorized__":
                name = "Uncategorized"

        target_list.append(TargetAggregation(
            target_id=gk,
            primary_name=name,
            aliases=alias_map.get(gk, []),
            total_integration_seconds=float(row.total_seconds),
            total_frames=row.total_frames,
            filter_distribution=filter_dist_map.get(gk, {}),
            equipment=equip_map.get(gk, []),
            sessions=sessions_map.get(gk, []),
            matched_sessions=None,
            total_sessions=None,
        ))

    # ── Phase 2: Global aggregates ─────────────────────────────────
    agg_sub = base_join.subquery()
    agg_q = select(
        func.count().label("target_count"),
        func.sum(agg_sub.c.total_seconds).label("total_seconds"),
        func.sum(agg_sub.c.total_frames).label("total_frames"),
        func.min(agg_sub.c.oldest_date).label("oldest_date"),
        func.max(agg_sub.c.newest_date).label("newest_date"),
    )
    agg_row = (await session.execute(agg_q)).one()

    aggregates = AggregateStats(
        total_integration_seconds=float(agg_row.total_seconds or 0),
        target_count=agg_row.target_count or 0,
        total_frames=agg_row.total_frames or 0,
        disk_usage_bytes=0,
        oldest_date=str(agg_row.oldest_date) if agg_row.oldest_date else None,
        newest_date=str(agg_row.newest_date) if agg_row.newest_date else None,
    )

    return TargetAggregationResponse(
        targets=target_list,
        aggregates=aggregates,
        total_count=total_count,
        page=page,
        page_size=page_size,
    )
```

- [ ] **Step 2: Add missing `sa` import**

The code uses `sa.String` and `sa.literal`. Add `sqlalchemy as sa` to the imports at the top of the file. Line 8 currently reads:

```python
from sqlalchemy import select, or_, and_, func, cast, Float, Date, text
```

Change to:

```python
import sqlalchemy as sa
from sqlalchemy import select, or_, and_, func, cast, Float, Date, text
```

Also remove the `statistics` import (line 3) since it's no longer used by this function. Check if any other function in the file uses it before removing -- if so, keep it.

- [ ] **Step 3: Run the backend manually and test**

```bash
cd backend && uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` and test `GET /targets` with:
- No filters (should return paginated results fast)
- With `page_size=25`
- With a search term
- With metric filters (e.g., `hfr_min=1.0`)

Expected: Response in <500ms. Same response schema as before (targets, aggregates, total_count, page, page_size).

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/targets.py
git commit -m "perf: rewrite targets endpoint with SQL aggregation and pagination"
```

---

### Task 2: Add Database Indexes for Metric Columns

**Files:**
- Create: `backend/alembic/versions/0014_add_metric_indexes.py`

- [ ] **Step 1: Create the migration file**

```python
"""Add indexes on metric columns for HAVING clause performance."""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_images_median_hfr", "images", ["median_hfr"], if_not_exists=True)
    op.create_index("ix_images_fwhm", "images", ["fwhm"], if_not_exists=True)
    op.create_index("ix_images_eccentricity", "images", ["eccentricity"], if_not_exists=True)
    op.create_index("ix_images_detected_stars", "images", ["detected_stars"], if_not_exists=True)
    op.create_index("ix_images_guiding_rms_arcsec", "images", ["guiding_rms_arcsec"], if_not_exists=True)
    op.create_index("ix_images_adu_mean", "images", ["adu_mean"], if_not_exists=True)
    op.create_index("ix_images_focuser_temp", "images", ["focuser_temp"], if_not_exists=True)
    op.create_index("ix_images_ambient_temp", "images", ["ambient_temp"], if_not_exists=True)
    op.create_index("ix_images_humidity", "images", ["humidity"], if_not_exists=True)
    op.create_index("ix_images_airmass", "images", ["airmass"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_images_airmass", "images")
    op.drop_index("ix_images_humidity", "images")
    op.drop_index("ix_images_ambient_temp", "images")
    op.drop_index("ix_images_focuser_temp", "images")
    op.drop_index("ix_images_adu_mean", "images")
    op.drop_index("ix_images_guiding_rms_arcsec", "images")
    op.drop_index("ix_images_detected_stars", "images")
    op.drop_index("ix_images_eccentricity", "images")
    op.drop_index("ix_images_fwhm", "images")
    op.drop_index("ix_images_median_hfr", "images")
```

- [ ] **Step 2: Run the migration**

```bash
cd backend && alembic upgrade head
```

Expected: Migration applies cleanly. If indexes already exist, `if_not_exists=True` handles it.

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0014_add_metric_indexes.py
git commit -m "feat: add database indexes for metric columns"
```

---

### Task 3: NavBar Hamburger Menu

Add a hamburger button that collapses nav links on screens < lg (1024px).

**Files:**
- Modify: `frontend/src/components/NavBar.tsx`

- [ ] **Step 1: Replace NavBar.tsx contents**

```tsx
import { Component, Show, createSignal } from "solid-js";
import { A, useNavigate } from "@solidjs/router";
import { useAuth } from "./AuthProvider";

const NavBar: Component = () => {
  const { user, logout, isAdmin } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = createSignal(false);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <header class="sticky top-0 z-30 bg-theme-surface backdrop-blur-sm border-b border-theme-border px-4 lg:px-6 py-3 flex items-center gap-4 lg:gap-6">
      <A href="/" class="flex items-center gap-2 no-underline">
        <img src="/logo-transparent.png" alt="GalactiLog logo" class="h-7 w-7" />
        <h1 class="text-theme-text-primary font-bold tracking-tight text-lg whitespace-nowrap">GalactiLog</h1>
      </A>

      {/* Desktop nav */}
      <nav class="hidden lg:flex gap-4">
        <A
          href="/"
          class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          activeClass="text-theme-text-primary font-medium bg-theme-elevated rounded-[var(--radius-sm)] px-2.5 py-1"
          end
        >
          Dashboard
        </A>
        <A
          href="/statistics"
          class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          activeClass="text-theme-text-primary font-medium bg-theme-elevated rounded-[var(--radius-sm)] px-2.5 py-1"
        >
          Statistics
        </A>
        <A
          href="/settings"
          class="text-theme-text-secondary hover:text-theme-text-primary transition-colors text-sm"
          activeClass="text-theme-text-primary font-medium bg-theme-elevated rounded-[var(--radius-sm)] px-2.5 py-1"
        >
          Settings
        </A>
      </nav>

      <div class="ml-auto flex items-center gap-3">
        <Show when={user()}>
          <span class="text-xs text-theme-text-secondary hidden sm:inline">
            {user()!.username}
            <Show when={!isAdmin()}>{" "}(viewer)</Show>
          </span>
          <button
            onClick={handleLogout}
            class="text-xs text-theme-text-secondary hover:text-theme-text-primary transition-colors hidden sm:inline"
          >
            Sign out
          </button>
        </Show>
        <a
          href="https://github.com/chvvkumar/GalactiLog"
          target="_blank"
          rel="noopener noreferrer"
          class="text-theme-text-secondary hover:text-theme-text-primary transition-colors hidden sm:inline"
          title="GitHub"
        >
          <svg width="20" height="20" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>
          </svg>
        </a>

        {/* Hamburger button -- visible < lg */}
        <button
          class="lg:hidden p-1 text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          onClick={() => setMenuOpen(!menuOpen())}
          aria-label="Toggle menu"
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <Show when={!menuOpen()} fallback={
              <>{/* X icon */}
                <line x1="6" y1="6" x2="18" y2="18" />
                <line x1="6" y1="18" x2="18" y2="6" />
              </>
            }>
              {/* Hamburger icon */}
              <line x1="4" y1="6" x2="20" y2="6" />
              <line x1="4" y1="12" x2="20" y2="12" />
              <line x1="4" y1="18" x2="20" y2="18" />
            </Show>
          </svg>
        </button>
      </div>

      {/* Mobile dropdown menu */}
      <Show when={menuOpen()}>
        <div class="absolute top-full left-0 right-0 bg-theme-surface border-b border-theme-border shadow-[var(--shadow-md)] lg:hidden z-40">
          <nav class="flex flex-col p-4 gap-2">
            <A
              href="/"
              class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors py-2 px-3 rounded-[var(--radius-sm)]"
              activeClass="text-theme-text-primary font-medium bg-theme-elevated"
              end
              onClick={() => setMenuOpen(false)}
            >
              Dashboard
            </A>
            <A
              href="/statistics"
              class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors py-2 px-3 rounded-[var(--radius-sm)]"
              activeClass="text-theme-text-primary font-medium bg-theme-elevated"
              onClick={() => setMenuOpen(false)}
            >
              Statistics
            </A>
            <A
              href="/settings"
              class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors py-2 px-3 rounded-[var(--radius-sm)]"
              activeClass="text-theme-text-primary font-medium bg-theme-elevated"
              onClick={() => setMenuOpen(false)}
            >
              Settings
            </A>
            <Show when={user()}>
              <div class="border-t border-theme-border mt-2 pt-2 flex items-center justify-between px-3">
                <span class="text-xs text-theme-text-secondary">
                  {user()!.username}
                  <Show when={!isAdmin()}>{" "}(viewer)</Show>
                </span>
                <button
                  onClick={() => { handleLogout(); setMenuOpen(false); }}
                  class="text-xs text-theme-text-secondary hover:text-theme-text-primary transition-colors"
                >
                  Sign out
                </button>
              </div>
            </Show>
          </nav>
        </div>
      </Show>
    </header>
  );
};

export default NavBar;
```

- [ ] **Step 2: Test in browser**

```bash
cd frontend && npm run dev
```

Resize the browser below 1024px. Expected: hamburger appears, nav links hide. Clicking hamburger shows dropdown with all links + sign out. Above 1024px, normal horizontal nav.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/NavBar.tsx
git commit -m "feat: add responsive hamburger menu for mobile nav"
```

---

### Task 4: Sidebar Slide-In Drawer for Mobile

Make the sidebar hidden on < lg screens, toggled by a filter icon in the NavBar.

**Files:**
- Modify: `frontend/src/pages/DashboardPage.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/components/NavBar.tsx` (add filter toggle button)

- [ ] **Step 1: Add sidebar signal to DashboardPage.tsx**

Replace the full file:

```tsx
import { Component, onMount, onCleanup, createSignal } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import Sidebar from "../components/Sidebar";
import TargetFeed from "../components/TargetFeed";
import DashboardFilterProvider, { hasFilterParams, ALL_PARAM_KEYS } from "../components/DashboardFilterProvider";

const SESSION_KEY = "dashboard_params";

export const [sidebarOpen, setSidebarOpen] = createSignal(false);

const DashboardPage: Component = () => {
  const [searchParams, setSearchParams] = useSearchParams();

  onMount(() => {
    if (!hasFilterParams(searchParams)) {
      try {
        const saved = sessionStorage.getItem(SESSION_KEY);
        if (saved) {
          const parsed = JSON.parse(saved) as Record<string, string>;
          setSearchParams(parsed, { replace: true });
        }
      } catch { /* ignore */ }
    }
  });

  onCleanup(() => {
    const toSave: Record<string, string> = {};
    for (const key of ALL_PARAM_KEYS) {
      const val = searchParams[key];
      if (val !== undefined && val !== "") {
        toSave[key] = String(val);
      }
    }
    try {
      if (Object.keys(toSave).length > 0) {
        sessionStorage.setItem(SESSION_KEY, JSON.stringify(toSave));
      }
    } catch { /* ignore */ }
  });

  return (
    <DashboardFilterProvider>
      <div class="flex" data-layout="sidebar-main">
        {/* Desktop sidebar */}
        <div class="hidden lg:block">
          <Sidebar />
        </div>

        {/* Mobile drawer backdrop */}
        <div
          class={`fixed inset-0 bg-black/50 z-40 lg:hidden transition-opacity ${sidebarOpen() ? "opacity-100" : "opacity-0 pointer-events-none"}`}
          onClick={() => setSidebarOpen(false)}
        />

        {/* Mobile drawer */}
        <div class={`fixed top-0 left-0 h-full w-72 z-50 bg-theme-base transform transition-transform lg:hidden ${sidebarOpen() ? "translate-x-0" : "-translate-x-full"}`}>
          <div class="flex items-center justify-between p-4 border-b border-theme-border">
            <span class="text-sm font-medium text-theme-text-primary">Filters</span>
            <button
              onClick={() => setSidebarOpen(false)}
              class="p-1 text-theme-text-secondary hover:text-theme-text-primary transition-colors"
              aria-label="Close filters"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <line x1="6" y1="6" x2="18" y2="18" />
                <line x1="6" y1="18" x2="18" y2="6" />
              </svg>
            </button>
          </div>
          <Sidebar />
        </div>

        <main class="flex-1 min-h-[calc(100vh-57px)]">
          <TargetFeed />
        </main>
      </div>
    </DashboardFilterProvider>
  );
};

export default DashboardPage;
```

- [ ] **Step 2: Update Sidebar.tsx for drawer mode**

The sidebar is now rendered in two contexts (desktop inline, mobile drawer). It needs to scroll within the drawer. Change the `<aside>` tag on line 37:

From:
```tsx
    <aside class="w-72 min-h-[calc(100vh-57px)] border-r border-theme-border-em p-4 space-y-6 overflow-y-auto">
```

To:
```tsx
    <aside class="w-72 min-h-0 max-h-[calc(100vh-57px)] border-r border-theme-border-em p-4 space-y-6 overflow-y-auto">
```

This change makes the sidebar scrollable within both the desktop layout and the mobile drawer (which has a fixed header above it).

- [ ] **Step 3: Add filter icon button to NavBar.tsx**

In `NavBar.tsx`, add this import at the top:

```tsx
import { sidebarOpen, setSidebarOpen } from "../pages/DashboardPage";
```

Then add the filter button right before the hamburger button (inside the `ml-auto` div), only shown on dashboard. Add a `useLocation` import and check:

Add to imports:
```tsx
import { A, useNavigate, useLocation } from "@solidjs/router";
```

Then before the hamburger button, add:

```tsx
        {/* Filter button -- visible < lg on dashboard only */}
        <Show when={useLocation().pathname === "/"}>
          <button
            class="lg:hidden p-1 text-theme-text-secondary hover:text-theme-text-primary transition-colors"
            onClick={() => setSidebarOpen(!sidebarOpen())}
            aria-label="Toggle filters"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
            </svg>
          </button>
        </Show>
```

- [ ] **Step 4: Test in browser**

Resize browser below 1024px on the dashboard. Expected:
- Sidebar hidden, filter icon visible in header
- Tap filter icon: drawer slides in from left with backdrop
- Tap backdrop or X: drawer closes
- Above 1024px: sidebar visible inline, no filter icon

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/DashboardPage.tsx frontend/src/components/Sidebar.tsx frontend/src/components/NavBar.tsx
git commit -m "feat: add slide-in filter drawer for mobile dashboard"
```

---

### Task 5: Responsive Grids -- StatsOverview and Statistics Page

**Files:**
- Modify: `frontend/src/components/StatsOverview.tsx`
- Modify: `frontend/src/pages/StatisticsPage.tsx`

- [ ] **Step 1: Update StatsOverview grid**

In `frontend/src/components/StatsOverview.tsx`, line 28, change:

```tsx
    <div class="grid grid-cols-7 gap-3">
```

To:

```tsx
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
```

- [ ] **Step 2: Update Statistics page 3-column grid**

In `frontend/src/pages/StatisticsPage.tsx`, line 38, change:

```tsx
            <div class="grid grid-cols-3 gap-4 [&>*]:border [&>*]:border-theme-border [&>*]:rounded-[var(--radius-md)] [&>*]:shadow-[var(--shadow-sm)]">
```

To:

```tsx
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 [&>*]:border [&>*]:border-theme-border [&>*]:rounded-[var(--radius-md)] [&>*]:shadow-[var(--shadow-sm)]">
```

- [ ] **Step 3: Update Statistics page 2-column grid**

In `frontend/src/pages/StatisticsPage.tsx`, line 46, change:

```tsx
            <div class="grid grid-cols-2 gap-4 [&>*]:border [&>*]:border-theme-border [&>*]:rounded-[var(--radius-md)] [&>*]:shadow-[var(--shadow-sm)]">
```

To:

```tsx
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 [&>*]:border [&>*]:border-theme-border [&>*]:rounded-[var(--radius-md)] [&>*]:shadow-[var(--shadow-sm)]">
```

- [ ] **Step 4: Test in browser**

Resize browser. Expected:
- StatsOverview: 2 cols on phone, 4 on tablet, 7 on desktop
- Statistics 3-grid: 1 col on phone, 2 on tablet, 3 on desktop
- Statistics 2-grid: 1 col on phone, 2 on tablet+

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/StatsOverview.tsx frontend/src/pages/StatisticsPage.tsx
git commit -m "feat: add responsive grid breakpoints for stats and statistics"
```

---

### Task 6: Skeleton Loading for Target Table

Replace the current loading state (toast + opacity) with skeleton placeholder rows for a smoother experience.

**Files:**
- Modify: `frontend/src/components/TargetFeed.tsx`

- [ ] **Step 1: Add skeleton component and update TargetFeed**

Replace the full file:

```tsx
import { Component, Show, For, createEffect } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import { showToast, dismissToast } from "./Toast";
import TargetTable from "./TargetTable";

const SkeletonRow: Component = () => (
  <tr class="border-b border-theme-border">
    <td class="p-3"><div class="h-4 w-32 bg-theme-elevated rounded animate-pulse" /></td>
    <td class="p-3"><div class="h-4 w-20 bg-theme-elevated rounded animate-pulse" /></td>
    <td class="p-3"><div class="flex gap-1"><div class="h-5 w-8 bg-theme-elevated rounded animate-pulse" /><div class="h-5 w-8 bg-theme-elevated rounded animate-pulse" /></div></td>
    <td class="p-3"><div class="h-4 w-16 bg-theme-elevated rounded animate-pulse" /></td>
    <td class="p-3"><div class="h-4 w-24 bg-theme-elevated rounded animate-pulse" /></td>
    <td class="p-3"><div class="h-4 w-20 bg-theme-elevated rounded animate-pulse" /></td>
    <td class="p-3"><div class="h-4 w-6 bg-theme-elevated rounded animate-pulse" /></td>
  </tr>
);

const TargetFeed: Component = () => {
  const { targetData, page, totalPages, totalCount, setPage, pageSize, setPageSize } = useDashboardFilters();
  const PAGE_SIZES = [10, 25, 50, 100, 250];

  createEffect(() => {
    if (targetData.loading) {
      showToast("Loading targets...", "success", 10000);
    } else {
      dismissToast();
    }
  });

  const pageRange = () => {
    const current = page();
    const total = totalPages();
    const pages: (number | "...")[] = [];
    if (total <= 7) {
      for (let i = 1; i <= total; i++) pages.push(i);
    } else {
      pages.push(1);
      if (current > 3) pages.push("...");
      for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) {
        pages.push(i);
      }
      if (current < total - 2) pages.push("...");
      pages.push(total);
    }
    return pages;
  };

  const showingRange = () => {
    const start = (page() - 1) * pageSize() + 1;
    const end = Math.min(page() * pageSize(), totalCount());
    return { start, end };
  };

  const displayData = () => targetData() ?? targetData.latest;

  return (
    <div class="p-4">
      <Show when={targetData.error && !displayData()}>
        <div class="text-center text-theme-error py-8">
          Failed to load targets: {String(targetData.error)}
        </div>
      </Show>

      {/* Skeleton: shown on initial load (no data yet) */}
      <Show when={targetData.loading && !displayData()}>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead><tr class="border-b border-theme-border text-left">
              <th class="p-3 text-xs text-theme-text-secondary">Target</th>
              <th class="p-3 text-xs text-theme-text-secondary">Designation</th>
              <th class="p-3 text-xs text-theme-text-secondary">Palette</th>
              <th class="p-3 text-xs text-theme-text-secondary">Integration</th>
              <th class="p-3 text-xs text-theme-text-secondary">Equipment</th>
              <th class="p-3 text-xs text-theme-text-secondary">Last Session</th>
              <th class="p-3" />
            </tr></thead>
            <tbody>
              <For each={Array(pageSize())}>{() => <SkeletonRow />}</For>
            </tbody>
          </table>
        </div>
      </Show>

      <Show when={displayData()}>
        {(data) => (
          <Show
            when={data().targets.length > 0}
            fallback={<div class="text-center text-theme-text-secondary py-8">No targets match your filters</div>}
          >
            <div class="flex items-center justify-between mb-2 px-1">
              <div class="flex items-center gap-3">
                <span class="text-xs text-theme-text-tertiary">
                  Showing {showingRange().start}-{showingRange().end} of {totalCount()} targets
                </span>
                <select
                  value={pageSize()}
                  onChange={(e) => setPageSize(Number(e.currentTarget.value))}
                  class="px-2 py-1 text-xs rounded border border-theme-border bg-theme-input text-theme-text-secondary cursor-pointer transition-colors hover:border-theme-border-em"
                >
                  <For each={PAGE_SIZES}>
                    {(size) => <option value={size}>{size} / page</option>}
                  </For>
                </select>
              </div>
              <Show when={totalPages() > 1}>
                <div class="flex items-center gap-1">
                  <button
                    onClick={() => setPage(page() - 1)}
                    disabled={page() <= 1}
                    class="px-2 py-1 text-xs rounded border border-theme-border text-theme-text-secondary hover:bg-theme-elevated disabled:opacity-30 disabled:cursor-default transition-colors"
                  >
                    Prev
                  </button>
                  <For each={pageRange()}>
                    {(p) => (
                      <Show
                        when={p !== "..."}
                        fallback={<span class="px-1 text-xs text-theme-text-tertiary">...</span>}
                      >
                        <button
                          onClick={() => setPage(p as number)}
                          class={`px-2 py-1 text-xs rounded border transition-colors ${
                            page() === p
                              ? "border-theme-accent bg-theme-accent/10 text-theme-accent font-medium"
                              : "border-theme-border text-theme-text-secondary hover:bg-theme-elevated"
                          }`}
                        >
                          {p}
                        </button>
                      </Show>
                    )}
                  </For>
                  <button
                    onClick={() => setPage(page() + 1)}
                    disabled={page() >= totalPages()}
                    class="px-2 py-1 text-xs rounded border border-theme-border text-theme-text-secondary hover:bg-theme-elevated disabled:opacity-30 disabled:cursor-default transition-colors"
                  >
                    Next
                  </button>
                </div>
              </Show>
            </div>

            <div class={targetData.loading ? "opacity-50 pointer-events-none transition-opacity" : "transition-opacity"}>
              <TargetTable targets={data().targets} />
            </div>
          </Show>
        )}
      </Show>
    </div>
  );
};

export default TargetFeed;
```

- [ ] **Step 2: Test in browser**

Hard refresh the dashboard. Expected:
- On initial load: skeleton rows appear matching table columns, pulsing gray
- On subsequent filter changes: previous data dims (opacity-50), no skeleton
- Skeleton count matches current page size

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TargetFeed.tsx
git commit -m "feat: add skeleton loading state for target table"
```

---

### Task 7: Integration Testing

Run the full stack and verify all changes work together.

**Files:** None (testing only)

- [ ] **Step 1: Run backend tests**

```bash
cd backend && pytest -x -v
```

Expected: All existing tests pass. The query rewrite doesn't change the response schema.

- [ ] **Step 2: Run frontend build**

```bash
cd frontend && npm run build
```

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 3: Manual end-to-end test**

Start both servers and test:
1. Dashboard loads fast (<500ms) with 25 rows
2. Filters work: search, camera, telescope, date range, HFR, object type
3. Pagination works: page 2 loads fast, page size changes work
4. Sidebar stats show correct totals
5. Resize below 1024px: hamburger menu works, filter drawer works
6. StatsOverview reflows to 2 cols on phone, 4 on tablet
7. Statistics page grids reflow correctly
8. Skeleton rows appear on initial load

- [ ] **Step 4: Commit any fixes found during testing**

```bash
git add -A
git commit -m "fix: address issues found during integration testing"
```

Only if there are fixes to commit; skip if everything passes.
