"""The discovery tools against the real services: the current plan and the
last workout are found without an id, for the trusted user only, and the
existing lookups by id work as before.

The current plan is the user's PLANNED plan scheduled for today, or else the
next one, or else the latest before today; the last workout is their most
recently started COMPLETED session. Both say where they are relative to today.

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
# the request's date, fixed for these tests
TODAY = date(2026, 10, 8)
# what the discovery tools add to the output of the lookup by id
RELATIVE_TO_TODAY = ("today", "days_from_today", "days_ago")


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
        today=TODAY,
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


def by_id_output(result):
    """The discovery result as the lookup by id returns it."""
    return {
        "output": {
            key: value
            for key, value in result["output"].items()
            if key not in RELATIVE_TO_TODAY
        }
    }


def planned(db_session, user, name, day, exercise_id, status="PLANNED"):
    return add_plan(
        db_session,
        user,
        name,
        exercise_ids=[exercise_id],
        status=status,
        scheduled_date=TODAY + timedelta(days=day),
    )


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


def test_the_current_plan_is_the_planned_plan_for_today(
    tools, db_session, user, other_user, exercise_id
):
    planned(db_session, user, "Yesterday", -1, exercise_id)
    today = planned(db_session, user, "Today", 0, exercise_id)
    planned(db_session, user, "Tomorrow", 1, exercise_id)
    # never current: not ready, not to be done, or another user's
    planned(db_session, user, "Draft", 0, exercise_id, status="DRAFT")
    planned(db_session, user, "Gone", 0, exercise_id, status="CANCELLED")
    planned(db_session, other_user, "Theirs", 0, exercise_id)

    result = run(tools, "get_current_workout_plan", user_id=user.id)

    assert result["output"]["plan_id"] == today.id
    assert result["output"]["today"] == TODAY.isoformat()
    assert result["output"]["days_from_today"] == 0
    # otherwise the same output as the lookup by id, which still works
    assert by_id_output(result) == run(
        tools, "get_workout_plan", user_id=user.id, plan_id=today.id
    )


def test_without_a_plan_for_today_the_current_plan_is_the_next_one(
    tools, db_session, user, other_user, exercise_id
):
    planned(db_session, user, "Past", -3, exercise_id)
    later = planned(db_session, user, "Later", 2, exercise_id)
    planned(db_session, user, "Much later", 12, exercise_id)
    planned(db_session, user, "Draft", 1, exercise_id, status="DRAFT")
    planned(db_session, other_user, "Theirs", 1, exercise_id)

    result = run(tools, "get_current_workout_plan", user_id=user.id)

    assert result["output"]["plan_id"] == later.id
    assert result["output"]["days_from_today"] == 2


def test_without_a_plan_today_or_later_the_current_plan_is_the_latest_before(
    tools, db_session, user, other_user, exercise_id
):
    planned(db_session, user, "Older", -7, exercise_id)
    latest = planned(db_session, user, "Latest", -3, exercise_id)
    planned(db_session, user, "Gone", 1, exercise_id, status="CANCELLED")
    planned(db_session, other_user, "Theirs", 0, exercise_id)

    result = run(tools, "get_current_workout_plan", user_id=user.id)

    # in the past: the coach can see it was missed if no workout followed it
    assert result["output"]["plan_id"] == latest.id
    assert result["output"]["days_from_today"] == -3


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
    # completed on October 5, three days before TODAY
    assert result["output"]["today"] == TODAY.isoformat()
    assert result["output"]["days_ago"] == 3
    # otherwise the same output as the lookup by id, which still works
    assert by_id_output(result) == run(
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
