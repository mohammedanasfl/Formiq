from pathlib import Path
from unittest.mock import patch

import pytest
from google.genai import types
from pydantic import ValidationError

from app.ai import AIProviderNotConfiguredError
from app.api import dependencies
from app.api.dependencies import get_ai_provider
from app.core.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


@pytest.fixture
def no_gemini_environment(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_TIMEOUT_SECONDS", raising=False)


@pytest.fixture
def provider_cache():
    """get_ai_provider is cached: each test starts and ends with an empty cache."""
    get_ai_provider.cache_clear()
    yield
    get_ai_provider.cache_clear()


def test_defaults_are_gemini_flash_without_a_key(no_gemini_environment):
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://x")

    assert settings.gemini_model == "gemini-3.8-flash"
    assert settings.gemini_api_key is None
    assert settings.gemini_timeout_seconds == 30


def test_key_model_and_timeout_come_from_the_environment(no_gemini_environment, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-other")
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "12.5")

    settings = Settings(_env_file=None, database_url="postgresql+psycopg://x")

    assert settings.gemini_api_key.get_secret_value() == "test-secret-key"
    assert settings.gemini_model == "gemini-other"
    assert settings.gemini_timeout_seconds == 12.5
    # the key stays out of reprs, and so out of logs and tracebacks
    assert "test-secret-key" not in repr(settings)
    assert "test-secret-key" not in str(settings.model_dump())


def test_env_example_names_the_variables_without_a_key():
    lines = ENV_EXAMPLE.read_text().splitlines()

    assert "GEMINI_API_KEY=" in lines
    assert "GEMINI_MODEL=gemini-3.8-flash" in lines
    assert "GEMINI_TIMEOUT_SECONDS=30" in lines


@pytest.mark.parametrize("timeout", ["0", "-5", "inf", "nan", "soon"])
def test_timeout_must_be_a_positive_number(no_gemini_environment, monkeypatch, timeout):
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", timeout)

    with pytest.raises(ValidationError, match="gemini_timeout_seconds"):
        Settings(_env_file=None, database_url="postgresql+psycopg://x")


def test_provider_uses_the_configured_key_model_and_timeout(provider_cache, monkeypatch):
    configured = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://x",
        gemini_api_key="test-secret-key",
        gemini_model="gemini-other",
        gemini_timeout_seconds=12.5,
    )
    monkeypatch.setattr(dependencies, "settings", configured)

    with patch("app.ai.gemini.genai.Client") as client_class:
        provider = get_ai_provider()

    assert provider.model == "gemini-other"
    client_class.assert_called_once_with(
        api_key="test-secret-key", http_options=types.HttpOptions(timeout=12_500)
    )
    # one provider, and so one client, for every request
    assert get_ai_provider() is provider


@pytest.mark.parametrize("api_key", [None, ""])
def test_provider_without_a_key_refuses_to_generate(provider_cache, monkeypatch, api_key):
    configured = Settings(
        _env_file=None, database_url="postgresql+psycopg://x", gemini_api_key=api_key
    )
    monkeypatch.setattr(dependencies, "settings", configured)

    with patch("app.ai.gemini.genai.Client") as client_class:
        provider = get_ai_provider()
        with pytest.raises(AIProviderNotConfiguredError, match="GEMINI_API_KEY is not set"):
            provider.generate("Hi", instructions="Be brief")

    client_class.assert_not_called()
