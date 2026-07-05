"""Add a btree expression index on images.raw_headers->>'OBJECT'.

The existing GIN index on raw_headers uses the default jsonb_ops opclass, which
cannot serve equality/prefix lookups on a single extracted key such as
``raw_headers->>'OBJECT' = :name``. Those lookups drive the dashboard target
detail, obj: pseudo-targets, unresolved search, and the rebuild/link UPDATE
loops, and in production they fall back to sequential scans of the ~190 MB
images table.

A plain btree on the extracted text value ``(raw_headers->>'OBJECT')`` makes
those exact-match and prefix queries index-served.

Defensive per project convention (installs may have been bootstrapped by
create_all then `alembic stamp head`): the index is created with
``CREATE INDEX IF NOT EXISTS`` and dropped with ``DROP INDEX IF EXISTS`` so the
migration is idempotent regardless of the starting state.

Index-only change: no DATA_VERSION bump (target derivation logic is unchanged).
"""
from alembic import op


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_INDEX = "ix_images_raw_headers_object"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX} "
        "ON images ((raw_headers->>'OBJECT'))"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
