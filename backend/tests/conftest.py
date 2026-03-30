import os

os.environ.setdefault("ASTRO_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("ASTRO_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("ASTRO_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("ASTRO_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("ASTRO_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("ASTRO_SECURE_COOKIES", "false")
