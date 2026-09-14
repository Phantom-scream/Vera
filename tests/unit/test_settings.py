import pytest

from vera.config import Environment, Settings


def test_settings_have_safe_development_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "Vera"
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000


def test_settings_load_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_ENVIRONMENT", "test")
    monkeypatch.setenv("VERA_API_PORT", "9000")

    settings = Settings(_env_file=None)

    assert settings.environment is Environment.TEST
    assert settings.api_port == 9000
