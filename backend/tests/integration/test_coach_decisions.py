"""Integration tests for the coach's decision policy with the real tools and
services on the test database.

They require the local PostgreSQL container to be running. The model is a fake
that plays the decisions under test: no test calls the Gemini API.
"""

import pytest

from app.agent import CANNOT_ANSWER_REPLY
from app.schemas import UserCreate, UserProfileCreate, WorkoutPlanCreate
from app.services import CoachService, UserProfileService, UserService, WorkoutPlanService
from tests.coach import call, fake_provider, respond_turn, sent_contents, tool_responses, tool_turn


@pytest.fixture
def user(service_session):
    return UserService(service_session).create_user(UserCreate(email="decide-a@example.com"))


@pytest.fixture
def other_user(service_session):
    return UserService(service_session).create_user(UserCreate(email="decide-b@example.com"))


def results_given(provider, request):
    return [item.response for item in tool_responses(sent_contents(provider, request)[-1])]


def test_the_stored_profile_beats_the_models_assumption(service_session, user, profile_fields):
    UserProfileService(service_session).create_profile(
        user.id, UserProfileCreate(**{**profile_fields, "goal": "muscle_gain"})
    )
    provider = fake_provider(
        respond_turn("Your goal is fat loss.", "PROFILE", "ANSWER"),
        tool_turn(call("get_user_profile")),
        respond_turn("Your goal is muscle gain.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
    )

    reply = CoachService(service_session, provider).reply(user.id, "What is my goal?")

    assert reply == "Your goal is muscle gain."
    (profile,) = results_given(provider, 2)
    assert profile["output"]["profile"]["goal"] == "muscle_gain"


def test_another_users_plan_is_not_data_to_answer_from(service_session, user, other_user):
    theirs = WorkoutPlanService(service_session).create_plan(
        other_user.id, WorkoutPlanCreate(name="B's secret plan")
    )
    provider = fake_provider(
        tool_turn(call("get_workout_plan", plan_id=theirs.id)),
        respond_turn("Plan: B's secret plan.", "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        respond_turn("I could not find that plan.", "WORKOUT_PLAN", "CANNOT_ANSWER"),
    )

    reply = CoachService(service_session, provider).reply(user.id, f"Show plan {theirs.id}")

    (not_found,) = results_given(provider, 1)
    (rejected,) = results_given(provider, 2)
    assert not_found["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert rejected["error"]["code"] == "DECISION_REJECTED"
    assert reply == "I could not find that plan."


def test_a_missing_profile_is_not_filled_in(service_session, user):
    provider = fake_provider(
        tool_turn(call("get_user_profile")),
        respond_turn("You train 4 times a week.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
        respond_turn("You have not set up your profile yet.", "PROFILE", "CANNOT_ANSWER"),
    )

    reply = CoachService(service_session, provider).reply(user.id, "How often do I train?")

    (missing,) = results_given(provider, 1)
    assert missing["error"]["code"] == "PROFILE_NOT_FOUND"
    assert results_given(provider, 2)[0]["error"]["code"] == "DECISION_REJECTED"
    assert reply == "You have not set up your profile yet."


def test_a_guessed_catalog_id_never_reaches_the_catalog(service_session, user):
    provider = fake_provider(
        tool_turn(call("search_exercises", equipment_id=3)),
        tool_turn(call("search_exercises", movement_pattern="HORIZONTAL_PUSH")),
        respond_turn("Try the push-up.", "EXERCISE", "RETRIEVE_THEN_ANSWER"),
    )

    reply = CoachService(service_session, provider).reply(user.id, "I only have dumbbells.")

    (guess,) = results_given(provider, 1)
    (search,) = results_given(provider, 2)
    assert guess["error"]["code"] == "ID_NOT_GROUNDED"
    assert [item["name"] for item in search["output"]["exercises"]] == [
        "Barbell Bench Press",
        "Push-Up",
    ]
    assert reply == "Try the push-up."


def test_a_turn_that_cannot_decide_ends_with_cannot_answer(service_session, user):
    provider = fake_provider(
        *[respond_turn("Your goal is fat loss.", "PROFILE", "ANSWER")] * 6
    )

    reply = CoachService(service_session, provider).reply(user.id, "What is my goal?")

    assert reply == CANNOT_ANSWER_REPLY
    assert provider.generate_turn.call_count == 6
