"""The discovery tools against the real services: the current plan and the
last workout are found without an id, for the trusted user only, and the
existing lookups by id work as before.

The current plan is the user's PLANNED plan with the latest scheduled date;
the last workout is their most recently started COMPLETED session.

They require the local PostgreSQL container to be running. Test data is only
flushed in db_session, which is rolled back after each test.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock

import pytest

from app.ai import ToolCall
from app.services import (
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.tools import FormiqTools
from tests.integration.workout_plans import add_plan, add_user
from tests.integration.workout_sessions import add_session

DAY = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)


@pytest.fixture
def tools(db_session):
    return FormiqTools(
        users=UserService(db_session),
        profiles=UserProfileService(db_session),
        plans=WorkoutPlanService(db_session),
        sessions=WorkoutSessionService(db_session),
        catalog=ExerciseCatalogService(db_session),
        # ending the read would roll back the flushed test data
        end_read=Mock(),
    )


@pytest.fixture
def user(db_session):
    return add_user(db_session, "discovery@example.com")


@pytest.fixture
def other_user(db_session):
    return add_user(db_session, "discovery-other@example.com")


@pytest.fixture
def exercise_id(catalog_exercise_ids):
    return next(iter(catalog_exercise_ids.values()))


def run(tools, name, *, user_id, **arguments):
    (result,) = tools.run([ToolCall(name=name, arguments=arguments)], user_id=user_id)
    return result


def session_on(db_session, user, day, status, exercise_id):
    return add_session(
        db_session,
        user,
        status=status,
        exercises=[(exercise_id, [8, 8])],
        started_at=DAY + timedelta(days=day),
        completed_at=DAY + timedelta(days=day, hours=1)
        if status == "COMPLETED"
        else None,
    )


# --- the current workout plan ---


def test_the_current_plan_is_the_latest_scheduled_planned_plan(
    tools, db_session, user, other_user, exercise_id
):
    add_plan(
        db_session,
        user,
        "Old",
        exercise_ids=[exercise_id],
        status="PLANNED",
        scheduled_date=date(2026, 10, 1),
    )
    current = add_plan(
        db_session,
        user,
        "Current",
        exercise_ids=[exercise_id],
        status="PLANNED",
        scheduled_date=date(2026, 10, 10),
    )
    # never current: not ready, not to be done, or another user's
    add_plan(
        db_session,
        user,
        "Draft",
        exercise_ids=[exercise_id],
        status="DRAFT",
        scheduled_date=date(2026, 10, 20),
    )
    add_plan(
        db_session,
        user,
        "Gone",
        exercise_ids=[exercise_id],
        status="CANCELLED",
        scheduled_date=date(2026, 10, 30),
    )
    add_plan(
        db_session,
        other_user,
        "Theirs",
        exercise_ids=[exercise_id],
        status="PLANNED",
        scheduled_date=date(2026, 11, 1),
    )

    result = run(tools, "get_current_workout_plan", user_id=user.id)

    assert result["output"]["plan_id"] == current.id
    # the same output as the lookup by id, which still works
    assert result == run(tools, "get_workout_plan", user_id=user.id, plan_id=current.id)


def test_without_a_planned_plan_there_is_no_current_plan(
    tools, db_session, user, other_user, exercise_id
):
    add_plan(db_session, user, "Draft", exercise_ids=[exercise_id], status="DRAFT")
    add_plan(
        db_session,
        other_user,
        "Theirs",
        exercise_ids=[exercise_id],
        status="PLANNED",
        scheduled_date=date(2026, 10, 10),
    )

    result = run(tools, "get_current_workout_plan", user_id=user.id)

    # a controlled answer, never another user's plan
    assert result["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert "no current workout plan" in result["error"]["message"]


# --- the last workout ---


def test_the_last_workout_is_the_most_recently_started_completed_session(
    tools, db_session, user, other_user, exercise_id
):
    session_on(db_session, user, 0, "COMPLETED", exercise_id)
    last = session_on(db_session, user, 4, "COMPLETED", exercise_id)
    # never the last workout: cancelled, still running, or another user's
    session_on(db_session, user, 5, "CANCELLED", exercise_id)
    session_on(db_session, user, 6, "IN_PROGRESS", exercise_id)
    session_on(db_session, other_user, 7, "COMPLETED", exercise_id)

    result = run(tools, "get_latest_workout_session", user_id=user.id)

    assert result["output"]["session_id"] == last.id
    # the same output as the lookup by id, which still works
    assert result == run(
        tools, "get_workout_session", user_id=user.id, session_id=last.id
    )


def test_without_a_completed_session_there_is_no_last_workout(
    tools, db_session, user, other_user, exercise_id
):
    session_on(db_session, user, 0, "IN_PROGRESS", exercise_id)
    session_on(db_session, other_user, 1, "COMPLETED", exercise_id)

    result = run(tools, "get_latest_workout_session", user_id=user.id)

    assert result["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert "no completed workout session" in result["error"]["message"]


# --- what the model cannot choose ---


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("get_current_workout_plan", {"user_id": "other"}),
        ("get_current_workout_plan", {"plan_id": 1}),
        ("get_latest_workout_session", {"user_id": "other"}),
        ("get_latest_workout_session", {"session_id": 1}),
    ],
    ids=["plan_user_id", "plan_id", "session_user_id", "session_id"],
)
def test_the_discovery_tools_take_no_user_or_resource_id(
    tools, db_session, user, other_user, exercise_id, name, arguments
):
    add_plan(
        db_session,
        other_user,
        "Theirs",
        exercise_ids=[exercise_id],
        status="PLANNED",
        scheduled_date=date(2026, 10, 10),
    )
    session_on(db_session, other_user, 1, "COMPLETED", exercise_id)
    if arguments.get("user_id") == "other":
        arguments = {"user_id": other_user.id}

    (result,) = tools.run([ToolCall(name=name, arguments=arguments)], user_id=user.id)

    # refused before anything is read
    assert result["error"]["code"] == "INVALID_INPUT"
