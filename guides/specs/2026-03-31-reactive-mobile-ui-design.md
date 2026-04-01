# Reactive & Mobile-Friendly UI Design

## Problem

1. **Dashboard loads in 2s local / 4s deployed** even with 25 rows displayed. The backend fetches all matching Image rows, aggregates in Python, then slices for pagination.
2. **No mobile/responsive layout.** Fixed 272px sidebar, hardcoded `grid-cols-7` stats, no hamburger menu. Only 2 responsive breakpoints exist in the entire app (both in DisplayTab).

## Goals

- Dashboard load time under 500ms
- Full functionality on tablet, quick-glance usability on phone
- Snappy filter/pagination interactions with no blank flashes

---

## Section 1: Backend Query Optimization

### Current Flow (targets.py:412-877)

1. `load_alias_maps()` fetches normalization settings
2. Main query: `SELECT Image, Target ... ORDER BY capture_date DESC` with no LIMIT -- returns all matching rows
3. Python loops through every row building `targets_map` and `sessions_map` dictionaries (lines 570-655)
4. Nine sequential Python filter loops calculate medians and discard non-matching sessions (lines 663-824)
5. Sort by total integration, compute global aggregates, then slice for pagination (lines 847-869)

### New Flow: Two-Phase SQL

**Phase 1 -- Paginated target list** (serves the table):

- SQL `GROUP BY resolved_target_id` (or `raw_headers->>'OBJECT'` for unresolved)
- Aggregates via SQL: `SUM(exposure_time)`, `COUNT(*)`, `MIN(capture_date)`, `MAX(capture_date)`
- Metric filters become `HAVING` clauses: e.g. `HAVING AVG(median_hfr) BETWEEN :hfr_min AND :hfr_max`
- `ORDER BY SUM(exposure_time) DESC`
- `LIMIT :page_size OFFSET :offset` at database level
- Filter distribution and equipment: second grouped query keyed only on the current page's target IDs

**Phase 2 -- Global aggregates** (serves the sidebar stats):

- `SELECT COUNT(DISTINCT resolved_target_id), SUM(exposure_time), COUNT(*)` with same WHERE/HAVING, no LIMIT
- Cheap since it doesn't materialize per-target detail

**Session detail** fetched only for the current page's targets (unchanged).

### Key Decisions

- Use `AVG()` instead of `MEDIAN()` for metric HAVING clauses. PostgreSQL has no built-in median; AVG is close enough for filtering and avoids a custom aggregate or `percentile_cont` subquery. The current Python code uses `statistics.median`.
- Unresolved images (no `resolved_target_id`) grouped by `raw_headers->>'OBJECT'` using `COALESCE(resolved_target_id::text, 'obj:' || raw_headers->>'OBJECT')` as the grouping key.
- Normalization (filter/camera/telescope aliases) still applied via `expand_canonical` to build the WHERE `IN` clause -- this is already efficient.

### Expected Impact

~200-400ms total (down from 2-4s). Database handles grouping, filtering, sorting, and pagination in a single indexed scan.

### Database Indexes to Verify/Add

- `images(resolved_target_id)` -- for the GROUP BY
- `images(image_type, capture_date)` -- for the base WHERE + sort
- `images(median_hfr)`, `images(fwhm)`, etc. -- if metric filtering is used frequently

---

## Section 2: Mobile-Responsive Layout

### Breakpoint Strategy

Using Tailwind's existing defaults (available but currently unused):

| Breakpoint | Width | Use |
|------------|-------|-----|
| `sm` | 640px | Large phones landscape |
| `md` | 768px | Tablets |
| `lg` | 1024px | Sidebar toggle point, small laptops |

### Component Changes

#### NavBar

- **lg+**: Current horizontal nav (unchanged)
- **< lg**: Hamburger button on the right side of the header. Nav links collapse into a dropdown/overlay menu. Only logo + hamburger visible in the bar.

#### Dashboard Sidebar

- **lg+**: Fixed `w-72` sidebar (unchanged)
- **< lg**: Hidden by default. A filter icon (funnel) button appears in the NavBar header (separate from the hamburger menu button) and toggles a slide-in drawer from the left with a backdrop overlay. Same sidebar content inside. Closes on backdrop tap or explicit close button.

#### StatsOverview (currently grid-cols-7)

- **lg+**: 7 columns (unchanged)
- **md**: 4 columns (wraps to 2 rows)
- **< md**: 2 columns

#### Statistics Page Grids

- 3-column grid: `grid-cols-1 md:grid-cols-2 lg:grid-cols-3`
- 2-column grid: `grid-cols-1 md:grid-cols-2`

#### TargetTable / TargetFeed

- **md+**: Full table (unchanged)
- **< md**: Horizontal scroll preserved (already has `overflow-x-auto`). No column hiding -- horizontal scroll is the simplest approach and already works.

#### Settings Page

- Tab bar: horizontal scroll on small screens
- Tab content grids in DisplayTab already have `sm:` breakpoints -- no change needed

#### Target Detail Page

- Session accordion cards: already full-width, no change needed
- Metrics charts: ensure Chart.js `responsive: true` respects container width

### What's NOT Changing

- No new CSS framework or custom breakpoints
- Pure Tailwind responsive prefixes on existing classes
- No layout restructuring beyond responsive variants

---

## Section 3: Frontend Snappiness

### Skeleton Loading States

- Target table: show placeholder rows (gray pulsing bars matching table column layout) during fetch
- Sidebar stats: skeleton placeholders during fetch
- Prevents layout shift when data arrives

### Optimistic Filter Feedback

- On filter change, immediately apply subtle opacity reduction to the table (e.g. `opacity-50 transition-opacity`) or show a spinner overlay
- Keep previous data visible (dimmed) until new data arrives -- no blank flash

### Debounced Search

- Search input debounced at ~300ms to avoid firing requests per keystroke
- Check if this is already implemented; add if not

### What's NOT Being Added

- No client-side caching/SWR layer -- backend will be fast enough after optimization
- No virtual scrolling -- page sizes of 25-250 rows don't need it
- No prefetching -- adds complexity for minimal gain at this scale

---

## Scope Summary

| Area | Files Affected | Complexity |
|------|---------------|------------|
| Backend query rewrite | `backend/app/api/targets.py` | High -- core query restructure |
| Database indexes | Alembic migration | Low |
| NavBar mobile | `frontend/src/components/NavBar.tsx` | Medium -- hamburger + overlay |
| Sidebar drawer | `frontend/src/components/Sidebar.tsx`, `frontend/src/pages/DashboardPage.tsx` | Medium -- drawer + backdrop |
| StatsOverview responsive | `frontend/src/components/StatsOverview.tsx` | Low -- class changes |
| Statistics grids responsive | `frontend/src/pages/StatisticsPage.tsx` | Low -- class changes |
| Skeleton loading | `frontend/src/components/TargetFeed.tsx`, `frontend/src/components/Sidebar.tsx` | Medium -- new placeholder components |
| Optimistic filter feedback | `frontend/src/components/DashboardFilterProvider.tsx`, `frontend/src/components/TargetFeed.tsx` | Low -- opacity transition |
| Search debounce | `frontend/src/components/SearchBar.tsx` | Low -- timer guard |
