"""Target search and paginated/aggregated listing logic.

Pure extraction of the business/DB logic that used to live in
app/services/target_aggregation.py (itself extracted from app/api/targets.py).
Behavior (query shapes, response models, status codes) is preserved exactly.
"""

import json
import re
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select, or_, func, cast, String, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Target, Image
from app.services.simbad import COMMON_NAME_MAP
from app.services.normalization import load_alias_maps, normalize_filter, normalize_equipment, expand_canonical
from app.schemas.target import (
    TargetAggregationResponse, TargetAggregation, SessionSummary,
    AggregateStats, EquipmentResponse, ObjectTypeCount, TargetSearchResultFuzzy,
)
from app.services.target_helpers import sort_clause, categorize_object_type, SIMBAD_CATEGORY_MAP


async def search_targets(
    q: str, limit: int, session: AsyncSession, *, include_unresolved: bool = False,
) -> list[TargetSearchResultFuzzy]:
    """Search targets by name or alias with fuzzy trigram matching.

    With include_unresolved, distinct unlinked OBJECT header names matching the
    query are appended as "obj:<name>" pseudo entries so merge flows can offer
    unresolved image groups as merge sources.
    """
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"

    # Also create a space-normalized pattern for catalog IDs like "M31" → "M 31"
    spaced = re.sub(r"([A-Za-z])(\d)", r"\1 \2", escaped)
    spaced_pattern = f"%{spaced}%" if spaced != escaped else None

    # Tier 1: Exact substring matches - exclude soft-deleted
    aliases_str = func.array_to_string(Target.aliases, ' ')
    ilike_conditions = [
        Target.primary_name.ilike(pattern),
        Target.catalog_id.ilike(pattern),
        Target.common_name.ilike(pattern),
        aliases_str.ilike(pattern),
    ]
    if spaced_pattern:
        ilike_conditions.extend([
            Target.primary_name.ilike(spaced_pattern),
            Target.catalog_id.ilike(spaced_pattern),
            Target.common_name.ilike(spaced_pattern),
            aliases_str.ilike(spaced_pattern),
        ])
    exact_query = (
        select(Target)
        .where(
            Target.merged_into_id.is_(None),
            or_(*ilike_conditions),
        )
        .limit(limit)
    )
    exact_result = await session.execute(exact_query)
    exact_targets = exact_result.scalars().all()

    exact_ids = {t.id for t in exact_targets}
    results = []
    for t in exact_targets:
        match_source = None
        if q.upper() not in t.primary_name.upper():
            for alias in (t.aliases or []):
                if q.upper() in alias.upper():
                    match_source = alias
                    break
        results.append(TargetSearchResultFuzzy(
            id=t.id,
            primary_name=t.primary_name,
            object_type=t.object_type,
            aliases=t.aliases or [],
            match_source=match_source,
            similarity_score=1.0,
        ))

    # Tier 1.5: Common name map lookup - match colloquial names to catalog IDs
    if len(results) < limit:
        q_lower = q.lower()
        mapped_catalog_ids = set()
        for common_name, catalog_id in COMMON_NAME_MAP.items():
            if q_lower in common_name or common_name in q_lower:
                mapped_catalog_ids.add(catalog_id)
        if mapped_catalog_ids:
            exclude_ids = exact_ids | {r.id for r in results}
            map_conditions = [Target.catalog_id == cid for cid in mapped_catalog_ids]
            map_query = (
                select(Target)
                .where(
                    Target.merged_into_id.is_(None),
                    Target.id.notin_(exclude_ids) if exclude_ids else True,
                    or_(*map_conditions),
                )
                .limit(limit - len(results))
            )
            map_result = await session.execute(map_query)
            for t in map_result.scalars().all():
                # Find which common name matched for display
                matched_name = None
                for cn, cid in COMMON_NAME_MAP.items():
                    if cid == t.catalog_id and (q_lower in cn or cn in q_lower):
                        matched_name = cn.title()
                        break
                exact_ids.add(t.id)
                results.append(TargetSearchResultFuzzy(
                    id=t.id,
                    primary_name=t.primary_name,
                    object_type=t.object_type,
                    aliases=t.aliases or [],
                    match_source=matched_name,
                    similarity_score=1.0,
                ))

    # Tier 2: Fuzzy trigram matches if we need more
    if len(results) < limit:
        remaining = limit - len(results)
        searchable_text = func.concat(
            func.coalesce(Target.catalog_id, ''), ' ',
            func.coalesce(Target.common_name, ''), ' ',
            func.array_to_string(Target.aliases, ' '),
        )
        fuzzy_score = func.similarity(searchable_text, q)
        fuzzy_query = (
            select(Target, fuzzy_score.label("score"))
            .where(
                Target.merged_into_id.is_(None),
                Target.id.notin_(exact_ids) if exact_ids else True,
                fuzzy_score > 0.3,
            )
            .order_by(fuzzy_score.desc())
            .limit(remaining)
        )
        fuzzy_result = await session.execute(fuzzy_query)
        for target, score in fuzzy_result.all():
            best_alias = None
            for alias in (target.aliases or []):
                if q.upper() in alias.upper():
                    best_alias = alias
                    break
            results.append(TargetSearchResultFuzzy(
                id=target.id,
                primary_name=target.primary_name,
                object_type=target.object_type,
                aliases=target.aliases or [],
                match_source=best_alias,
                similarity_score=float(score),
            ))

    if include_unresolved:
        unresolved_rows = (await session.execute(
            text("""
                SELECT raw_headers->>'OBJECT' AS obj, COUNT(*) AS cnt
                FROM images
                WHERE resolved_target_id IS NULL
                  AND raw_headers->>'OBJECT' IS NOT NULL
                  AND raw_headers->>'OBJECT' != ''
                  AND raw_headers->>'OBJECT' ILIKE :pattern
                GROUP BY raw_headers->>'OBJECT'
                ORDER BY cnt DESC
                LIMIT :lim
            """).bindparams(pattern=pattern, lim=limit)
        )).all()
        for obj_name, cnt in unresolved_rows:
            results.append(TargetSearchResultFuzzy(
                id=f"obj:{obj_name}",
                primary_name=obj_name,
                unresolved=True,
                image_count=cnt,
            ))

    return results


