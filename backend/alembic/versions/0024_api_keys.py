"""Create the api_keys table for public API bearer credentials.

The cookie session is a browser credential: it is httponly, SameSite=strict
and rotates, none of which a script or a third-party integration can carry.
The public API therefore needs a credential that is a single opaque string,
which is what this table stores.

Only the sha256 hexdigest of the raw key is persisted (key_hash, unique - it
is the authentication lookup key). ``prefix`` keeps the first 12 characters of
the raw key so the admin list can identify a row without holding anything that
authenticates. ``can_write`` is the whole permission model: read-only by
default, write when explicitly granted.

Revocation sets ``revoked_at`` instead of deleting, so a withdrawn key stays
in the list with its last_used_at for audit.

No index beyond the unique constraint on key_hash: that constraint already
serves the only hot lookup, and the admin list is a handful of rows.

Schema only, nothing to backfill. Plain create_table with no existence guards,
per the project rule that guards need a specific stated reason.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(12), nullable=False),
        sa.Column("can_write", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("api_keys")
