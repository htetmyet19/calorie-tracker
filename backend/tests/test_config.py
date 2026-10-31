import importlib

import pytest

from app import config


@pytest.fixture
def reload_config(monkeypatch):
    """Reload app.config under monkeypatched env; restore the real settings afterwards."""
    def _reload():
        return importlib.reload(config)

    yield _reload
    monkeypatch.undo()
    importlib.reload(config)


def test_supabase_settings_load(monkeypatch, reload_config):
    # Set env first: load_dotenv() does not override variables that already exist.
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "pub-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "jwt-secret")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.delenv("SUPABASE_TIMEOUT", raising=False)

    cfg = reload_config()

    assert cfg.SUPABASE_URL == "http://127.0.0.1:54321"
    assert cfg.SUPABASE_PUBLISHABLE_KEY == "pub-key"
    assert cfg.SUPABASE_JWT_SECRET == "jwt-secret"
    assert cfg.SUPABASE_SERVICE_ROLE_KEY == "service-key"
    assert cfg.SUPABASE_TIMEOUT == 10.0