async def get_equipment(session: AsyncSession) -> EquipmentResponse:
    """Return distinct camera and telescope values."""
    filter_map, cam_map, tel_map = await load_alias_maps(session)
    cam_result = await session.execute(
        select(Image.camera).where(Image.camera.isnot(None)).distinct().order_by(Image.camera)
    )
    tel_result = await session.execute(
        select(Image.telescope).where(Image.telescope.isnot(None)).distinct().order_by(Image.telescope)
    )
    raw_cameras = [r[0] for r in cam_result.all() if r[0]]
    raw_telescopes = [r[0] for r in tel_result.all() if r[0]]

    # Track which canonical names have multiple raw names (grouped)
    cam_canonical: dict[str, set[str]] = {}
    for c in raw_cameras:
        canonical = normalize_equipment(c, cam_map) or c
        cam_canonical.setdefault(canonical, set()).add(c)
    tel_canonical: dict[str, set[str]] = {}
    for t in raw_telescopes:
        canonical = normalize_equipment(t, tel_map) or t
        tel_canonical.setdefault(canonical, set()).add(t)

    from app.schemas.target import EquipmentOption
    cameras = [EquipmentOption(name=name, grouped=len(raw) > 1) for name, raw in sorted(cam_canonical.items())]
    telescopes = [EquipmentOption(name=name, grouped=len(raw) > 1) for name, raw in sorted(tel_canonical.items())]
    return EquipmentResponse(
        cameras=cameras,
        telescopes=telescopes,
    )


async def get_object_types(session: AsyncSession) -> list[ObjectTypeCount]:
    """Return human-readable object type categories with target counts."""
    query = (
        select(Target.object_type, func.count(Target.id).label("count"))
        .where(
            Target.object_type.isnot(None),
            Target.merged_into_id.is_(None),
        )
        .group_by(Target.object_type)
    )
    result = await session.execute(query)

    # Aggregate raw SIMBAD types into human-readable categories
    category_counts: dict[str, int] = defaultdict(int)
    for raw_type, count in result.all():
        category = categorize_object_type(raw_type)
        category_counts[category] += count

    return sorted(
        [ObjectTypeCount(object_type=cat, count=cnt) for cat, cnt in category_counts.items()],
        key=lambda x: x.count,
        reverse=True,
    )


