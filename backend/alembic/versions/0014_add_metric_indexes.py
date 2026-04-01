"""Add indexes on metric columns for HAVING clause performance."""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_images_median_hfr", "images", ["median_hfr"], if_not_exists=True)
    op.create_index("ix_images_fwhm", "images", ["fwhm"], if_not_exists=True)
    op.create_index("ix_images_eccentricity", "images", ["eccentricity"], if_not_exists=True)
    op.create_index("ix_images_detected_stars", "images", ["detected_stars"], if_not_exists=True)
    op.create_index("ix_images_guiding_rms_arcsec", "images", ["guiding_rms_arcsec"], if_not_exists=True)
    op.create_index("ix_images_adu_mean", "images", ["adu_mean"], if_not_exists=True)
    op.create_index("ix_images_focuser_temp", "images", ["focuser_temp"], if_not_exists=True)
    op.create_index("ix_images_ambient_temp", "images", ["ambient_temp"], if_not_exists=True)
    op.create_index("ix_images_humidity", "images", ["humidity"], if_not_exists=True)
    op.create_index("ix_images_airmass", "images", ["airmass"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_images_airmass", "images")
    op.drop_index("ix_images_humidity", "images")
    op.drop_index("ix_images_ambient_temp", "images")
    op.drop_index("ix_images_focuser_temp", "images")
    op.drop_index("ix_images_adu_mean", "images")
    op.drop_index("ix_images_guiding_rms_arcsec", "images")
    op.drop_index("ix_images_detected_stars", "images")
    op.drop_index("ix_images_eccentricity", "images")
    op.drop_index("ix_images_fwhm", "images")
    op.drop_index("ix_images_median_hfr", "images")
