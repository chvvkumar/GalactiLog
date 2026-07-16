"""Add eccentricity provenance and frame altitude columns to images.

Introduces two nullable columns:

``images.eccentricity_source`` records which of three physically distinct
origins produced ``images.eccentricity``: a native ``ECCENTRICITY`` keyword
("header"), a value derived from ``ELLIPTICITY`` via
e = sqrt(1 - (1 - ellipticity)^2) ("ellipticity"), or the N.I.N.A. Session
Metadata CSV ("csv"). The column collapsed all three into one number even
though each application measures eccentricity by its own method, so values
from different sources are not comparable and must not be pooled blindly.

``images.altitude_deg`` records the frame-centre altitude from ``OBJCTALT``
(else ``CENTALT``). Eccentricity is contaminated by atmospheric dispersion,
which scales with tan(zenith distance), so an eccentricity read without an
altitude cannot be attributed to the rig. Altitude was captured nowhere.

Schema only. Backfilling both columns for existing rows is inference from
``raw_headers``, not a structural DDL step, and it re-derives stored image
values the same way the AUD-001/AUD-007 backfill did -- so it runs through
``app.services.data_migrations`` as data migration v14, which is where
raw-headers re-derivation already lives and where the version gate makes it
run exactly once. Unlike 0018 (a self-contained one-time backfill), there is
nothing here to make re-runnable beyond the DDL itself.

No index on either column: ``eccentricity_source`` has three values plus NULL,
far too low-cardinality for a btree to pay for itself, and nothing filters on
it yet; ``altitude_deg`` has no reader at all today (frame-quality grouping is
deliberately unchanged), so an index would cost every ingest write for no read.
Add one when a query needs it.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existence guards, matching 0018: some installs were bootstrapped by
    # `create_all` then stamped, so a column the models declare may already
    # exist on a database whose alembic_version predates this revision.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("images")}

    if "eccentricity_source" not in existing_columns:
        op.add_column(
            "images", sa.Column("eccentricity_source", sa.String(20), nullable=True)
        )
    if "altitude_deg" not in existing_columns:
        op.add_column("images", sa.Column("altitude_deg", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("images", "altitude_deg")
    op.drop_column("images", "eccentricity_source")
