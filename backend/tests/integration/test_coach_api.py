"""Integration tests for the coach API route.

They require the local PostgreSQL container to be running. The client fixture
sends every request to the test database. The model is a mock, or a real
GeminiProvider whose SDK client is a mock: no test calls the Gemini API.
"""

from unittest.mock import Mock, patch

import httpx
import pytest
from google.genai import errors

from app.ai import GeminiProvider
from app.api.dependencies import get_ai_provider
from app.main import app

API_KEY = "test-secret-key"
URL = "/coach/message"


@pytest.fixture
def user_id(client):
    return client.post("/users", json={"email": "coach-api@example.com"}).json()["id"]


@pytest.fixture
def use_provider(client):
    """Makes the route use the given provider instead of the configured one."""

    def use(provider):
        app.dependency_overrides[get_ai_provider] = lambda: provider
        return provider

    try:
        yield use
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)


@pytest.fixture
def provider(use_provider):
    provider = Mock(spec=GeminiProvider)
    provider.generate.return_value = "Start with three sets of eight."
    return use_provider(provider)


def test_message_returns_200_and_the_reply(client, user_id, provider):
    response = client.post(URL, json={"user_id": user_id, "message": "  How should I start?  "})

    assert response.status_code == 200
    assert response.json() == {"reply": "Start with three sets of eight."}
    # surrounding whitespace is dropped before the model sees the message
    assert provider.generate.call_args.args == ("How should I start?",)


def test_message_of_an_unknown_user_returns_404(client, provider):
    response = client.post(URL, json={"user_id": 2_147_483_647, "message": "Hi"})

    assert response.status_code == 404
    assert response.json() == {"detail": "user 2147483647 does not exist"}
    provider.generate.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        {"message": "Hi"},
        {"user_id": 1},
        {"user_id": 1, "message": ""},
        {"user_id": 1, "message": "   "},
        {"user_id": 1, "message": "x" * 4001},
        {"user_id": 1, "message": 42},
        {"user_id": 0, "message": "Hi"},
        {"user_id": 2_147_483_648, "message": "Hi"},
        {"user_id": "me", "message": "Hi"},
    ],
    ids=[
        "no user_id",
        "no message",
        "empty message",
        "blank message",
        "message too long",
        "message not text",
        "user_id 0",
        "user_id beyond the column",
        "user_id not a number",
    ],
)
def test_invalid_body_returns_422(client, provider, body):
    response = client.post(URL, json=body)

    assert response.status_code == 422
    provider.generate.assert_not_called()


def test_longest_message_is_accepted(client, user_id, provider):
    response = client.post(URL, json={"user_id": user_id, "message": "x" * 4000})

    assert response.status_code == 200


def test_missing_api_key_returns_503(client, user_id, use_provider):
    use_provider(GeminiProvider(None, "gemini-3.8-flash", timeout_seconds=30))

    response = client.post(URL, json={"user_id": user_id, "message": "Hi"})

    assert response.status_code == 503
    assert response.json() == {"detail": "the AI coach is not configured"}


@pytest.mark.parametrize(
    "failure",
    [
        errors.ClientError(
            429,
            {"error": {"code": 429, "message": "Quota exceeded for project 1234", "status": "X"}},
        ),
        errors.ServerError(500, {"error": {"code": 500, "message": "Internal", "status": "X"}}),
        ConnectionError("connection reset by api.example"),
        httpx.ReadTimeout("The read operation timed out"),
    ],
    ids=["rate limit", "server error", "network error", "timeout"],
)
def test_provider_failure_returns_502_without_its_details(client, user_id, use_provider, failure):
    # a real provider, so the request goes through the provider and the graph
    with patch("app.ai.gemini.genai.Client") as client_class:
        client_class.return_value.models.generate_content.side_effect = failure
        use_provider(GeminiProvider(API_KEY, "gemini-3.8-flash", timeout_seconds=30))

        response = client.post(URL, json={"user_id": user_id, "message": "Hi"})

    assert response.status_code == 502
    assert response.json() == {"detail": "the AI coach could not answer; try again later"}
    for internal in (API_KEY, str(failure), "Traceback", "gemini"):
        assert internal not in response.text


def test_reply_without_text_returns_502(client, user_id, use_provider):
    with patch("app.ai.gemini.genai.Client") as client_class:
        client_class.return_value.models.generate_content.return_value.text = None
        use_provider(GeminiProvider(API_KEY, "gemini-3.8-flash", timeout_seconds=30))

        response = client.post(URL, json={"user_id": user_id, "message": "Hi"})

    assert response.status_code == 502