async def list_targets_aggregated(
    *,
    session: AsyncSession,
    search: str | None,
    target_id: str | None,
    camera: str | None,
    telescope: str | None,
    filters: str | None,
    date_from: str | None,
    date_to: str | None,
    fits_key: list[str] | None,
    fits_op: list[str] | None,
    fits_val: list[str] | None,
    object_type: str | None,
    hfr_min: float | None,
    hfr_max: float | None,
    fwhm_min: float | None,
    fwhm_max: float | None,
    eccentricity_min: float | None,
    eccentricity_max: float | None,
    stars_min: int | None,
    stars_max: int | None,
    guiding_rms_min: float | None,
    guiding_rms_max: float | None,
    adu_mean_min: float | None,
    adu_mean_max: float | None,
    focuser_temp_min: float | None,
    focuser_temp_max: float | None,
    ambient_temp_min: float | None,
    ambient_temp_max: float | None,
    humidity_min: float | None,
    humidity_max: float | None,
    airmass_min: float | None,
    airmass_max: float | None,
    catalog: str | None,
    sort_by: str,
    sort_dir: str,
    page: int,
    page_size: int,
    include_custom: bool,
    custom_filters: str | None,
) -> TargetAggregationResponse:
    """Return targets with aggregated session data, filtered by query params."""
    filter_map, cam_map, tel_map = await load_alias_maps(session)

    # ---------------------------------------------------------------
    # Parse custom column filters
    # ---------------------------------------------------------------
    cc_filter_entries: list[dict] = []
    cc_columns_by_slug: dict[str, dict] = {}
    if custom_filters:
        import json as _json
        try:
            cc_filter_entries = _json.loads(custom_filters)
        except (ValueError, TypeError):
            cc_filter_entries = []

        if cc_filter_entries:
            from app.models.custom_column import CustomColumn
            cc_q = select(CustomColumn.id, CustomColumn.slug, CustomColumn.column_type, CustomColumn.applies_to)
            cc_rows = (await session.execute(cc_q)).all()
            cc_columns_by_slug = {
                r.slug: {"id": str(r.id), "column_type": r.column_type, "applies_to": r.applies_to}
                for r in cc_rows
            }

    # ---------------------------------------------------------------
    # Phases 1-3: Raw SQL for grouped + aggregates + pagination
    # ---------------------------------------------------------------
    where_parts: list[str] = [
        "i.image_type = 'LIGHT'",
        "(i.resolved_target_id IS NULL OR t.merged_into_id IS NULL)",
    ]
    params: dict = {}

    # Generate EXISTS subqueries for custom column filters
    has_cc_session_filters = False
    for idx, entry in enumerate(cc_filter_entries):
        slug = entry.get("slug", "")
        value = entry.get("value", "")
        col_meta = cc_columns_by_slug.get(slug)
        if not col_meta or not value:
            continue

        col_id_param = f"cc_col_{idx}"
        val_param = f"cc_val_{idx}"
        params[col_id_param] = col_meta["id"]

        applies_to = col_meta["applies_to"]
        col_type = col_meta["column_type"]

        if col_type == "text":
            escaped_val = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params[val_param] = f"%{escaped_val}%"
            match_expr = f"cv.value ILIKE :{val_param}"
        else:
            params[val_param] = value
            match_expr = f"cv.value = :{val_param}"

        if applies_to == "target":
            where_parts.append(f"""EXISTS (
                SELECT 1 FROM custom_column_values cv
                WHERE cv.target_id = t.id AND cv.column_id = CAST(:{col_id_param} AS uuid)
                AND {match_expr}
            )""")
        elif applies_to == "session":
            has_cc_session_filters = True
            where_parts.append(f"""EXISTS (
                SELECT 1 FROM custom_column_values cv
                WHERE cv.target_id = t.id AND cv.column_id = CAST(:{col_id_param} AS uuid)
                AND cv.session_date IS NOT NULL AND {match_expr}
            )""")
        elif applies_to == "rig":
            has_cc_session_filters = True
            where_parts.append(f"""EXISTS (
                SELECT 1 FROM custom_column_values cv
                WHERE cv.target_id = t.id AND cv.column_id = CAST(:{col_id_param} AS uuid)
                AND cv.rig_label IS NOT NULL AND {match_expr}
            )""")

    if camera:
        cam_variants = expand_canonical(camera, cam_map)
        where_parts.append("i.camera = ANY(:cam_variants)")
        params["cam_variants"] = cam_variants
    if telescope:
        tel_variants = expand_canonical(telescope, tel_map)
        where_parts.append("i.telescope = ANY(:tel_variants)")
        params["tel_variants"] = tel_variants
    if filters:
        filter_list = [f.strip() for f in filters.split(",")]
        all_filter_variants: list[str] = []
        for f in filter_list:
            all_filter_variants.extend(expand_canonical(f, filter_map))
        where_parts.append("i.filter_used = ANY(:filter_variants)")
        params["filter_variants"] = all_filter_variants
    if date_from:
        where_parts.append("i.session_date >= :date_from")
        params["date_from"] = datetime.strptime(date_from, "%Y-%m-%d").date()
    if date_to:
        where_parts.append("i.session_date <= :date_to")
        params["date_to"] = datetime.strptime(date_to, "%Y-%m-%d").date()
    if target_id:
        where_parts.append("i.resolved_target_id = CAST(:exact_target_id AS uuid)")
        params["exact_target_id"] = target_id
    elif search:
        escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_search}%"
        where_parts.append("""(
            t.primary_name ILIKE :search_pat
            OR t.catalog_id ILIKE :search_pat
            OR t.common_name ILIKE :search_pat
            OR array_to_string(t.aliases, ' ') ILIKE :search_pat
            OR similarity(concat(coalesce(t.catalog_id,''),' ',coalesce(t.common_name,''),' ',array_to_string(t.aliases,' ')), :search_raw) > 0.3
            OR i.raw_headers->>'OBJECT' ILIKE :search_pat
        )""")
        params["search_pat"] = pattern
        params["search_raw"] = search

    if object_type:
        type_list = [tp.strip() for tp in object_type.split(",")]
        has_unresolved = "Unresolved" in type_list
        categories = [tp for tp in type_list if tp != "Unresolved"]

        if categories:
            matching_codes: set[str] = set()
            for code, cat in SIMBAD_CATEGORY_MAP.items():
                if cat in categories:
                    matching_codes.add(code)

            type_conds: list[str] = []
            for idx, code in enumerate(matching_codes):
                pname = f"simbad_{idx}"
                type_conds.append(f"(t.object_type LIKE :{pname}_like OR t.object_type = :{pname}_eq)")
                params[f"{pname}_like"] = f"{code},%"
                params[f"{pname}_eq"] = code

            if "Other" in categories:
                mapped = list(SIMBAD_CATEGORY_MAP.keys())
                oparts: list[str] = []
                for idx2, code in enumerate(mapped):
                    pn = f"other_{idx2}"
                    oparts.append(f"(t.object_type NOT LIKE :{pn}_like AND t.object_type != :{pn}_eq)")
                    params[f"{pn}_like"] = f"{code},%"
                    params[f"{pn}_eq"] = code
                type_conds.append(f"({' AND '.join(oparts)})")

            if has_unresolved:
                type_conds.append("i.resolved_target_id IS NULL")
            where_parts.append(f"({' OR '.join(type_conds)})")
        elif has_unresolved:
            where_parts.append("i.resolved_target_id IS NULL")

    if catalog:
        where_parts.append("""EXISTS (
            SELECT 1 FROM target_catalog_memberships tcm
            WHERE tcm.target_id = t.id AND tcm.catalog_name = :catalog_name
        )""")
        params["catalog_name"] = catalog

    if fits_key and fits_op and fits_val:
        for idx, (key, op_str, val) in enumerate(zip(fits_key, fits_op, fits_val)):
            if not re.match(r'^[A-Za-z0-9_-]{1,20}$', key):
                continue
            pn = f"fits_{idx}"
            # The header keyword is bound, never interpolated: `->>` takes the
            # key as a text operand, so it needs no identifier splicing.
            kn = f"fits_key_{idx}"
            field = f"i.raw_headers->>CAST(:{kn} AS text)"
            if op_str == "eq":
                where_parts.append(f"{field} = :{pn}")
                params[pn] = val
            elif op_str == "neq":
                where_parts.append(f"{field} != :{pn}")
                params[pn] = val
            elif op_str in ("gt", "lt", "gte", "lte"):
                try:
                    float(val)
                except ValueError:
                    continue
                op_map = {"gt": ">", "lt": "<", "gte": ">=", "lte": "<="}
                where_parts.append(f"CAST({field} AS FLOAT) {op_map[op_str]} :{pn}")
                params[pn] = float(val)
            elif op_str == "contains":
                esc = val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                where_parts.append(f"{field} ILIKE :{pn}")
                params[pn] = f"%{esc}%"
            # Only bind the keyword for ops that actually emitted a clause;
            # every emitting branch above sets params[pn].
            if pn in params:
                params[kn] = key

    where_sql = " AND ".join(where_parts)

    # HAVING clauses for metric range filters
    having_parts: list[str] = []
    metric_cols = {
        "hfr": "median_hfr", "fwhm": "fwhm", "eccentricity": "eccentricity",
        "stars": "CAST(detected_stars AS FLOAT)", "guiding_rms": "guiding_rms_arcsec",
        "adu_mean": "adu_mean", "focuser_temp": "focuser_temp",
        "ambient_temp": "ambient_temp", "humidity": "humidity", "airmass": "airmass",
    }
    metric_ranges = {
        "hfr": (hfr_min, hfr_max), "fwhm": (fwhm_min, fwhm_max),
        "eccentricity": (eccentricity_min, eccentricity_max),
        "stars": (stars_min, stars_max), "guiding_rms": (guiding_rms_min, guiding_rms_max),
        "adu_mean": (adu_mean_min, adu_mean_max), "focuser_temp": (focuser_temp_min, focuser_temp_max),
        "ambient_temp": (ambient_temp_min, ambient_temp_max),
        "humidity": (humidity_min, humidity_max), "airmass": (airmass_min, airmass_max),
    }
    for mname, (m_min, m_max) in metric_ranges.items():
        col = metric_cols[mname]
        if m_min is not None:
            having_parts.append(f"avg(i.{col}) >= :{mname}_min")
            params[f"{mname}_min"] = m_min
        if m_max is not None:
            having_parts.append(f"avg(i.{col}) <= :{mname}_max")
            params[f"{mname}_max"] = m_max

    has_metric_filters = bool(having_parts)
    having_sql = f"HAVING {' AND '.join(having_parts)}" if having_parts else ""

    # An empty-string OBJECT header is treated the same as a missing one
    # (nullif -> NULL -> __uncategorized__). This MUST match the detail-phase
    # key derivation (detail_target_key below) so a frame lands in the same
    # group in both phases.
    gk = "coalesce(CAST(i.resolved_target_id AS VARCHAR), concat('obj:', coalesce(nullif(i.raw_headers->>'OBJECT', ''), '__uncategorized__')))"

    # Equipment sort support: only computed when actively sorting by
    # equipment, since it requires two extra per-group array aggregates plus
    # a normalization pass over the (small) alias maps. `grouped_eq` layers a
    # single `equipment_sort_key` column on top of `grouped` -- the
    # space-joined, alphabetized set of normalized camera + telescope names
    # for the group, mirroring the Python-side normalization in Phase 4
    # below (`equipment_map`). Uncategorized targets are sent last via
    # `sort_clause`, independent of this key.
    equipment_group_cols = ""
    equipment_key_cte = ""
    grouped_source = "grouped"
    if sort_by == "equipment":
        equipment_group_cols = (
            ",\n               array_agg(DISTINCT coalesce(CAST(:cam_alias_map AS jsonb) ->> i.camera, i.camera)) "
            "FILTER (WHERE i.camera IS NOT NULL) AS cam_arr,\n"
            "               array_agg(DISTINCT coalesce(CAST(:tel_alias_map AS jsonb) ->> i.telescope, i.telescope)) "
            "FILTER (WHERE i.telescope IS NOT NULL) AS tel_arr"
        )
        params["cam_alias_map"] = json.dumps(cam_map)
        params["tel_alias_map"] = json.dumps(tel_map)
        equipment_key_cte = """
    grouped_eq AS (
        SELECT g.*,
               (
                   SELECT array_to_string(array_agg(DISTINCT eq ORDER BY eq), ' ')
                   FROM unnest(coalesce(g.cam_arr, ARRAY[]::text[]) || coalesce(g.tel_arr, ARRAY[]::text[])) AS eq
                   WHERE eq IS NOT NULL AND eq != ''
               ) AS equipment_sort_key
        FROM grouped g
    ),
    """
        grouped_source = "grouped_eq"

    # NOTE (AUD-032, axis 1): the resulting `agg.target_count` below counts
    # every group in `gk`, including unresolved-OBJECT / uncategorized "obj:"
    # buckets, alongside resolved targets. This is intentionally a different,
    # broader count than the Statistics overview's `target_count`
    # (`stats._query_overview`, which counts only `count(distinct
    # resolved_target_id)` and so excludes unresolved frames entirely). Both
    # are kept as distinct metrics -- this one drives the Dashboard sidebar's
    # "Targets" figure (a list-entry count including unresolved groups), the
    # Statistics figure is labeled "Resolved targets". Do not silently unify
    # them without updating both labels.
    combined_sql = text(f"""
    WITH grouped AS (
        SELECT {gk} AS target_key,
               coalesce(min(t.primary_name), min(nullif(i.raw_headers->>'OBJECT', '')), 'Uncategorized') AS primary_name,
               coalesce(bool_or(t.user_defined), false) AS user_defined,
               sum(coalesce(i.exposure_time, 0)) AS total_integration,
               count(i.id) AS total_frames,
               count(distinct coalesce(CAST(i.session_date AS VARCHAR), 'unknown')) AS session_count,
               max(i.session_date) AS last_session_date,
               min(i.session_date) AS oldest_date,
               max(i.session_date) AS newest_date{equipment_group_cols}
        FROM images i LEFT JOIN targets t ON i.resolved_target_id = t.id
        WHERE {where_sql}
        GROUP BY {gk}
        {having_sql}
    ),
    {equipment_key_cte}
    agg AS (
        SELECT count(*) AS target_count, sum(total_integration) AS total_integration,
               sum(total_frames) AS total_frames,
               min(oldest_date) AS oldest, max(newest_date) AS newest FROM {grouped_source}
    ),
    page AS (
        SELECT * FROM {grouped_source} ORDER BY {sort_clause(sort_by, sort_dir)}
        LIMIT :page_size OFFSET :page_offset
    )
    SELECT (SELECT target_count FROM agg) AS agg_target_count,
           (SELECT total_integration FROM agg) AS agg_total_integration,
           (SELECT total_frames FROM agg) AS agg_total_frames,
           (SELECT oldest FROM agg) AS agg_oldest,
           (SELECT newest FROM agg) AS agg_newest,
           p.target_key, p.primary_name, p.user_defined, p.total_integration, p.total_frames, p.session_count
    FROM page p
    """)
    params["page_size"] = page_size
    params["page_offset"] = (page - 1) * page_size

    combined_result = await session.execute(combined_sql, params)
    combined_rows = combined_result.all()

    if not combined_rows:
        return TargetAggregationResponse(
            targets=[],
            aggregates=AggregateStats(
                total_integration_seconds=0, target_count=0, total_frames=0, disk_usage_bytes=0,
            ),
            total_count=0, page=page, page_size=page_size,
        )

    first = combined_rows[0]
    total_count = first.agg_target_count or 0
    aggregates = AggregateStats(
        total_integration_seconds=float(first.agg_total_integration or 0),
        target_count=total_count,
        total_frames=int(first.agg_total_frames or 0),
        disk_usage_bytes=0,
        oldest_date=str(first.agg_oldest) if first.agg_oldest else None,
        newest_date=str(first.agg_newest) if first.agg_newest else None,
    )

    page_keys: list[str] = []
    page_basics: dict[str, dict] = {}
    for row in combined_rows:
        tk = row.target_key
        page_keys.append(tk)
        page_basics[tk] = {
            "target_key": tk,
            "primary_name": row.primary_name,
            "user_defined": bool(row.user_defined),
            "total_integration": float(row.total_integration),
            "total_frames": int(row.total_frames),
            "session_count": int(row.session_count),
        }

    # ---------------------------------------------------------------
    # Phase 4: Detail query for current page's targets (raw SQL)
    # ---------------------------------------------------------------
    page_uuids = []
    page_obj_names = []
    has_uncategorized = False
    for tk in page_keys:
        if tk == "obj:__uncategorized__":
            has_uncategorized = True
        elif tk.startswith("obj:"):
            page_obj_names.append(tk[4:])
        else:
            try:
                page_uuids.append(str(uuid.UUID(tk)))
            except ValueError:
                pass

    key_conds = []
    if page_uuids:
        key_conds.append("i.resolved_target_id = ANY(CAST(:page_uuids AS uuid[]))")
        params["page_uuids"] = page_uuids
    if page_obj_names:
        key_conds.append("(i.resolved_target_id IS NULL AND i.raw_headers->>'OBJECT' = ANY(:page_obj_names))")
        params["page_obj_names"] = page_obj_names
    if has_uncategorized:
        key_conds.append("(i.resolved_target_id IS NULL AND (NOT i.raw_headers ? 'OBJECT' OR i.raw_headers->>'OBJECT' = '' OR i.raw_headers->>'OBJECT' IS NULL))")

    key_filter = f"({' OR '.join(key_conds)})" if key_conds else "FALSE"

    # SQL-side target key, mirroring the Python derivation that previously ran
    # per frame: resolved UUID -> its text; otherwise obj:<OBJECT>, where an
    # empty/missing OBJECT collapses to obj:__uncategorized__.
    detail_target_key = (
        "CASE WHEN i.resolved_target_id IS NOT NULL "
        "THEN CAST(i.resolved_target_id AS VARCHAR) "
        "ELSE concat('obj:', coalesce(nullif(i.raw_headers->>'OBJECT', ''), '__uncategorized__')) "
        "END"
    )
    # Per-frame OBJECT header, NULL when empty/missing (mirrors `if row.fits_object`).
    detail_fits_object = "nullif(i.raw_headers->>'OBJECT', '')"

    # Two-level aggregation: collapse frames to one row per target_key, carrying
    # raw (un-normalized) filter sums, distinct raw equipment, distinct OBJECT
    # aliases, and a per-session breakdown as JSON. Alias normalization/merging
    # is applied in Python below over these small per-target sets.
    detail_sql = text(f"""
        WITH frames AS (
            SELECT {detail_target_key} AS target_key,
                   {detail_fits_object} AS fits_object,
                   coalesce(i.exposure_time, 0) AS exp,
                   i.filter_used,
                   i.camera,
                   i.telescope,
                   i.median_hfr,
                   i.eccentricity,
                   CASE WHEN i.session_date IS NULL THEN 'unknown'
                        ELSE CAST(i.session_date AS VARCHAR) END AS session_key
            FROM images i LEFT JOIN targets t ON i.resolved_target_id = t.id
            WHERE {where_sql} AND {key_filter}
        ),
        per_filter AS (
            SELECT target_key, filter_used, sum(exp) AS filter_exp
            FROM frames
            WHERE filter_used IS NOT NULL
            GROUP BY target_key, filter_used
        ),
        per_session AS (
            SELECT target_key, session_key,
                   sum(exp) AS session_exp,
                   count(*) AS frame_count,
                   array_agg(DISTINCT filter_used) FILTER (WHERE filter_used IS NOT NULL) AS session_filters,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY median_hfr)
                       FILTER (WHERE median_hfr IS NOT NULL) AS session_median_hfr,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY eccentricity)
                       FILTER (WHERE eccentricity IS NOT NULL) AS session_median_ecc
            FROM frames
            GROUP BY target_key, session_key
        ),
        per_target AS (
            SELECT target_key,
                   array_agg(DISTINCT camera) FILTER (WHERE camera IS NOT NULL) AS cameras,
                   array_agg(DISTINCT telescope) FILTER (WHERE telescope IS NOT NULL) AS telescopes,
                   array_agg(DISTINCT fits_object) FILTER (WHERE fits_object IS NOT NULL) AS fits_objects
            FROM frames
            GROUP BY target_key
        ),
        -- Roll per_filter up to one row per target ONCE (set-based), then
        -- LEFT JOIN onto per_target. Avoids a correlated scalar subquery that
        -- would rescan the frames CTE once per target.
        filter_agg AS (
            SELECT target_key,
                   jsonb_object_agg(filter_used, filter_exp) AS filter_raw_dist
            FROM per_filter
            GROUP BY target_key
        ),
        -- Roll per_session up to one row per target ONCE (set-based).
        session_agg AS (
            SELECT target_key,
                   jsonb_agg(jsonb_build_object(
                       'session_key', session_key,
                       'session_exp', session_exp,
                       'frame_count', frame_count,
                       'filters', coalesce(session_filters, ARRAY[]::varchar[]),
                       'median_hfr', session_median_hfr,
                       'median_eccentricity', session_median_ecc)) AS sessions
            FROM per_session
            GROUP BY target_key
        )
        SELECT pt.target_key,
               pt.cameras,
               pt.telescopes,
               pt.fits_objects,
               fa.filter_raw_dist,
               sa.sessions
        FROM per_target pt
        LEFT JOIN filter_agg fa USING (target_key)
        LEFT JOIN session_agg sa USING (target_key)
    """)
    detail_result = await session.execute(detail_sql, params)
    detail_rows = detail_result.all()

    # Build per-target detail maps. One row per target_key now; alias
    # normalization and merging happen here over the small per-target sets,
    # preserving the exact semantics of the former per-frame loop.
    filter_dist: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    equipment_map: dict[str, set] = defaultdict(set)
    sessions_detail: dict[str, dict[str, dict]] = defaultdict(dict)
    aliases_map: dict[str, set] = defaultdict(set)

    for row in detail_rows:
        tk = row.target_key
        if tk not in page_basics:
            continue

        # Filter distribution: normalize each raw filter and SUM exposures
        # that collapse to the same canonical name.
        for raw_filter, exp_sum in (row.filter_raw_dist or {}).items():
            f = normalize_filter(raw_filter, filter_map)
            if f:
                filter_dist[tk][f] += float(exp_sum)

        # Equipment: normalize cameras + telescopes, dedupe into one set.
        for raw_cam in (row.cameras or []):
            cam = normalize_equipment(raw_cam, cam_map)
            if cam:
                equipment_map[tk].add(cam)
        for raw_tel in (row.telescopes or []):
            tel = normalize_equipment(raw_tel, tel_map)
            if tel:
                equipment_map[tk].add(tel)

        # Aliases: distinct non-empty OBJECT headers.
        for obj_name in (row.fits_objects or []):
            if obj_name:
                aliases_map[tk].add(obj_name)

        # Sessions: normalize each session's filters, dedupe, cast numerics.
        for sess in (row.sessions or []):
            date_key = sess["session_key"]
            if date_key not in sessions_detail[tk]:
                sessions_detail[tk][date_key] = {
                    "session_date": date_key,
                    "integration_seconds": 0,
                    "frame_count": 0,
                    "filters_set": set(),
                    "median_hfr": None,
                    "median_eccentricity": None,
                }
            s = sessions_detail[tk][date_key]
            s["integration_seconds"] += float(sess["session_exp"])
            s["frame_count"] += int(sess["frame_count"])
            # Per-session median sharpness/roundness, computed SQL-side over the
            # session's frames (nulls ignored). Each (target_key, session_key)
            # appears once per detail row, so a direct set is correct.
            mh = sess.get("median_hfr")
            if mh is not None:
                s["median_hfr"] = float(mh)
            me = sess.get("median_eccentricity")
            if me is not None:
                s["median_eccentricity"] = float(me)
            for raw_filter in (sess.get("filters") or []):
                f = normalize_filter(raw_filter, filter_map)
                if f:
                    s["filters_set"].add(f)

    # ---------------------------------------------------------------
    # Phase 4b: Mosaic membership lookup
    # ---------------------------------------------------------------
    from app.models.mosaic_panel import MosaicPanel
    from app.models.mosaic import Mosaic
    page_target_uuids = [uuid.UUID(tk) for tk in page_keys if not tk.startswith("obj:")]
    panel_q = (
        select(MosaicPanel.target_id, Mosaic.id, Mosaic.name)
        .join(Mosaic)
        .where(MosaicPanel.target_id.in_(page_target_uuids))
    )
    panel_rows = (await session.execute(panel_q)).all()
    mosaic_map = {str(r[0]): (str(r[1]), r[2]) for r in panel_rows}

    # ---------------------------------------------------------------
    # Phase 4c: Custom column values (target-level)
    # ---------------------------------------------------------------
    custom_values_map: dict[str, dict[str, str]] = {}
    if include_custom:
        from app.models.custom_column import CustomColumn, CustomColumnValue, AppliesTo
        cv_q = (
            select(CustomColumnValue.target_id, CustomColumn.slug, CustomColumnValue.value)
            .join(CustomColumn)
            .where(
                CustomColumn.applies_to == AppliesTo.target,
                CustomColumnValue.target_id.in_(page_target_uuids),
            )
        )
        cv_rows = (await session.execute(cv_q)).all()
        for tid, slug, val in cv_rows:
            tid_str = str(tid)
            if tid_str not in custom_values_map:
                custom_values_map[tid_str] = {}
            custom_values_map[tid_str][slug] = val

    # ---------------------------------------------------------------
    # Phase 4d: Batch pre-fetch custom column session/rig values
    # ---------------------------------------------------------------
    _cc_batch_values: dict[str, dict[str, list[tuple[str, str]]]] = {}
    if has_cc_session_filters:
        from app.models.custom_column import CustomColumnValue
        import uuid as _uuid
        page_uuids = [_uuid.UUID(tk) for tk in page_keys if not tk.startswith("obj:")]
        col_ids = [
            _uuid.UUID(col_meta["id"])
            for col_meta in cc_columns_by_slug.values()
            if col_meta["applies_to"] in ("session", "rig")
        ]
        if page_uuids and col_ids:
            _batch_q = select(
                cast(CustomColumnValue.target_id, String),
                cast(CustomColumnValue.column_id, String),
                cast(CustomColumnValue.session_date, String),
                CustomColumnValue.value,
            ).where(
                CustomColumnValue.target_id.in_(page_uuids),
                CustomColumnValue.column_id.in_(col_ids),
                CustomColumnValue.session_date.isnot(None),
            )
            for row in (await session.execute(_batch_q)).all():
                tid_str, cid_str, sd_str, val = row
                _cc_batch_values.setdefault(tid_str, {}).setdefault(cid_str, []).append((sd_str, val))

    # ---------------------------------------------------------------
    # Phase 5: Assemble the response
    # ---------------------------------------------------------------
    target_list = []
    for tk in page_keys:
        basics = page_basics[tk]
        sessions_list = sorted(
            sessions_detail.get(tk, {}).values(),
            key=lambda x: x["session_date"],
            reverse=True,
        )
        total_session_count = basics["session_count"]
        matched_session_count = len(sessions_list) if has_metric_filters else None

        # Count sessions matching custom column session/rig filters
        if has_cc_session_filters and not tk.startswith("obj:"):
            cc_matched_dates: set[str] | None = None
            for idx, entry in enumerate(cc_filter_entries):
                slug = entry.get("slug", "")
                value = entry.get("value", "")
                col_meta = cc_columns_by_slug.get(slug)
                if not col_meta or not value:
                    continue
                if col_meta["applies_to"] not in ("session", "rig"):
                    continue

                col_id = col_meta["id"]
                col_type = col_meta["column_type"]

                # Look up pre-fetched values for this target + column
                target_key = basics["target_key"]
                cv_entries = _cc_batch_values.get(target_key, {}).get(col_id, [])
                matching_dates: set[str] = set()
                for sd, val in cv_entries:
                    if col_type == "text":
                        if value.lower() in (val or "").lower():
                            matching_dates.add(sd)
                    else:
                        if val == value:
                            matching_dates.add(sd)

                if cc_matched_dates is None:
                    cc_matched_dates = matching_dates
                else:
                    cc_matched_dates &= matching_dates

            if cc_matched_dates is not None:
                session_dates_for_target = set(sessions_detail.get(tk, {}).keys())
                if matched_session_count is not None:
                    # Intersect with metric-filtered sessions
                    metric_dates = {s["session_date"] for s in sessions_list}
                    cc_matched_dates &= metric_dates
                    matched_session_count = len(cc_matched_dates)
                else:
                    matched_session_count = len(cc_matched_dates & session_dates_for_target)

        sessions = [
            SessionSummary(
                session_date=s["session_date"],
                integration_seconds=s["integration_seconds"],
                frame_count=s["frame_count"],
                filters_used=sorted(s["filters_set"]),
                median_hfr=s["median_hfr"],
                median_eccentricity=s["median_eccentricity"],
            )
            for s in sessions_list
        ]

        target_list.append(TargetAggregation(
            target_id=basics["target_key"],
            primary_name=basics["primary_name"],
            aliases=sorted(aliases_map.get(tk, set())),
            total_integration_seconds=basics["total_integration"],
            total_frames=basics["total_frames"],
            filter_distribution=dict(filter_dist.get(tk, {})),
            equipment=sorted(equipment_map.get(tk, set())),
            sessions=sessions,
            matched_sessions=matched_session_count,
            total_sessions=total_session_count if matched_session_count is not None else None,
            mosaic_id=mosaic_map.get(basics["target_key"], (None, None))[0],
            mosaic_name=mosaic_map.get(basics["target_key"], (None, None))[1],
            custom_values=custom_values_map.get(basics["target_key"]) if include_custom else None,
            user_defined=basics["user_defined"],
        ))

    return TargetAggregationResponse(
        targets=target_list,
        aggregates=aggregates,
        total_count=total_count,
        page=page,
        page_size=page_size,
    )
