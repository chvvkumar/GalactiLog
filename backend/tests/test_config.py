from app.config import Settings


def test_settings_defaults():
    s = Settings()
    assert "postgresql" in s.database_url
    assert "redis" in s.redis_url
    assert s.thumbnail_max_width == 800


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("ASTRO_THUMBNAIL_MAX_WIDTH", "400")
    s = Settings()
    assert s.thumbnail_max_width == 400
