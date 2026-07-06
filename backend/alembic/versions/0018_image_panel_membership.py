"""Add panel-membership columns to images and backfill existing rows.

Introduces ``images.panel_label`` (the panel token parsed from the OBJECT
header, e.g. "Panel 3") and ``images.panel_id`` (FK to ``mosaic_panels.id``,
``ON DELETE SET NULL``) so accepted-mosaic panel stats can become exact joins
against a per-Image column instead of a per-query ILIKE scan of
``raw_headers``. See docs/retrofit-roadmap.md Phase 5.

This does NOT bump DATA_VERSION and does NOT route through
``app.services.data_migrations`` / ``data_jobs``. That machinery exists for
changes to target-derivation logic (how a Target is resolved/enriched); panel
membership is a structural, one-time backfill of a new column, not a change
to how targets are derived, so it runs as ordinary migration code instead.

Backfill: for every existing LIGHT-frame Image with a non-null OBJECT header,
the OBJECT is re-parsed with the same tokenizer used everywhere else
(``match_panel_token_full``) using the configured ``mosaic_keywords`` (read
directly from ``user_settings.general``, defaulting to ["Panel", "P"] like
every other call site). A parsed token yields ``panel_label`` in the exact
format existing ``MosaicPanel.panel_label`` rows use (``_panel_label``,
"Panel {num}"); if a ``MosaicPanel`` already exists for
``(resolved_target_id, panel_label)`` its id is also set on ``panel_id``.
Images whose OBJECT does not parse as a token get no ``panel_label``, but are
still linked to an existing "simple" panel (a ``MosaicPanel`` with no
``object_pattern`` -- one Target maps to exactly one panel) when exactly one
such panel exists for that target, since the target-id match is unambiguous
in that case. This mirrors the lookup Task 2's ingest-time hook applies so
backfilled and newly-ingested rows agree.

The backfill is batched (500 rows/commit, keyset-paginated by id so forward
progress does not depend on row outcomes) and safe to call again: rows that
already have panel_label or panel_id set are skipped by the selection query.
"""
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

BATCH_SIZE = 500
_NIL_UUID = "00000000-0000-0000-0000-000000000000"
_DEFAULT_KEYWORDS = ["Panel", "P"]
_SETTINGS_ROW_ID = "00000000-0000-4000-8000-000000000001"


