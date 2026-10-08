"""Integration tests for the coach's tools, reading through the real services.

They require the local PostgreSQL container to be running. The tools only read,
so the test data is only flushed in db_session, which is rolled back after each
test. The test database also holds the seeded exercise catalog.
"""

from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest

from app.ai import ToolCall
from app.models import UserProfile, WorkoutSession, WorkoutSessionExercise, WorkoutSet
from app.services import (
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.tools import FormiqTools
from app.tools.limits import MAX_SEARCH_RESULTS
from tests.integration.catalog import add_equipment, add_exercise, add_muscle_group
from tests.integration.workout_plans import add_plan, add_user
from tests.integration.workout_sessions import add_session

STARTED = datetime(2026, 10, 6, 7, 0, tzinfo=UTC)
COMPLETED = datetime(2026, 10, 6, 7, 45, tzinfo=UTC)


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
    return add_user(db_session, "tools@example.com")


@pytest.fixture
def other_user(db_session):
    return add_user(db_session, "tools-other@example.com")


def run(tools, name, *, user_id, **arguments):
    (result,) = tools.run([ToolCall(name=name, arguments=arguments)], user_id=user_id)
    return result


def add_profile(session, user, profile_fields, **fields):
    profile = UserProfile(user_id=user.id, **{**profile_fields, **fields})
    session.add(profile)
    session.flush()
    return profile


def not_found(message):
    return {"error": {"code": "RESOURCE_NOT_FOUND", "message": message}}


# get_user_profile


def test_profile_holds_the_fitness_fields(tools, db_session, user, profile_fields):
    add_profile(
        db_session,
        user,
        profile_fields,
        last_name="Example",
        target_weight_kg=75.0,
        goal_period_weeks=12,
        dietary_preference="non_vegetarian",
    )

    assert run(tools, "get_user_profile", user_id=user.id) == {
        "output": {
            "user_id": user.id,
            "profile": {
                "first_name": "Test",
                "last_name": "Example",
                "age": 30,
                "height_cm": 175.0,
                "weight_kg": 70.0,
                "gender": "other",
                "fitness_experience": "beginner",
                "goal": "general_fitness",
                "target_weight_kg": 75.0,
                "goal_period_weeks": 12,
                "training_frequency_per_week": 3,
                "training_location": "gym",
                "activity_level": "moderate",
                "sleep_hours": 7.5,
                "dietary_preference": "non_vegetarian",
            },
        }
    }


def test_profile_never_holds_contact_details_ids_or_timestamps(
    tools, db_session, user, profile_fields
):
    # the user's email and phone exist, in the users table
    user.phone = "+15550100"
    db_session.flush()
    add_profile(db_session, user, profile_fields, last_name="Example")

    result = run(tools, "get_user_profile", user_id=user.id)

    assert set(result["output"]["profile"]).isdisjoint(
        {"id", "user_id", "email", "phone", "created_at", "updated_at"}
    )
    # the name, and nothing to contact the user by
    assert (result["output"]["profile"]["first_name"], result["output"]["profile"]["last_name"]) == (
        "Test",
        "Example",
    )
    assert "tools@example.com" not in str(result) and "5550100" not in str(result)


def test_profile_of_an_unknown_user(tools):
    assert run(tools, "get_user_profile", user_id=2_147_483_647) == {
        "error": {"code": "USER_NOT_FOUND", "message": "the user does not exist"}
    }


def test_profile_not_created_yet(tools, user):
    assert run(tools, "get_user_profile", user_id=user.id) == {
        "error": {
            "code": "PROFILE_NOT_FOUND",
            "message": "the user has not created a fitness profile",
        }
    }


@pytest.mark.parametrize("user_id", [0, -1, 2_147_483_648])
def test_profile_of_an_invalid_user_id(tools, user_id):
    assert run(tools, "get_user_profile", user_id=user_id)["error"]["code"] == "INVALID_INPUT"


def test_profile_of_another_user_is_out_of_reach(
    tools, db_session, user, other_user, profile_fields
):
    add_profile(db_session, other_user, profile_fields)

    # the user has no profile, whoever else has one ...
    assert run(tools, "get_user_profile", user_id=user.id)["error"]["code"] == (
        "PROFILE_NOT_FOUND"
    )
    # ... and the model cannot name another user
    (named,) = tools.run(
        [ToolCall(name="get_user_profile", arguments={"user_id": other_user.id})],
        user_id=user.id,
    )
    assert named["error"]["code"] == "INVALID_INPUT"


# get_workout_plan


def test_plan_with_its_prescribed_exercises(tools, db_session, user, catalog_exercise_ids):
    bench, push_up = catalog_exercise_ids["Barbell Bench Press"], catalog_exercise_ids["Push-Up"]
    plan = add_plan(
        db_session,
        user,
        "Upper Body A",
        exercise_ids=[bench, push_up],
        status="PLANNED",
        scheduled_date=date(2026, 10, 7),
        description="Not returned",
    )
    plan.exercises[0].weight_kg = 20.0
    plan.exercises[0].rest_seconds = 90
    plan.exercises[1].notes = "Slow tempo"
    db_session.flush()

    assert run(tools, "get_workout_plan", user_id=user.id, plan_id=plan.id) == {
        "output": {
            "plan_id": plan.id,
            "name": "Upper Body A",
            "status": "PLANNED",
            "scheduled_date": "2026-10-07",
            "exercises": [
                {
                    "exercise_id": bench,
                    "exercise_name": "Barbell Bench Press",
                    "exercise_order": 1,
                    "sets": 3,
                    "reps": 8,
                    "weight_kg": 20.0,
                    "rest_seconds": 90,
                    "notes": None,
                },
                {
                    "exercise_id": push_up,
                    "exercise_name": "Push-Up",
                    "exercise_order": 2,
                    "sets": 3,
                    "reps": 8,
                    "weight_kg": None,
                    "rest_seconds": None,
                    "notes": "Slow tempo",
                },
            ],
            "truncated": False,
        }
    }


def test_empty_draft_plan(tools, db_session, user):
    plan = add_plan(db_session, user, "Ideas")

    output = run(tools, "get_workout_plan", user_id=user.id, plan_id=plan.id)["output"]

    assert (output["status"], output["scheduled_date"], output["exercises"]) == ("DRAFT", None, [])


def test_cancelled_plan_stays_readable(tools, db_session, user, catalog_exercise_ids):
    plan = add_plan(
        db_session,
        user,
        exercise_ids=[catalog_exercise_ids["Push-Up"]],
        status="CANCELLED",
        scheduled_date=date(2026, 10, 1),
    )

    output = run(tools, "get_workout_plan", user_id=user.id, plan_id=plan.id)["output"]

    assert output["status"] == "CANCELLED"


def test_missing_plan(tools, user):
    assert run(tools, "get_workout_plan", user_id=user.id, plan_id=2_147_483_647) == not_found(
        "the user has no workout plan 2147483647"
    )


def test_plan_of_another_user_looks_missing(tools, db_session, user, other_user):
    plan = add_plan(db_session, other_user, "Not yours")

    result = run(tools, "get_workout_plan", user_id=user.id, plan_id=plan.id)

    # the same answer as for a plan that does not exist: nothing about its owner
    assert result == not_found(f"the user has no workout plan {plan.id}")
    assert "Not yours" not in str(result)


# get_workout_session


def add_completed_session(session, user, plan, exercise_ids):
    workout_session = WorkoutSession(
        user_id=user.id,
        workout_plan_id=plan.id if plan else None,
        status="COMPLETED",
        started_at=STARTED,
        completed_at=COMPLETED,
        notes="Felt strong",
        exercises=[
            WorkoutSessionExercise(
                exercise_id=exercise_ids[0],
                exercise_order=1,
                notes="Not returned",
                sets=[
                    WorkoutSet(set_number=1, reps=10, weight_kg=20.0, rpe=7.0),
                    WorkoutSet(set_number=2, reps=10, weight_kg=20.0, rpe=8.5),
                    WorkoutSet(set_number=3, reps=6, weight_kg=20.0, rpe=10.0, completed=False),
                ],
            ),
            WorkoutSessionExercise(
                exercise_id=exercise_ids[1],
                exercise_order=2,
                sets=[WorkoutSet(set_number=1, reps=15)],
            ),
        ],
    )
    session.add(workout_session)
    session.flush()
    return workout_session


def performed(set_number, reps, weight_kg, rpe, *, completed=True):
    return {
        "set_number": set_number,
        "reps": reps,
        "weight_kg": weight_kg,
        "rpe": rpe,
        "completed": completed,
    }


def test_completed_session_with_its_performed_sets(
    tools, db_session, user, catalog_exercise_ids
):
    bench, push_up = catalog_exercise_ids["Barbell Bench Press"], catalog_exercise_ids["Push-Up"]
    plan = add_plan(
        db_session, user, exercise_ids=[bench], status="PLANNED", scheduled_date=date(2026, 10, 6)
    )
    workout_session = add_completed_session(db_session, user, plan, [bench, push_up])

    result = run(tools, "get_workout_session", user_id=user.id, session_id=workout_session.id)

    assert result == {
        "output": {
            "session_id": workout_session.id,
            "workout_plan_id": plan.id,
            "status": "COMPLETED",
            "started_at": "2026-10-06T07:00:00Z",
            "completed_at": "2026-10-06T07:45:00Z",
            "notes": "Felt strong",
            "exercises": [
                {
                    "exercise_id": bench,
                    "exercise_name": "Barbell Bench Press",
                    "exercise_order": 1,
                    "sets": [
                        performed(1, 10, 20.0, 7.0),
                        performed(2, 10, 20.0, 8.5),
                        performed(3, 6, 20.0, 10.0, completed=False),
                    ],
                },
                {
                    "exercise_id": push_up,
                    "exercise_name": "Push-Up",
                    "exercise_order": 2,
                    "sets": [performed(1, 15, None, None)],
                },
            ],
            "truncated": False,
        }
    }


def test_session_in_progress_without_a_plan(tools, db_session, user, catalog_exercise_ids):
    workout_session = add_session(
        db_session, user, exercises=[(catalog_exercise_ids["Walking Lunge"], [12, 12])]
    )

    output = run(tools, "get_workout_session", user_id=user.id, session_id=workout_session.id)[
        "output"
    ]

    assert (output["status"], output["workout_plan_id"], output["completed_at"]) == (
        "IN_PROGRESS",
        None,
        None,
    )
    assert [s["reps"] for s in output["exercises"][0]["sets"]] == [12, 12]


def test_missing_session(tools, user):
    assert run(
        tools, "get_workout_session", user_id=user.id, session_id=2_147_483_647
    ) == not_found("the user has no workout session 2147483647")


def test_session_of_another_user_looks_missing(
    tools, db_session, user, other_user, catalog_exercise_ids
):
    workout_session = add_completed_session(
        db_session, other_user, None, [catalog_exercise_ids["Push-Up"]] * 2
    )

    result = run(tools, "get_workout_session", user_id=user.id, session_id=workout_session.id)

    assert result == not_found(f"the user has no workout session {workout_session.id}")
    assert "Felt strong" not in str(result)


# get_exercise


def test_exercise_from_the_catalog(tools, user, catalog_exercise_ids):
    bench = catalog_exercise_ids["Barbell Bench Press"]

    output = run(tools, "get_exercise", user_id=user.id, exercise_id=bench)["output"]

    assert output == {
        "exercise_id": bench,
        "name": "Barbell Bench Press",
        "description": output["description"],
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "HORIZONTAL_PUSH",
        "muscles": [
            {"name": "Chest", "role": "PRIMARY"},
            {"name": "Front Deltoid", "role": "SECONDARY"},
            {"name": "Triceps", "role": "SECONDARY"},
        ],
        "equipment": ["Barbell", "Bench"],
        "is_active": True,
    }
    assert output["description"].startswith("Lie on a bench")


def test_exercise_without_equipment(tools, user, catalog_exercise_ids):
    push_up = catalog_exercise_ids["Push-Up"]

    output = run(tools, "get_exercise", user_id=user.id, exercise_id=push_up)["output"]

    assert output["equipment"] == []


def test_inactive_exercise_stays_readable(tools, db_session, user):
    retired = add_exercise(db_session, "Test Retired Press", is_active=False)

    output = run(tools, "get_exercise", user_id=user.id, exercise_id=retired.id)["output"]

    assert (output["name"], output["is_active"]) == ("Test Retired Press", False)


def test_missing_exercise(tools, user):
    assert run(tools, "get_exercise", user_id=user.id, exercise_id=2_147_483_647) == not_found(
        "the catalog has no exercise 2147483647"
    )


# search_exercises


def names(result):
    return [item["name"] for item in result["output"]["exercises"]]


def test_search_by_equipment(tools, db_session, user):
    kettlebell = add_equipment(db_session, "Test Kettlebell")
    chest = add_muscle_group(db_session, "Test Chest")
    add_exercise(db_session, "Test Swing", equipment=[kettlebell], primary=[chest])
    add_exercise(db_session, "Test Goblet Squat", equipment=[kettlebell])
    add_exercise(db_session, "Test Air Squat")

    result = run(tools, "search_exercises", user_id=user.id, equipment_id=kettlebell.id)

    assert result["output"] == {
        "exercises": [
            {
                "exercise_id": result["output"]["exercises"][0]["exercise_id"],
                "name": "Test Goblet Squat",
                "difficulty": "BEGINNER",
                "movement_pattern": "SQUAT",
                "muscles": [],
                "equipment": ["Test Kettlebell"],
            },
            {
                "exercise_id": result["output"]["exercises"][1]["exercise_id"],
                "name": "Test Swing",
                "difficulty": "BEGINNER",
                "movement_pattern": "SQUAT",
                "muscles": ["Test Chest"],
                "equipment": ["Test Kettlebell"],
            },
        ],
        "count": 2,
    }


def test_search_by_movement_pattern(tools, user):
    result = run(tools, "search_exercises", user_id=user.id, movement_pattern="HORIZONTAL_PUSH")

    assert names(result) == ["Barbell Bench Press", "Push-Up"]


def test_search_by_difficulty(tools, user):
    result = run(tools, "search_exercises", user_id=user.id, difficulty="INTERMEDIATE")

    assert names(result) == [
        "Barbell Back Squat",
        "Barbell Bench Press",
        "Cable Woodchop",
        "Pull-Up",
        "Romanian Deadlift",
    ]
    assert result["output"]["count"] == 5


def test_search_with_combined_filters(tools, user):
    result = run(
        tools,
        "search_exercises",
        user_id=user.id,
        movement_pattern="HORIZONTAL_PUSH",
        difficulty="BEGINNER",
    )

    assert names(result) == ["Push-Up"]


def test_search_combines_equipment_with_the_other_filters(tools, db_session, user):
    band = add_equipment(db_session, "Test Band")
    add_exercise(db_session, "Test Band Squat", equipment=[band], movement_pattern="SQUAT")
    add_exercise(db_session, "Test Band Hinge", equipment=[band], movement_pattern="HINGE")

    result = run(
        tools, "search_exercises", user_id=user.id, equipment_id=band.id, movement_pattern="HINGE"
    )

    assert names(result) == ["Test Band Hinge"]


def test_search_returns_at_most_ten_exercises(tools, db_session, user):
    rack = add_equipment(db_session, "Test Rack")
    for number in range(MAX_SEARCH_RESULTS + 2):
        add_exercise(db_session, f"Test Rack Exercise {number:02}", equipment=[rack])

    result = run(tools, "search_exercises", user_id=user.id, equipment_id=rack.id)

    assert result["output"]["count"] == MAX_SEARCH_RESULTS == 10
    assert names(result) == [f"Test Rack Exercise {number:02}" for number in range(10)]


def test_search_without_matches(tools, db_session, user):
    unused = add_equipment(db_session, "Test Unused")

    result = run(tools, "search_exercises", user_id=user.id, equipment_id=unused.id)

    assert result == {"output": {"exercises": [], "count": 0}}


def test_search_leaves_out_inactive_exercises(tools, db_session, user):
    sled = add_equipment(db_session, "Test Sled")
    add_exercise(db_session, "Test Sled Push", equipment=[sled])
    add_exercise(db_session, "Test Sled Pull", equipment=[sled], is_active=False)

    assert names(run(tools, "search_exercises", user_id=user.id, equipment_id=sled.id)) == [
        "Test Sled Push"
    ]


def test_search_without_filters_is_rejected(tools, user):
    result = run(tools, "search_exercises", user_id=user.id)

    assert result["error"]["code"] == "INVALID_INPUT"
    assert "at least one of equipment_id, movement_pattern, difficulty" in (
        result["error"]["message"]
    )


# read-only


def test_tools_change_nothing(tools, db_session, user, profile_fields, catalog_exercise_ids):
    add_profile(db_session, user, profile_fields)
    push_up = catalog_exercise_ids["Push-Up"]
    plan = add_plan(db_session, user, exercise_ids=[push_up])
    workout_session = add_completed_session(db_session, user, None, [push_up, push_up])
    calls = [
        ToolCall(name="get_user_profile", arguments={}),
        ToolCall(name="get_workout_plan", arguments={"plan_id": plan.id}),
        ToolCall(name="get_workout_session", arguments={"session_id": workout_session.id}),
        ToolCall(name="get_exercise", arguments={"exercise_id": push_up}),
        ToolCall(name="search_exercises", arguments={"difficulty": "BEGINNER"}),
    ]

    results = tools.run(calls, user_id=user.id)

    assert all("output" in result for result in results)
    assert [*db_session.new, *db_session.dirty, *db_session.deleted] == []
    tools.end_read.assert_called_once()
