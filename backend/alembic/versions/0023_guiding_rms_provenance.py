"""Add guiding RMS provenance column to images.

``images.guiding_rms_arcsec`` and its RA/Dec siblings have had exactly one
writer since they existed: the N.I.N.A. Session Metadata CSV sidecar, whose
values land inline during ingest. Phase 2 of the PHD2 feature adds a second
writer that computes the same three numbers from the guide log's raw sample
stream over each frame's exposure interval. The two are close but are not
the same measurement - N.I.N.A. reports what its own guider integration saw,
PHD2's figure is a population standard deviation over the 0.5 s series - so
a column that silently held either would make the frame table's guiding
figures non-comparable with each other and with PHD2's own display.

``guiding_rms_source`` records which one wrote the row: "csv" or "phd2", or
NULL for a row with no guiding data (and, until data migration v16 runs, for
rows written before this column existed). It mirrors ``eccentricity_source``
from revision 0019, which solved the same problem for a column that had
collapsed three non-comparable origins into one number.

No index. Two values plus NULL is far too low-cardinality for a btree to pay
for itself, and nothing filters on it: the readers are a response field and
a data migration, both of which already have the row in hand.

Schema only. Stamping existing rows as "csv" and computing the PHD2 fill are
inference over data already held (``phd2_sessions`` / ``phd2_frames``), not a
structural DDL step, so they run through ``app.services.data_migrations`` as
data migration v16 where the version gate makes them run exactly once.

Plain add_column with no existence guards, per the project rule that guards
need a specific stated reason. This revision has none: the column is new in
this release and no install can already carry it.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "images", sa.Column("guiding_rms_source", sa.String(20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("images", "guiding_rms_source")
