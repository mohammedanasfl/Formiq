"""Tests for GeminiProvider. The SDK client is replaced by a mock, or its HTTP
transport by httpx.MockTransport: no test calls the Gemini API."""

import logging
from unittest.mock import patch

import httpx
import pytest
from google import genai
from google.genai import errors, types

from app.ai import AIProviderError, AIProviderNotConfiguredError, GeminiProvider

API_KEY = "test-secret-key"
MODEL = "gemini-3.8-flash"
TIMEOUT_SECONDS = 30


def response_with_text(text):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]))
        ]
    )


@pytest.fixture
def client():
    """The SDK client that the provider creates."""
    with patch("app.ai.gemini.genai.Client") as client_class:
        yield client_class.return_value


@pytest.fixture
def provider(client):
    return GeminiProvider(API_KEY, MODEL, timeout_seconds=TIMEOUT_SECONDS)


def test_generate_sends_the_message_and_instructions_to_the_model(provider, client):
    client.models.generate_content.return_value = response_with_text("Start with three sets.")

    reply = provider.generate("How should I start?", instructions="Be a coach")

    assert reply == "Start with three sets."
    client.models.generate_content.assert_called_once_with(
        model=MODEL,
        contents="How should I start?",
        config=types.GenerateContentConfig(system_instruction="Be a coach"),
    )


def test_client_gets_the_key_and_timeout_explicitly():
    with patch("app.ai.gemini.genai.Client") as client_class:
        GeminiProvider(API_KEY, MODEL, timeout_seconds=TIMEOUT_SECONDS)

    client_class.assert_called_once_with(
        api_key=API_KEY, http_options=types.HttpOptions(timeout=30_000)
    )
    # no retry_options: the SDK makes a single attempt
    assert client_class.call_args.kwargs["http_options"].retry_options is None


@pytest.mark.parametrize(
    ("timeout_seconds", "milliseconds"),
    [(30, 30_000), (12.5, 12_500), (0.0001, 1)],
    ids=["whole seconds", "fraction of a second", "rounded up, never 0 (no timeout)"],
)
def test_timeout_is_given_to_the_sdk_in_milliseconds(timeout_seconds, milliseconds):
    with patch("app.ai.gemini.genai.Client") as client_class:
        GeminiProvider(API_KEY, MODEL, timeout_seconds=timeout_seconds)

    assert client_class.call_args.kwargs["http_options"].timeout == milliseconds


@pytest.mark.parametrize("api_key", [None, ""])
def test_without_a_key_nothing_is_called(api_key):
    with patch("app.ai.gemini.genai.Client") as client_class:
        provider = GeminiProvider(api_key, MODEL, timeout_seconds=TIMEOUT_SECONDS)

        with pytest.raises(AIProviderNotConfiguredError, match="GEMINI_API_KEY is not set"):
            provider.generate("Hi", instructions="Be a coach")

    client_class.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        errors.ClientError(
            429,
            {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}},
        ),
        errors.ServerError(
            503, {"error": {"code": 503, "message": "Overloaded", "status": "UNAVAILABLE"}}
        ),
        httpx.ConnectTimeout("timed out"),
        httpx.ReadTimeout("The read operation timed out"),
        ValueError("unexpected response"),
    ],
    ids=["rate limit", "server error", "connect timeout", "read timeout", "other SDK error"],
)
def test_request_failures_become_provider_errors(provider, client, caplog, monkeypatch, failure):
    # Alembic's fileConfig, run in this process by the migration tests, disables
    # the loggers that exist by then. The application runs Alembic separately.
    monkeypatch.setattr(logging.getLogger("app.ai.gemini"), "disabled", False)
    client.models.generate_content.side_effect = failure

    with caplog.at_level(logging.ERROR, logger="app.ai.gemini"):
        with pytest.raises(AIProviderError) as raised:
            provider.generate("Hi", instructions="Be a coach")

    assert not isinstance(raised.value, AIProviderNotConfiguredError)
    assert str(raised.value) == f"the {MODEL} request failed"
    # the cause is kept for the server log, and the key is in neither
    assert raised.value.__cause__ is failure
    assert f"Gemini request to {MODEL} failed" in caplog.text
    assert API_KEY not in caplog.text
    assert API_KEY not in str(raised.value)


@pytest.mark.parametrize(
    "response",
    [
        types.GenerateContentResponse(candidates=[]),
        types.GenerateContentResponse(
            prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason="SAFETY")
        ),
        response_with_text(""),
    ],
    ids=["no candidates", "blocked prompt", "empty text"],
)
def test_a_reply_without_text_is_a_provider_error(provider, client, response):
    client.models.generate_content.return_value = response

    with pytest.raises(AIProviderError, match="returned no text"):
        provider.generate("Hi", instructions="Be a coach")


@pytest.fixture
def sdk_with_transport():
    """Makes the provider build a real SDK client whose HTTP requests go to the
    given handler instead of the network."""
    real_client = genai.Client

    def use(handler):
        transport = httpx.MockTransport(handler)

        def client_with_transport(**kwargs):
            http_options = kwargs["http_options"].model_copy(
                update={"httpx_client": httpx.Client(transport=transport)}
            )
            return real_client(**{**kwargs, "http_options": http_options})

        return patch("app.ai.gemini.genai.Client", side_effect=client_with_transport)

    return use


def test_sdk_requests_carry_the_timeout(sdk_with_transport):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(
            200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": "Hi"}]}}]}
        )

    with sdk_with_transport(reply):
        provider = GeminiProvider(API_KEY, MODEL, timeout_seconds=TIMEOUT_SECONDS)
        assert provider.generate("Hi", instructions="Be a coach") == "Hi"

    (request,) = requests
    assert request.extensions["timeout"] == dict.fromkeys(
        ["connect", "read", "write", "pool"], float(TIMEOUT_SECONDS)
    )
    # the key goes in a header, never in the URL
    assert request.headers["x-goog-api-key"] == API_KEY
    assert API_KEY not in str(request.url)


def test_timeout_is_a_provider_error_after_one_attempt(sdk_with_transport, caplog, monkeypatch):
    # see test_request_failures_become_provider_errors
    monkeypatch.setattr(logging.getLogger("app.ai.gemini"), "disabled", False)
    attempts = []

    def time_out(request):
        attempts.append(request)
        raise httpx.ReadTimeout("The read operation timed out", request=request)

    with sdk_with_transport(time_out), caplog.at_level(logging.ERROR, logger="app.ai.gemini"):
        provider = GeminiProvider(API_KEY, MODEL, timeout_seconds=TIMEOUT_SECONDS)
        with pytest.raises(AIProviderError) as raised:
            provider.generate("Hi", instructions="Be a coach")

    assert len(attempts) == 1  # no retry
    assert str(raised.value) == f"the {MODEL} request failed"
    assert isinstance(raised.value.__cause__, httpx.ReadTimeout)
    assert "ReadTimeout" in caplog.text  # the cause is in the server log
    assert API_KEY not in caplog.text
    assert API_KEY not in str(raised.value)
