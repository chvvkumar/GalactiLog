"""Add CSV metrics columns to images and display column to user_settings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Quality group
    op.add_column("images", sa.Column("hfr_stdev", sa.Float, nullable=True))
    op.add_column("images", sa.Column("fwhm", sa.Float, nullable=True))
    op.add_column("images", sa.Column("detected_stars", sa.Integer, nullable=True))

    # Guiding group
    op.add_column("images", sa.Column("guiding_rms_arcsec", sa.Float, nullable=True))
    op.add_column("images", sa.Column("guiding_rms_ra_arcsec", sa.Float, nullable=True))
    op.add_column("images", sa.Column("guiding_rms_dec_arcsec", sa.Float, nullable=True))

    # ADU group
    op.add_column("images", sa.Column("adu_stdev", sa.Float, nullable=True))
    op.add_column("images", sa.Column("adu_mean", sa.Float, nullable=True))
    op.add_column("images", sa.Column("adu_median", sa.Float, nullable=True))
    op.add_column("images", sa.Column("adu_min", sa.Integer, nullable=True))
    op.add_column("images", sa.Column("adu_max", sa.Integer, nullable=True))

    # Focuser group
    op.add_column("images", sa.Column("focuser_position", sa.Integer, nullable=True))
    op.add_column("images", sa.Column("focuser_temp", sa.Float, nullable=True))

    # Mount group
    op.add_column("images", sa.Column("rotator_position", sa.Float, nullable=True))
    op.add_column("images", sa.Column("pier_side", sa.String(10), nullable=True))
    op.add_column("images", sa.Column("airmass", sa.Float, nullable=True))

    # Weather group
    op.add_column("images", sa.Column("ambient_temp", sa.Float, nullable=True))
    op.add_column("images", sa.Column("dew_point", sa.Float, nullable=True))
    op.add_column("images", sa.Column("humidity", sa.Float, nullable=True))
    op.add_column("images", sa.Column("pressure", sa.Float, nullable=True))
    op.add_column("images", sa.Column("wind_speed", sa.Float, nullable=True))
    op.add_column("images", sa.Column("wind_direction", sa.Float, nullable=True))
    op.add_column("images", sa.Column("wind_gust", sa.Float, nullable=True))
    op.add_column("images", sa.Column("cloud_cover", sa.Float, nullable=True))
    op.add_column("images", sa.Column("sky_quality", sa.Float, nullable=True))

    # Display settings on user_settings
    op.add_column(
        "user_settings",
        sa.Column("display", JSONB, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    # Display settings
    op.drop_column("user_settings", "display")

    # Weather group
    op.drop_column("images", "sky_quality")
    op.drop_column("images", "cloud_cover")
    op.drop_column("images", "wind_gust")
    op.drop_column("images", "wind_direction")
    op.drop_column("images", "wind_speed")
    op.drop_column("images", "pressure")
    op.drop_column("images", "humidity")
    op.drop_column("images", "dew_point")
    op.drop_column("images", "ambient_temp")

    # Mount group
    op.drop_column("images", "airmass")
    op.drop_column("images", "pier_side")
    op.drop_column("images", "rotator_position")

    # Focuser group
    op.drop_column("images", "focuser_temp")
    op.drop_column("images", "focuser_position")

    # ADU group
    op.drop_column("images", "adu_max")
    op.drop_column("images", "adu_min")
    op.drop_column("images", "adu_median")
    op.drop_column("images", "adu_mean")
    op.drop_column("images", "adu_stdev")

    # Guiding group
    op.drop_column("images", "guiding_rms_dec_arcsec")
    op.drop_column("images", "guiding_rms_ra_arcsec")
    op.drop_column("images", "guiding_rms_arcsec")

    # Quality group
    op.drop_column("images", "detected_stars")
    op.drop_column("images", "fwhm")
    op.drop_column("images", "hfr_stdev")
