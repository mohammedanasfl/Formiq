"""Integration tests for CoachService.

They require the local PostgreSQL container to be running (test database). The
model is a mock: no test calls the Gemini API. The tools are the real ones,
reading the test database through the services.
"""

from unittest.mock import Mock

import pytest

from app.agent import COACH_INSTRUCTIONS, RESPOND
from app.ai import AIProviderError, AIProviderNotConfiguredError, GeminiProvider, user_content
from app.schemas import UserCreate, UserProfileCreate, WorkoutPlanCreate
from app.services import CoachService, UserProfileService, UserService, WorkoutPlanService
from app.services.exceptions import UserNotFoundError
from app.tools import TOOL_DECLARATIONS
from tests.coach import (
    call,
    fake_provider,
    respond_turn,
    sent_contents,
    tool_responses,
    tool_turn,
)


@pytest.fixture
def user(service_session):
    return UserService(service_session).create_user(UserCreate(email="coach@example.com"))


@pytest.fixture
def other_user(service_session):
    return UserService(service_session).create_user(UserCreate(email="coach-other@example.com"))


@pytest.fixture
def provider():
    return fake_provider(respond_turn("Start with three sets of eight."))


@pytest.fixture
def service(service_session, provider):
    return CoachService(service_session, provider)


def test_reply_comes_from_the_model_through_the_graph(service, user, provider):
    assert service.reply(user.id, "How should I start?") == "Start with three sets of eight."
    provider.generate_turn.assert_called_once_with(
        [user_content("How should I start?")],
        instructions=COACH_INSTRUCTIONS,
        tools=[*TOOL_DECLARATIONS, RESPOND],
        required_tool_names=[tool.name for tool in [*TOOL_DECLARATIONS, RESPOND]],
    )


def test_unknown_user_is_not_found_and_the_model_is_not_called(service, provider):
    with pytest.raises(UserNotFoundError, match="user 2147483647 does not exist"):
        service.reply(2_147_483_647, "Hi")

    provider.generate_turn.assert_not_called()


def test_no_transaction_is_open_while_the_model_answers(service_session, user, profile_fields):
    UserProfileService(service_session).create_profile(user.id, UserProfileCreate(**profile_fields))
    in_transaction = []
    turns = iter([tool_turn(call("get_user_profile")), respond_turn("Rest today.")])

    def answer(contents, **kwargs):
        in_transaction.append(service_session.in_transaction())
        return next(turns)

    provider = Mock(spec=GeminiProvider)
    provider.generate_turn.side_effect = answer

    assert CoachService(service_session, provider).reply(user.id, "Hi") == "Rest today."
    # neither before the first request nor after the tool read the database
    assert in_transaction == [False, False]


@pytest.mark.parametrize(
    "failure",
    [AIProviderNotConfiguredError("GEMINI_API_KEY is not set"), AIProviderError("failed")],
)
def test_provider_errors_reach_the_caller(service, user, provider, failure):
    provider.generate_turn.side_effect = failure

    with pytest.raises(AIProviderError) as raised:
        service.reply(user.id, "Hi")

    assert raised.value is failure


def test_the_users_data_reaches_the_model_through_the_tools(
    service_session, user, profile_fields
):
    UserProfileService(service_session).create_profile(
        user.id, UserProfileCreate(**{**profile_fields, "goal": "muscle_gain"})
    )
    provider = fake_provider(
        tool_turn(call("get_user_profile"), call("search_exercises", difficulty="BEGINNER")),
        respond_turn("Your goal is muscle gain."),
    )

    reply = CoachService(service_session, provider).reply(user.id, "What is my current goal?")

    assert reply == "Your goal is muscle gain."
    profile, search = tool_responses(sent_contents(provider, 1)[-1])
    assert profile.response["output"]["user_id"] == user.id
    assert profile.response["output"]["profile"]["goal"] == "muscle_gain"
    assert search.response["output"]["count"] > 0


def test_the_model_cannot_reach_another_users_data(service_session, user, other_user):
    plan = WorkoutPlanService(service_session).create_plan(
        other_user.id, WorkoutPlanCreate(name="Not yours")
    )
    provider = fake_provider(
        tool_turn(
            call("get_workout_plan", plan_id=plan.id),
            call("get_user_profile", user_id=other_user.id),
        ),
        respond_turn("I could not find that plan."),
    )

    CoachService(service_session, provider).reply(user.id, f"Show me plan {plan.id}")

    by_id, by_user = tool_responses(sent_contents(provider, 1)[-1])
    assert by_id.response["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert by_user.response["error"]["code"] == "INVALID_INPUT"
    assert "Not yours" not in str(sent_contents(provider, 1))
