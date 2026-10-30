import pytest
from app.core.config import settings


def test_settings_loaded_from_env() -> None:
    assert settings.app_name
    assert settings.database_url.startswith("mysql+asyncmy://")
    assert settings.database_url_sync.startswith("mysql+pymysql://")


def test_token_policy_defaults() -> None:
    assert settings.access_token_ttl == 900
    assert settings.refresh_token_ttl == 604800
    assert settings.login_max_attempts == 5


def test_cors_origins_parsed_to_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "cors_origins", " http://a.test , ,http://b.test")
    assert settings.cors_origins_list == ["http://a.test", "http://b.test"]
