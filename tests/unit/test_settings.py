import pytest
from pydantic import ValidationError

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


def test_provider_tokens_are_optional_and_secret() -> None:
    settings = Settings(github_token="sensitive-token", _env_file=None)

    assert settings.gitlab_token is None
    assert settings.github_token is not None
    assert settings.github_token.get_secret_value() == "sensitive-token"
    assert "sensitive-token" not in repr(settings)


def test_provider_api_urls_require_tls() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(gitlab_api_url="http://gitlab.example/api/v4", _env_file=None)
