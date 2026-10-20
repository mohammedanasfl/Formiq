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
from app.tools.limits import MAX_INSTRUCTION_STEPS, MAX_SEARCH_RESULTS
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
                    "section": "MAIN_WORKOUT",
                    "sets": 3,
                    "reps": 8,
                    "duration_seconds": None,
                    "weight_kg": 20.0,
                    "rest_seconds": 90,
                    "notes": None,
                },
                {
                    "exercise_id": push_up,
                    "exercise_name": "Push-Up",
                    "exercise_order": 2,
                    "section": "MAIN_WORKOUT",
                    "sets": 3,
                    "reps": 8,
                    "duration_seconds": None,
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
                    # counted from the records: the third set was not completed
                    "completed_sets": 2,
                },
                {
                    "exercise_id": push_up,
                    "exercise_name": "Push-Up",
                    "exercise_order": 2,
                    "sets": [performed(1, 15, None, None)],
                    "completed_sets": 1,
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
        # Formiq's own exercise: a description, and no upstream steps or category
        "instructions": [],
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "HORIZONTAL_PUSH",
        "category": None,
        "uses": ["MAIN_WORKOUT"],
        "muscles": [
            {"name": "Chest", "role": "PRIMARY"},
            {"name": "Front Deltoid", "role": "SECONDARY"},
            {"name": "Triceps", "role": "SECONDARY"},
        ],
        "equipment": ["Barbell", "Bench"],
        "is_active": True,
        "truncated": False,
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

    result = run(tools, "search_exercises", user_id=user.id, equipment=kettlebell.name)

    assert result["output"] == {
        "exercises": [
            {
                "exercise_id": result["output"]["exercises"][0]["exercise_id"],
                "name": "Test Goblet Squat",
                "difficulty": "BEGINNER",
                "movement_pattern": "SQUAT",
                "uses": [],
                "muscles": [],
                "equipment": ["Test Kettlebell"],
            },
            {
                "exercise_id": result["output"]["exercises"][1]["exercise_id"],
                "name": "Test Swing",
                "difficulty": "BEGINNER",
                "movement_pattern": "SQUAT",
                "uses": [],
                "muscles": ["Test Chest"],
                "equipment": ["Test Kettlebell"],
            },
        ],
        "count": 2,
        "total_matches": 2,
    }


def test_search_by_movement_pattern(tools, user):
    result = run(tools, "search_exercises", user_id=user.id, movement_pattern="HORIZONTAL_PUSH")

    assert names(result) == ["Barbell Bench Press", "Dumbbell Bench Press", "Push-Up"]


def test_search_by_difficulty(tools, user):
    result = run(tools, "search_exercises", user_id=user.id, difficulty="INTERMEDIATE")

    # one exercise per primary muscle in turn (Glutes, Chest, Obliques,
    # Shoulders, Lats), then the other two for the glutes, each turn by name
    assert names(result) == [
        "Barbell Back Squat",
        "Barbell Bench Press",
        "Cable Woodchop",
        "Pike Push-Up",
        "Pull-Up",
        "Kettlebell Swing",
        "Romanian Deadlift",
    ]
    assert result["output"]["count"] == 7


@pytest.mark.parametrize(
    ("pattern", "total"), [("MOBILITY", 21), ("STRETCH", 16), ("CARDIO", 7)]
)
def test_a_kind_of_warm_up_or_cool_down_activity_says_how_many_there_are(
    tools, user, pattern, total
):
    # the drills and the stretches are more than one search returns (they were 8 and 10,
    # which fit): the first come back, with how many match, and the coach narrows by muscle
    result = run(tools, "search_exercises", user_id=user.id, movement_pattern=pattern)

    assert result["output"]["total_matches"] == total
    assert result["output"]["count"] == min(total, MAX_SEARCH_RESULTS)
    assert {item["difficulty"] for item in result["output"]["exercises"]} == {"BEGINNER"}


ACTIVITY_MUSCLES = (
    "Chest",
    "Upper Back",
    "Lats",
    "Shoulders",
    "Biceps",
    "Triceps",
    "Core",
    "Glutes",
    "Quadriceps",
    "Hamstrings",
    "Calves",
)


@pytest.mark.parametrize("pattern", ["MOBILITY", "STRETCH"])
@pytest.mark.parametrize("muscle", ACTIVITY_MUSCLES)
def test_a_kind_of_activity_narrowed_by_a_muscle_fits_one_search(tools, user, pattern, muscle):
    # so the coach sees every drill or stretch for a muscle the main exercises train
    result = run(
        tools, "search_exercises", user_id=user.id, movement_pattern=pattern, muscle=muscle
    )

    assert result["output"]["total_matches"] == result["output"]["count"] <= MAX_SEARCH_RESULTS


@pytest.mark.parametrize(
    ("pattern", "muscle", "name"),
    [
        ("MOBILITY", "Triceps", "Wall Push-Up"),
        ("MOBILITY", "Triceps", "Light Band Triceps Pushdown"),
        ("MOBILITY", "Biceps", "Light Band Biceps Curl"),
        ("MOBILITY", "Chest", "Wall Push-Up"),
        ("MOBILITY", "Core", "Lying Pelvic Tilt"),
        ("MOBILITY", "Core", "Standing Cross-Crawl"),
        ("STRETCH", "Biceps", "Wall Biceps Stretch"),
        ("STRETCH", "Forearms", "Wrist Extensor Stretch"),
        ("STRETCH", "Adductors", "Butterfly Stretch"),
        ("STRETCH", "Obliques", "Seated Spinal Twist"),
    ],
)
def test_a_search_by_kind_and_muscle_finds_the_activities_added_for_that_muscle(
    tools, user, pattern, muscle, name
):
    result = run(
        tools, "search_exercises", user_id=user.id, movement_pattern=pattern, muscle=muscle
    )

    assert name in [item["name"] for item in result["output"]["exercises"]]


def test_search_with_combined_filters(tools, user):
    result = run(
        tools,
        "search_exercises",
        user_id=user.id,
        movement_pattern="HORIZONTAL_PUSH",
        difficulty="BEGINNER",
    )

    assert names(result) == ["Dumbbell Bench Press", "Push-Up"]


def test_search_combines_equipment_with_the_other_filters(tools, db_session, user):
    band = add_equipment(db_session, "Test Band")
    add_exercise(db_session, "Test Band Squat", equipment=[band], movement_pattern="SQUAT")
    add_exercise(db_session, "Test Band Hinge", equipment=[band], movement_pattern="HINGE")

    result = run(
        tools, "search_exercises", user_id=user.id, equipment=band.name, movement_pattern="HINGE"
    )

    assert names(result) == ["Test Band Hinge"]


def test_search_returns_at_most_fifteen_exercises(tools, db_session, user):
    rack = add_equipment(db_session, "Test Rack")
    for number in range(MAX_SEARCH_RESULTS + 2):
        add_exercise(db_session, f"Test Rack Exercise {number:02}", equipment=[rack])

    result = run(tools, "search_exercises", user_id=user.id, equipment=rack.name)

    assert result["output"]["count"] == MAX_SEARCH_RESULTS == 15
    # and says how many match in all, and that this is not all of them
    assert result["output"]["total_matches"] == MAX_SEARCH_RESULTS + 2
    assert result["output"]["note"].startswith("Showing 15 of 17 matches")
    assert names(result) == [f"Test Rack Exercise {number:02}" for number in range(15)]


def test_search_without_matches(tools, db_session, user):
    unused = add_equipment(db_session, "Test Unused")

    result = run(tools, "search_exercises", user_id=user.id, equipment=unused.name)

    assert result == {"output": {"exercises": [], "count": 0, "total_matches": 0}}


def test_search_leaves_out_inactive_exercises(tools, db_session, user):
    sled = add_equipment(db_session, "Test Sled")
    add_exercise(db_session, "Test Sled Push", equipment=[sled])
    add_exercise(db_session, "Test Sled Pull", equipment=[sled], is_active=False)

    assert names(run(tools, "search_exercises", user_id=user.id, equipment=sled.name)) == [
        "Test Sled Push"
    ]


def test_search_without_filters_is_rejected(tools, user):
    result = run(tools, "search_exercises", user_id=user.id)

    assert result["error"]["code"] == "INVALID_INPUT"
    assert (
        "at least one of use, muscle, available_equipment, equipment, movement_pattern, "
        "difficulty, name is required" in result["error"]["message"]
    )


def test_search_by_use_finds_the_exercises_formiq_uses_for_that_section(tools, db_session, user):
    # a muscle group of their own keeps the seeded catalog out of the results
    muscle = add_muscle_group(db_session, "Test Use Muscle")
    add_exercise(db_session, "Test Warm Drill", primary=[muscle], uses=["WARM_UP"])
    add_exercise(
        db_session, "Test Drill Both Ends", primary=[muscle], uses=["WARM_UP", "COOL_DOWN"]
    )
    add_exercise(db_session, "Test Main Only", primary=[muscle], uses=["MAIN_WORKOUT"])
    add_exercise(db_session, "Test Not Classified", primary=[muscle])

    def found(use):
        result = run(tools, "search_exercises", user_id=user.id, use=use, muscle=muscle.name)
        return {item["name"]: item["uses"] for item in result["output"]["exercises"]}

    assert found("WARM_UP") == {
        "Test Drill Both Ends": ["WARM_UP", "COOL_DOWN"],
        "Test Warm Drill": ["WARM_UP"],
    }
    assert list(found("COOL_DOWN")) == ["Test Drill Both Ends"]
    assert list(found("MAIN_WORKOUT")) == ["Test Main Only"]


def test_search_by_muscle_name_and_the_equipment_the_user_has(tools, db_session, user):
    glutes = add_muscle_group(db_session, "Test Glutes")
    band = add_equipment(db_session, "Test Loop Band")
    bar = add_equipment(db_session, "Test Bar")
    add_exercise(db_session, "Test Bridge", primary=[glutes], uses=["MAIN_WORKOUT"])
    add_exercise(db_session, "Test Band Walk", primary=[glutes], equipment=[band])
    add_exercise(db_session, "Test Bar Thrust", primary=[glutes], equipment=[bar, band])

    def found(**filters):
        result = run(tools, "search_exercises", user_id=user.id, muscle="test glutes", **filters)
        return names(result)

    # what a section uses first (a search says which exercises can go into a workout), then by name
    assert found() == ["Test Bridge", "Test Band Walk", "Test Bar Thrust"]
    # an empty list: only what needs no equipment at all
    assert found(available_equipment=[]) == ["Test Bridge"]
    # only what needs nothing beyond what the user has, matched without case
    assert found(available_equipment=["test loop band"]) == ["Test Bridge", "Test Band Walk"]
    assert found(available_equipment=["Test Loop Band", "Test Bar"]) == [
        "Test Bridge",
        "Test Band Walk",
        "Test Bar Thrust",
    ]
    assert found(available_equipment=[], use="MAIN_WORKOUT") == ["Test Bridge"]


@pytest.mark.parametrize(
    ("filters", "message"),
    [
        ({"muscle": "Pecs"}, "the catalog has no muscle group 'Pecs'; it has "),
        (
            {"available_equipment": ["Dumbbell", "Hover Board"]},
            "no equipment 'Hover Board'; it has ",
        ),
        ({"use": "MAIN"}, "use: Input should be 'WARM_UP', 'MAIN_WORKOUT' or 'COOL_DOWN'"),
    ],
)
def test_search_names_the_catalog_values_when_one_is_unknown(tools, user, filters, message):
    result = run(tools, "search_exercises", user_id=user.id, **filters)

    assert result["error"]["code"] == "INVALID_INPUT"
    assert message in result["error"]["message"]


@pytest.mark.parametrize(
    "said",
    [["body weight"], ["Bodyweight"], ["BODY-WEIGHT"], ["body only"], ["no equipment"], ["None"]],
)
def test_a_name_for_no_equipment_finds_what_needs_none(tools, user, said):
    # what a model writes for training without equipment, as in the Langfuse
    # baseline trace, finds what an empty list finds, instead of failing
    def found(available):
        return run(
            tools,
            "search_exercises",
            user_id=user.id,
            use="MAIN_WORKOUT",
            difficulty="BEGINNER",
            available_equipment=available,
        )

    result = found(said)

    assert result == found([])
    assert result["output"]["count"] > 0
    assert all(item["equipment"] == [] for item in result["output"]["exercises"])


def test_a_name_for_no_equipment_never_widens_what_the_user_has(tools, db_session, user):
    glutes = add_muscle_group(db_session, "Test Glutes")
    band = add_equipment(db_session, "Test Loop Band")
    bar = add_equipment(db_session, "Test Bar")
    add_exercise(db_session, "Test Bridge", primary=[glutes])
    add_exercise(db_session, "Test Band Walk", primary=[glutes], equipment=[band])
    add_exercise(db_session, "Test Bar Thrust", primary=[glutes], equipment=[bar])

    def found(*available):
        result = run(
            tools,
            "search_exercises",
            user_id=user.id,
            muscle=glutes.name,
            available_equipment=list(available),
        )
        return names(result)

    # a band and their own body weight: what needs the band or nothing, never the bar
    assert found("Test Loop Band", "body weight") == ["Test Band Walk", "Test Bridge"]
    assert found("body weight") == found() == ["Test Bridge"]
    # a piece written with other case, hyphens or spacing is still that piece
    assert found("test-loop  band") == ["Test Band Walk", "Test Bridge"]


def test_unknown_equipment_is_refused_with_the_names_there_are(tools, user):
    said = ["bodyweight", "Hover Board"]

    result = run(tools, "search_exercises", user_id=user.id, available_equipment=said)

    assert result["error"]["code"] == "INVALID_INPUT"
    message = result["error"]["message"]
    # the name for no equipment is understood; only the unknown one is named
    assert message.startswith("the catalog has no equipment 'Hover Board'; it has Barbell, Bench, ")
    # and how to correct it: an empty list for none, or no filter when the user named none
    assert message.endswith(
        "; for no equipment at all, give an empty list, and when the user did not say what "
        "equipment they have, leave available_equipment out"
    )


def test_a_warm_up_search_returns_easy_cardio_then_a_drill_per_muscle(tools, db_session, user):
    mat = add_equipment(db_session, "Test Mat")
    quads = add_muscle_group(db_session, "Test Quads")
    back = add_muscle_group(db_session, "Test Back")

    def warm_up(name, muscle, pattern):
        add_exercise(
            db_session, name, primary=[muscle], equipment=[mat], movement_pattern=pattern,
            uses=["WARM_UP"],
        )  # fmt: skip

    # added out of order: the order comes from the ranking, not the insertion
    warm_up("Test D Unclassified", quads, None)
    warm_up("Test B Back Drill", back, "MOBILITY")
    warm_up("Test Z March", quads, "CARDIO")
    warm_up("Test C Quad Drill", quads, "MOBILITY")
    warm_up("Test A Back Drill", back, "MOBILITY")

    result = run(tools, "search_exercises", user_id=user.id, use="WARM_UP", equipment=mat.name)

    assert names(result) == [
        # easy cardio suits any main workout, so it always fits a proposal
        "Test Z March",
        # Formiq's classified drills, one per primary muscle in turn
        "Test A Back Drill",
        "Test C Quad Drill",
        "Test B Back Drill",
        # then what Formiq has not classified
        "Test D Unclassified",
    ]
    # the same matches always come in the same order
    assert run(tools, "search_exercises", user_id=user.id, use="WARM_UP", equipment=mat.name) == (
        result
    )
    # with no main exercises found yet, none is said to suit them
    assert all("suits_main" not in item for item in result["output"]["exercises"])


def test_a_muscle_search_returns_where_it_is_primary_first(tools, db_session, user):
    quads = add_muscle_group(db_session, "Test Quads")
    back = add_muscle_group(db_session, "Test Back")
    add_exercise(db_session, "Test A Row", primary=[back], secondary=[quads])
    add_exercise(db_session, "Test B Squat", primary=[quads])

    result = run(tools, "search_exercises", user_id=user.id, muscle="test quads")

    assert names(result) == ["Test B Squat", "Test A Row"]


def test_the_few_results_returned_cover_several_muscles(tools, db_session, user):
    rack = add_equipment(db_session, "Test Rack")
    legs = add_muscle_group(db_session, "Test Legs")
    arms = add_muscle_group(db_session, "Test Arms")
    for number in range(10):
        add_exercise(db_session, f"Test L {number}", primary=[legs], equipment=[rack])
    for number in range(6):
        add_exercise(db_session, f"Test M {number}", primary=[arms], equipment=[rack])

    result = run(tools, "search_exercises", user_id=user.id, equipment=rack.name)

    # bounded, and saying how many match in all
    assert (result["output"]["count"], result["output"]["total_matches"]) == (15, 16)
    # every arms exercise, where the first fifteen names would hold only three of them
    assert names(result) == [
        "Test L 0", "Test M 0", "Test L 1", "Test M 1", "Test L 2", "Test M 2",
        "Test L 3", "Test M 3", "Test L 4", "Test M 4", "Test L 5", "Test M 5",
        "Test L 6", "Test L 7", "Test L 8",
    ]  # fmt: skip


def test_search_results_hold_only_what_choosing_an_exercise_needs(tools, db_session, user):
    mat = add_equipment(db_session, "Test Mat")
    record = {
        "id": "Test_Imported_Drill",
        "category": "stretching",
        "instructions": ["Lie down on the mat."] * 20,
        "images": ["Test_Imported_Drill/0.jpg"],
    }
    add_exercise(
        db_session,
        "Test Imported Drill",
        equipment=[mat],
        movement_pattern=None,
        uses=["WARM_UP", "COOL_DOWN"],
        source="FREE_EXERCISE_DB",
        source_id="Test_Imported_Drill",
        source_record=record,
        image_paths=["Test_Imported_Drill/0.jpg"],
    )

    result = run(tools, "search_exercises", user_id=user.id, equipment=mat.name)

    (item,) = result["output"]["exercises"]
    # the selection metadata: no upstream record, instructions, category or images
    assert set(item) == {
        "exercise_id", "name", "difficulty", "movement_pattern", "uses", "muscles", "equipment",
    }  # fmt: skip
    assert "Lie down" not in str(result) and ".jpg" not in str(result)


def test_an_imported_exercise_shows_its_upstream_steps_and_category(tools, db_session, user):
    steps = [f"Step {number}." for number in range(1, MAX_INSTRUCTION_STEPS + 3)]
    imported = add_exercise(
        db_session,
        "Test Imported Stretch",
        movement_pattern=None,
        uses=["COOL_DOWN"],
        source="FREE_EXERCISE_DB",
        source_id="Test_Imported_Stretch",
        source_record={
            "id": "Test_Imported_Stretch",
            "category": "stretching",
            "instructions": steps,
        },
    )

    output = run(tools, "get_exercise", user_id=user.id, exercise_id=imported.id)["output"]

    assert (output["category"], output["uses"], output["movement_pattern"]) == (
        "stretching",
        ["COOL_DOWN"],
        None,
    )
    # the steps in order, bounded
    assert output["instructions"] == steps[:MAX_INSTRUCTION_STEPS]
    assert output["truncated"] is True


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
