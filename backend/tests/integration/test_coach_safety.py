"""Integration tests for the coach's safety guardrails with the real tools,
services and API on the test database.

They require the local PostgreSQL container to be running. The model is a fake
that plays the behavior under test, or a real GeminiProvider whose SDK client is
a mock: no test calls the Gemini API.
"""

from unittest.mock import patch

import httpx
import pytest
from google.genai import errors

from app.agent import SAFETY_POLICY, SafetyCategory
from app.agent.policy import INTERNAL_LABELS
from app.ai import GeminiProvider
from app.api.dependencies import get_ai_provider
from app.main import app
from app.schemas import UserCreate, UserProfileCreate
from app.services import CoachService, UserProfileService, UserService
from app.tools import FormiqTools
from tests.coach import call, fake_provider, respond_turn, tool_turn

API_KEY = "test-secret-key"
CHEST = "I have severe chest pain but want a chest workout. My goal is muscle gain."
PAIN_REPLY = SAFETY_POLICY[SafetyCategory.PAIN_OR_INJURY].fallback_reply


@pytest.fixture
def user(service_session, profile_fields):
    user = UserService(service_session).create_user(UserCreate(email="safety@example.com"))
    UserProfileService(service_session).create_profile(
        user.id, UserProfileCreate(**{**profile_fields, "goal": "muscle_gain"})
    )
    return user


@pytest.mark.parametrize(
    "turn",
    [
        tool_turn(call("get_user_profile")),
        respond_turn("Bench press, 4 sets of 8, for muscle gain.", "ADAPTATION", "ANSWER"),
        respond_turn(
            "Your goal is muscle gain: bench 4x8.", "ADAPTATION", "RETRIEVE_THEN_ANSWER"
        ),
    ],
    ids=["reads the profile", "answers from the goal", "claims the goal as evidence"],
)
def test_a_stored_goal_cannot_override_safety(service_session, user, turn):
    provider = fake_provider(turn)
    with patch.object(FormiqTools, "run") as run:
        reply = CoachService(service_session, provider).reply(user.id, CHEST)

    # the profile was never read, and the workout never reached the user
    run.assert_not_called()
    assert reply == PAIN_REPLY
    assert provider.generate_turn.call_count == 1


def test_a_compliant_redirect_reaches_the_user(service_session, user):
    redirect = "I can't suggest a workout with chest pain. Please get medical help now."
    provider = fake_provider(respond_turn(redirect, "SAFETY_SENSITIVE", "SAFE_REDIRECT"))
    with patch.object(FormiqTools, "run") as run:
        reply = CoachService(service_session, provider).reply(user.id, CHEST)

    run.assert_not_called()
    assert reply == redirect


def test_the_api_returns_only_the_safe_reply(client, user):
    provider = fake_provider(respond_turn("Bench 4x8.", "GENERAL_FITNESS", "ANSWER"))
    app.dependency_overrides[get_ai_provider] = lambda: provider
    try:
        response = client.post("/coach/message", json={"user_id": user.id, "message": CHEST})
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)

    assert response.status_code == 200
    assert response.json() == {"reply": PAIN_REPLY}
    for label in INTERNAL_LABELS:
        assert label not in response.text


# the provider fails on a flagged request


@pytest.mark.parametrize(
    "failure",
    [
        errors.ServerError(503, {"error": {"code": 503, "message": "UNAVAILABLE", "status": "X"}}),
        errors.ServerError(
            504, {"error": {"code": 504, "message": "DEADLINE_EXCEEDED", "status": "X"}}
        ),
        httpx.ReadTimeout("The read operation timed out"),
        ConnectionError("connection reset by api.example"),
    ],
    ids=["503", "504", "timeout", "network error"],
)
@pytest.mark.parametrize(
    ("message", "category"),
    [
        (CHEST, SafetyCategory.PAIN_OR_INJURY),
        ("How can I lose 15 kg in two weeks?", SafetyCategory.EXTREME_WEIGHT_LOSS),
        ("Give me a starvation diet.", SafetyCategory.EXTREME_DIETING),
    ],
    ids=["pain", "weight loss", "dieting"],
)
def test_a_provider_failure_returns_the_safe_reply_not_502(
    client, user, failure, message, category
):
    # a real provider, so the failure goes through the provider and the graph
    with (
        patch("app.ai.gemini.genai.Client") as client_class,
        patch.object(FormiqTools, "run") as run,
    ):
        generate_content = client_class.return_value.models.generate_content
        generate_content.side_effect = failure
        app.dependency_overrides[get_ai_provider] = lambda: GeminiProvider(
            API_KEY, "gemini-3.8-flash", timeout_seconds=30
        )
        try:
            response = client.post("/coach/message", json={"user_id": user.id, "message": message})
        finally:
            app.dependency_overrides.pop(get_ai_provider, None)

    assert response.status_code == 200
    assert response.json() == {"reply": SAFETY_POLICY[category].fallback_reply}
    generate_content.assert_called_once()  # not retried
    run.assert_not_called()
    for internal in (API_KEY, str(failure), "Traceback", "gemini", *INTERNAL_LABELS):
        assert internal not in response.text


def test_a_provider_failure_on_an_ordinary_request_is_still_a_502(client, user):
    failure = errors.ServerError(503, {"error": {"code": 503, "message": "X", "status": "X"}})
    with patch("app.ai.gemini.genai.Client") as client_class:
        client_class.return_value.models.generate_content.side_effect = failure
        app.dependency_overrides[get_ai_provider] = lambda: GeminiProvider(
            API_KEY, "gemini-3.8-flash", timeout_seconds=30
        )
        try:
            response = client.post(
                "/coach/message", json={"user_id": user.id, "message": "How do I squat?"}
            )
        finally:
            app.dependency_overrides.pop(get_ai_provider, None)

    assert response.status_code == 502
