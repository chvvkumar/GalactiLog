"""SQL-side equipment name canonicalization.

The alias maps come from load_alias_maps (app.services.normalization); this
module holds the one CASE expression every query that groups or joins by a
canonical telescope or camera must build, so the stats inventory and the
analysis PHD2 join resolve a raw spelling to the SAME name.
"""
from sqlalchemy import case


def _norm_case(col, alias_map: dict[str, str]):
    """SQL expression mapping a raw equipment name to its canonical form.

    Mirrors normalize_equipment() (an exact-match dict lookup) so a query can
    group by the SAME normalized (telescope, camera) combo the Python
    post-processing uses. Empty map -> the column unchanged.
    """
    if not alias_map:
        return col
    return case(alias_map, value=col, else_=col)