def upgrade() -> None:
    op.add_column("images", sa.Column("panel_label", sa.String(100), nullable=True))
    op.add_column("images", sa.Column("panel_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_images_panel_id_mosaic_panels",
        "images", "mosaic_panels",
        ["panel_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_images_panel_id", "images", ["panel_id"])
    op.create_index(
        "ix_images_target_panel_label", "images",
        ["resolved_target_id", "panel_label"],
    )

    backfill_panel_membership(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_images_target_panel_label", table_name="images")
    op.drop_index("ix_images_panel_id", table_name="images")
    op.drop_constraint("fk_images_panel_id_mosaic_panels", "images", type_="foreignkey")
    op.drop_column("images", "panel_id")
    op.drop_column("images", "panel_label")


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------
#
# match_panel_token_full / _panel_label below are an intentional inline copy
# of app.services.mosaic_detection's tokenizer, NOT an import. Importing that
# module drags in app.services.mosaic_composite, which imports fitsio (a
# native FITS I/O extension not needed for pure string tokenizing) purely for
# unrelated helpers -- an avoidable, fragile dependency for a migration file
# to carry. The regex/logic below MUST stay byte-for-byte identical to
# mosaic_detection.py's `_TILE_RE`, `_keyword_regex`, `match_panel_token_full`,
# and `_panel_label` (verified against mosaic_detection.py as of this
# migration); any future change to the tokenizer there must be mirrored here
# if this migration is ever re-run against a fresh database.

_TILE_RE = re.compile(r"^(.+?)[\s_-]+(\d+-\d+)\s*$")


def _keyword_regex(keywords: list[str]) -> re.Pattern:
    kw_pattern = "|".join(re.escape(k) for k in keywords)
    return re.compile(
        rf"^(.+?)\s*[-_\s]?\s*({kw_pattern})\s*[-_\s]?\s*(\d+)\s*$",
        re.IGNORECASE,
    )


def match_panel_token_full(
    name: str, keywords: list[str]
) -> tuple[str, str, str | None] | None:
    if not name:
        return None
    if keywords:
        m = _keyword_regex(keywords).match(name)
        if m:
            return m.group(1).strip(), m.group(3), m.group(2)
    m = _TILE_RE.match(name)
    if m:
        return m.group(1).strip(), m.group(2), None
    return None


def _panel_label(num: str) -> str:
    return f"Panel {num}"


def _load_mosaic_keywords(bind) -> list[str]:
    """Read ``user_settings.general['mosaic_keywords']`` via raw SQL.

    Deliberately does not import the async ``load_mosaic_keywords`` helper
    (wrong execution context for a sync migration) -- reads the row directly,
    same default as every other call site.
    """
    row = bind.execute(
        text("SELECT general FROM user_settings WHERE id = :id"),
        {"id": _SETTINGS_ROW_ID},
    ).first()
    if row is None or not row[0]:
        return list(_DEFAULT_KEYWORDS)
    keywords = row[0].get("mosaic_keywords")
    return list(keywords) if keywords else list(_DEFAULT_KEYWORDS)


def _load_panel_maps(bind) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    """Build lookup maps from existing ``mosaic_panels`` rows.

    ``label_map``: (target_id, panel_label) -> panel_id, for token panels.
    ``simple_map``: target_id -> panel_id, only for targets with EXACTLY ONE
    panel that has no ``object_pattern`` (a "simple" one-target-one-panel
    mosaic) -- matches the ingest-time simple-panel fallback semantics.
    """
    label_map: dict[tuple[str, str], str] = {}
    simple_candidates: dict[str, list[str]] = {}

    for target_id, panel_label, panel_id, object_pattern in bind.execute(
        text("SELECT target_id, panel_label, id, object_pattern FROM mosaic_panels")
    ):
        target_key = str(target_id)
        label_map[(target_key, panel_label)] = panel_id
        if object_pattern is None:
            simple_candidates.setdefault(target_key, []).append(panel_id)

    simple_map = {
        target_key: panel_ids[0]
        for target_key, panel_ids in simple_candidates.items()
        if len(panel_ids) == 1
    }
    return label_map, simple_map


def backfill_panel_membership(bind) -> int:
    """Populate ``images.panel_label`` / ``images.panel_id`` for existing rows.

    Idempotent and resumable: only rows with both columns still NULL are
    selected, keyset-paginated by ``id`` (not OFFSET, since already-processed
    rows drop out of a naive WHERE-based page) so forward progress is
    guaranteed even for rows that end up with no match. Commits every
    ``BATCH_SIZE`` rows so a large catalog does not hold one long transaction.
    Returns the number of rows updated (for test/observability use).
    """
    keywords = _load_mosaic_keywords(bind)
    label_map, simple_map = _load_panel_maps(bind)

    updated = 0
    last_id = _NIL_UUID
    while True:
        rows = bind.execute(
            text("""
                SELECT id, resolved_target_id, raw_headers ->> 'OBJECT' AS object_name
                FROM images
                WHERE image_type = 'LIGHT'
                  AND raw_headers ->> 'OBJECT' IS NOT NULL
                  AND resolved_target_id IS NOT NULL
                  AND panel_label IS NULL
                  AND panel_id IS NULL
                  AND id > :last_id
                ORDER BY id
                LIMIT :limit
            """),
            {"last_id": last_id, "limit": BATCH_SIZE},
        ).all()
        if not rows:
            break

        for image_id, target_id, object_name in rows:
            target_key = str(target_id)
            label = None
            panel_id = None

            token = match_panel_token_full(object_name, keywords)
            if token is not None:
                _base, num, _keyword = token
                label = _panel_label(num)
                panel_id = label_map.get((target_key, label))
            else:
                panel_id = simple_map.get(target_key)

            if label is not None or panel_id is not None:
                bind.execute(
                    text(
                        "UPDATE images SET panel_label = :label, panel_id = :panel_id "
                        "WHERE id = :id"
                    ),
                    {"label": label, "panel_id": panel_id, "id": image_id},
                )
                updated += 1

        last_id = rows[-1][0]
        bind.commit()

    return updated
