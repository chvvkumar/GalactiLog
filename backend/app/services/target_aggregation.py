"""Target search, detail, export, aggregation and session-detail logic.

Pure extraction of the business/DB logic that used to live inline in
app/api/targets.py. Behavior (query shapes, response models, status codes via
HTTPException) is preserved exactly; the API handlers are thin wrappers around
these functions.

This module is now a pure facade over target_helpers.py, target_listing.py,
and target_detail.py (split out for file-size reasons); every name below is
re-exported unchanged for backward compatibility with existing imports.
"""

from app.services.target_helpers import (
    parse_sexa_ra, parse_sexa_dec, build_rig_details,
    SIMBAD_CATEGORY_MAP, SOLAR_SYSTEM_CATEGORIES,
    categorize_object_type, sort_clause, compute_insights,
)
from app.services.target_listing import (
    search_targets, get_equipment, get_object_types, list_targets_aggregated,
)
from app.services.target_detail import (
    get_target_detail, get_session_detail, export_target,
)

__all__ = [
    "parse_sexa_ra", "parse_sexa_dec", "build_rig_details",
    "SIMBAD_CATEGORY_MAP", "SOLAR_SYSTEM_CATEGORIES",
    "categorize_object_type", "sort_clause", "compute_insights",
    "search_targets", "get_equipment", "get_object_types", "list_targets_aggregated",
    "get_target_detail", "get_session_detail", "export_target",
]
