"""Integration tests for the coach API route.

They require the local PostgreSQL container to be running. The client fixture
sends every request to the test database. The model is a mock, or a real
GeminiProvider whose SDK client is a mock: no test calls the Gemini API.
"""

from unittest.mock import patch

import httpx
import pytest
from google.genai import errors, types

from app.ai import GeminiProvider, user_content
from app.api.dependencies import get_ai_provider
from app.main import app
from tests.coach import fake_provider, respond_turn

API_KEY = "test-secret-key"
URL = "/coach/message"


def respond_response(reply, intent, decision):
    """Gemini's response with the respond call that ends the coach's turn."""
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name="respond",
                                args={"intent": intent, "decision": decision, "reply": reply},
                            )
                        )
                    ],
                )
            )
        ]
    )


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
    return use_provider(fake_provider(respond_turn("Start with three sets of eight.")))


def test_message_returns_200_and_the_reply(client, user_id, provider):
    response = client.post(URL, json={"user_id": user_id, "message": "  How should I start?  "})

    assert response.status_code == 200
    assert response.json() == {"reply": "Start with three sets of eight."}
    # surrounding whitespace is dropped before the model sees the message
    assert provider.generate_turn.call_args.args == ([user_content("How should I start?")],)


def test_message_of_an_unknown_user_returns_404(client, provider):
    response = client.post(URL, json={"user_id": 2_147_483_647, "message": "Hi"})

    assert response.status_code == 404
    assert response.json() == {"detail": "user 2147483647 does not exist"}
    provider.generate_turn.assert_not_called()


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
    provider.generate_turn.assert_not_called()


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
        client_class.return_value.models.generate_content.return_value = (
            types.GenerateContentResponse(candidates=[])
        )
        use_provider(GeminiProvider(API_KEY, "gemini-3.8-flash", timeout_seconds=30))

        response = client.post(URL, json={"user_id": user_id, "message": "Hi"})

    assert response.status_code == 502


def test_the_coach_answers_after_a_tool_call(client, user_id, use_provider):
    # a real provider and graph, with the real tools on the test database
    calls_profile = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=types.FunctionCall(name="get_user_profile"))],
                )
            )
        ]
    )
    answers = respond_response("Set up a profile.", "PROFILE", "CANNOT_ANSWER")
    with patch("app.ai.gemini.genai.Client") as client_class:
        generate_content = client_class.return_value.models.generate_content
        generate_content.side_effect = [calls_profile, answers]
        use_provider(GeminiProvider(API_KEY, "gemini-3.8-flash", timeout_seconds=30))

        response = client.post(URL, json={"user_id": user_id, "message": "What is my goal?"})

    assert response.status_code == 200
    assert response.json() == {"reply": "Set up a profile."}
    # the user has no profile: the model got the tool's error, the client only the reply
    tool_result = generate_content.call_args.kwargs["contents"][-1].parts[0].function_response
    assert tool_result.response["error"]["code"] == "PROFILE_NOT_FOUND"


@pytest.mark.parametrize(("requested", "status"), [(20, 200), (21, 502)])
def test_a_turn_requesting_too_many_tool_calls_is_a_controlled_502(
    client, user_id, use_provider, requested, status
):
    calls = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name="get_exercise", args={"exercise_id": 1}
                            )
                        )
                    ]
                    * requested,
                )
            )
        ]
    )
    answers = respond_response("Done.", "EXERCISE", "RETRIEVE_THEN_ANSWER")
    with patch("app.ai.gemini.genai.Client") as client_class:
        generate_content = client_class.return_value.models.generate_content
        generate_content.side_effect = [calls, answers]
        use_provider(GeminiProvider(API_KEY, "gemini-3.8-flash", timeout_seconds=30))

        response = client.post(URL, json={"user_id": user_id, "message": "Exercise 1, often?"})

    assert response.status_code == status
    if status == 502:
        assert response.json() == {"detail": "the AI coach could not answer; try again later"}
        assert generate_content.call_count == 1
