"""Integration tests for RecoverySummaryService: the recovery summary of a completed workout
session, built from recorded sessions, the profile and what the user reports.

They require the local PostgreSQL container to be running (test database). The service
only reads, so the data of each test is committed first, as a request would find it; the
service_session fixture empties the user, workout plan and workout session tables before
and after each test.
"""

import re
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, event, func, select
from sqlalchemy.orm import Session

from app.guidance import foods, nutrition, recovery
from app.guidance.sources import SOURCES
from app.models import (
    Exercise,
    ExerciseMuscle,
    MuscleGroup,
    User,
    UserProfile,
    WorkoutPlan,
    WorkoutSession,
    WorkoutSessionExercise,
    WorkoutSet,
)
from app.repositories import ExerciseRepository, WorkoutPlanExerciseRepository
from app.schemas import Estimates, Guidance, RecoverySummaryRequest
from app.schemas.coach import CoachMessageRequest
from app.services import RecoverySummaryService
from app.services.exceptions import (
    WorkoutSessionConflictError,
    WorkoutSessionNotCompletedError,
    WorkoutSessionNotFoundError,
)
from app.services.recovery_summary_service import MAX_NOTE_LENGTH
from tests.integration.database import assert_disposable
from tests.integration.workout_plans import add_plan, add_user, columns

STARTED = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)
DONE = STARTED + timedelta(minutes=55)


def clock_at(moment):
    return lambda: moment


# an hour after the workout, whatever the real time is
CLOCK = clock_at(DONE + timedelta(hours=1))

SQUAT = "Barbell Back Squat"
BENCH = "Barbell Bench Press"
ALL_ESTIMATES = {
    "post_workout_protein_g",
    "daily_protein_g",
    "daily_carbohydrate_g",
    "rapid_refuel_carbohydrate_g_per_hour",
    "active_energy_kcal",
}
ANIMAL_FOODS = {"MEAT", "POULTRY", "FISH", "SHELLFISH", "EGG"}
# a note that the coach's safety backstop flags as pain, and one as extreme dieting
PAIN_NOTE = "sharp knee pain on the last set ZQXTOKEN"
DIET_NOTE = "extreme dieting: I eat 500 calories a day ZQXTOKEN"


@dataclass
class S:
    """A set as recorded: reps, and optionally weight, rpe and notes."""

    reps: int = 5
    weight: float | None = None
    rpe: float | None = None
    completed: bool = True
    notes: str | None = None


@dataclass
class Ex:
    """A session exercise, by the name of its catalog exercise. No sets: a timed one."""

    name: str | int
    sets: Sequence[S] = field(default_factory=list)
    notes: str | None = None
    plan_exercise_id: int | None = None


def add_workout(
    session,
    user,
    items,
    ids,
    *,
    status="COMPLETED",
    started_at=STARTED,
    completed_at=DONE,
    **fields,
):
    """A session of the user with the exercises and sets given, flushed only. An exercise
    is named by its catalog name, or given as its id."""
    workout_session = WorkoutSession(
        user_id=user.id,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        exercises=[
            WorkoutSessionExercise(
                exercise_id=item.name if isinstance(item.name, int) else ids[item.name],
                exercise_order=order,
                notes=item.notes,
                plan_exercise_id=item.plan_exercise_id,
                sets=[
                    WorkoutSet(
                        set_number=number,
                        reps=one.reps,
                        weight_kg=one.weight,
                        rpe=one.rpe,
                        completed=one.completed,
                        notes=one.notes,
                    )
                    for number, one in enumerate(item.sets, start=1)
                ],
            )
            for order, item in enumerate(items, start=1)
        ],
        **fields,
    )
    session.add(workout_session)
    session.flush()
    return workout_session


def lifting(session, user, ids, **fields):
    """55 minutes of squats and bench press, with weights and effort."""
    return add_workout(
        session,
        user,
        [
            Ex(SQUAT, [S(5, 100.0, 7.0), S(5, 100.0, 8.0), S(5, 100.0, 8.5)]),
            Ex(BENCH, [S(8, 60.0, 7.0), S(8, 60.0, 8.0), S(8, 60.0, 9.0)]),
        ],
        ids,
        **fields,
    )


def add_profile(session, user, profile_fields, **changes):
    profile = UserProfile(user_id=user.id, **{**profile_fields, **changes})
    session.add(profile)
    session.flush()
    return profile


def request_of(**fields):
    return RecoverySummaryRequest(**fields)


def reported(area, kind, severity):
    return {"area": area, "kind": kind, "severity": severity}


def plans_of(response):
    return {plan.muscle: plan for plan in response.guidance.recovery.muscles}


def given(response):
    """The names of the estimates the response gives."""
    return {name for name, value in response.estimates if value is not None}


def notice_codes(response):
    return [notice.code for notice in response.safety.notices]


def trained_names(response):
    return [entry.muscle for entry in response.calculated.muscles_trained]


def recovery_reason(plan):
    """The lower-confidence reason of a muscle plan, if it has one."""
    return next((reason for reason in plan.reasons if "logged without sets" in reason), None)


def bounds(estimate):
    return estimate.low, estimate.high


def cited_ids(dumped):
    """Every id in any source_id or source_id field of a dumped response, found without
    the service's own helper. A field that names a source in another way fails here."""
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for key, item in node.items():
                if key == "source_id":
                    found.add(item)
                elif key == "source_ids":
                    found.update(item)
                else:
                    assert "source" not in key or key == "sources", key
                    walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(dumped)
    return found


def note_of_length(length, start="sharp knee pain ZQXTOKEN "):
    """A note that starts with a pain and is exactly this long, not ending in a space."""
    return start + "x" * (length - len(start))


@contextmanager
def recorded_statements(engine):
    """The SQL statements the engine runs inside the block."""
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


@pytest.fixture
def user(service_session):
    return add_user(service_session, "recovery-summary@example.com")


@pytest.fixture
def other_user(service_session):
    return add_user(service_session, "recovery-summary-other@example.com")


@pytest.fixture
def ids(catalog_exercise_ids):
    return catalog_exercise_ids


@pytest.fixture
def summarise(service_session):
    """Commits what the test added, then builds the summary like a request would."""

    def run(user, workout_session, *, clock=CLOCK, user_id=None, session_id=None, **request):
        owner_id, workout_id = user.id, workout_session.id
        service_session.commit()
        service = RecoverySummaryService(service_session, clock=clock)
        return service.build_summary(
            owner_id if user_id is None else user_id,
            workout_id if session_id is None else session_id,
            request_of(**request),
        )

    return run


@pytest.fixture
def unclassified_exercise(test_engine, service_session):
    """A committed catalog exercise that Formiq has not classified (no uses), which works
    the chest. It is deleted afterwards with the session exercises that use it, because
    the catalog tests expect the catalog to hold only the seed."""
    with Session(test_engine) as session:
        assert_disposable(session.connection())
        chest = session.scalars(select(MuscleGroup).where(MuscleGroup.name == "Chest")).one()
        exercise = Exercise(
            name="Test Unclassified Exercise",
            difficulty="BEGINNER",
            movement_pattern="HORIZONTAL_PUSH",
            uses=[],
            muscles=[ExerciseMuscle(muscle_group_id=chest.id, role="PRIMARY")],
        )
        session.add(exercise)
        session.commit()
        exercise_id = exercise.id
    try:
        yield exercise_id
    finally:
        with Session(test_engine) as session:
            assert_disposable(session.connection())
            session.execute(
                delete(WorkoutSessionExercise).where(
                    WorkoutSessionExercise.exercise_id == exercise_id
                )
            )
            session.execute(delete(Exercise).where(Exercise.id == exercise_id))
            session.commit()


# the realistic case


def test_a_realistic_summary(service_session, user, ids, profile_fields, summarise):
    add_profile(
        service_session,
        user,
        profile_fields,
        weight_kg=72.0,
        goal="build_muscle",
        dietary_preference="vegetarian",
        age=30,
    )
    workout_session = lifting(service_session, user, ids)

    response = summarise(
        user,
        workout_session,
        discomfort=[reported("KNEES", "SORENESS", 5)],
    )

    assert response.session_id == workout_session.id
    assert response.completed_at == DONE
    assert response.hours_since_completed == 1.0
    assert response.calculated.duration_minutes == 55.0
    assert response.calculated.duration_plausible is True

    estimates = response.estimates
    assert bounds(estimates.post_workout_protein_g) == (18, 29)
    assert bounds(estimates.daily_protein_g) == (115, 144)
    assert bounds(estimates.daily_carbohydrate_g) == (216, 360)
    assert bounds(estimates.rapid_refuel_carbohydrate_g_per_hour) == (72, 86)
    assert bounds(estimates.active_energy_kcal) == (160, 330)
    assert estimates.daily_protein_g.basis == "1.6-2.0 g/kg/day x 72.0 kg recorded body weight"
    assert estimates.active_energy_kcal.unit == "kcal"
    assert given(response) == ALL_ESTIMATES
    assert response.missing_data == []

    plans = plans_of(response)
    quadriceps, chest = plans["Quadriceps"], plans["Chest"]
    assert (quadriceps.status, quadriceps.rest_hours) == ("REST", 72)
    assert quadriceps.rest_until == DONE + timedelta(hours=72)
    assert (chest.status, chest.rest_hours) == ("REST", 48)
    assert chest.rest_until == DONE + timedelta(hours=48)
    assert plans["Glutes"].rest_hours == 48
    # a secondary muscle with reported soreness gets a window; one without only a note
    assert plans["Hamstrings"].rest_hours == 72 and plans["Hamstrings"].role == "SECONDARY"
    assert plans["Triceps"].status == "ALSO_WORKED"
    assert plans["Triceps"].rest_until is None
    # a muscle the user reported but did not train
    assert plans["Calves"].role is None and plans["Calves"].rest_hours == 72

    guidance = response.guidance
    items = guidance.food_suggestions.items
    assert guidance.food_suggestions.preference_status == "APPLIED"
    assert guidance.food_suggestions.dietary_pattern == "VEGETARIAN"
    assert items
    assert not any(ANIMAL_FOODS & set(item.contains) for item in items)
    assert guidance.fluid_loss_measured is False
    assert [note.text for note in guidance.hydration] == [
        item.text for item in nutrition.hydration_items()
    ]
    assert guidance.post_workout_carbohydrate and guidance.recovery.general
    # 7.5 hours of sleep meets the recommendation
    assert guidance.sleep is None

    assert response.safety.status == "CAUTION"
    used = response.calculated.profile_values_used
    assert (used.weight_kg, used.age, used.bmi) == (72.0, 30, 23.5)
    assert (used.goal, used.goal_category) == ("build_muscle", "BUILD_MUSCLE")
    assert (used.dietary_preference, used.sleep_hours) == ("vegetarian", 7.5)


# calculated facts


def test_the_calculated_facts_are_exact(service_session, user, ids, summarise):
    workout_session = add_workout(
        service_session,
        user,
        [
            Ex(
                SQUAT,
                [
                    S(5, 100.0, 7.0),
                    S(5, 100.0, 8.0),
                    S(3, 100.0, 9.0, completed=False),
                ],
            ),
            # sets without a weight or an rpe
            Ex(BENCH, [S(10), S(10)]),
            # its only set was not completed
            Ex("Dumbbell Biceps Curl", [S(12, 15.0, completed=False)]),
        ],
        ids,
    )

    response = summarise(user, workout_session)
    calculated = response.calculated

    squat, bench, curl = calculated.exercises
    assert [item.name for item in calculated.exercises] == [SQUAT, BENCH, "Dumbbell Biceps Curl"]
    assert (squat.status, squat.sets_logged, squat.completed_sets) == ("TRAINED", 3, 2)
    assert (squat.total_reps, squat.volume_kg, squat.average_rpe) == (10, 1000.0, 7.5)
    assert (bench.status, bench.sets_logged, bench.completed_sets) == ("TRAINED", 2, 2)
    assert (bench.total_reps, bench.volume_kg, bench.average_rpe) == (20, None, None)
    assert (curl.status, curl.sets_logged, curl.completed_sets) == ("SKIPPED", 1, 0)
    assert (curl.total_reps, curl.volume_kg, curl.average_rpe) == (0, None, None)
    assert [item.section for item in calculated.exercises] == ["MAIN_WORKOUT"] * 3
    assert [item.session_exercise_id for item in calculated.exercises] == sorted(
        item.session_exercise_id for item in calculated.exercises
    )
    # the totals add up the exercises; a skipped one adds nothing
    assert calculated.completed_sets == 4
    assert calculated.total_reps == 30
    assert calculated.volume_kg == 1000.0
    # a skipped exercise counts for no muscle: Biceps is only the curl's main muscle
    assert "Biceps" not in trained_names(response)
    assert "Biceps" not in plans_of(response)


def test_a_volume_comes_only_from_completed_sets_with_a_weight(
    service_session, user, ids, summarise
):
    workout_session = add_workout(
        service_session,
        user,
        [
            Ex(SQUAT, [S(3, 22.5), S(4, 20.0), S(10), S(10, 200.0, completed=False)]),
            Ex(BENCH, [S(5, 50.0)]),
        ],
        ids,
    )

    calculated = summarise(user, workout_session).calculated

    squat, bench = calculated.exercises
    assert squat.volume_kg == 147.5
    assert squat.completed_sets == 3 and squat.total_reps == 17
    assert calculated.volume_kg == 397.5


def test_the_average_rpe_and_volume_round_half_up_to_two_decimals(
    service_session, user, ids, summarise
):
    workout_session = add_workout(
        service_session,
        user,
        [
            Ex(SQUAT, [S(1, 0.5, 7.0), S(1, 0.5, 7.01)]),
            Ex(BENCH, [S(1, 33.335, 7.0), S(1, 33.335, 7.0), S(1, 33.335, 8.0)]),
        ],
        ids,
    )

    squat, bench = summarise(user, workout_session).calculated.exercises

    # 7.005 rounds up, where float rounding gives 7.0
    assert squat.average_rpe == 7.01
    assert squat.volume_kg == 1.0
    assert bench.average_rpe == 7.33
    # 100.005 rounds up
    assert bench.volume_kg == 100.01


def test_a_muscle_is_primary_if_it_is_primary_in_any_counted_exercise(
    service_session, user, ids, summarise
):
    workout_session = add_workout(
        service_session,
        user,
        [
            Ex("Pull-Up", [S(8), S(8)]),
            Ex("Seated Cable Row", [S(10), S(10), S(10)]),
            Ex("Dumbbell Bench Press", [S(10)]),
            Ex(BENCH, [S(8), S(8)]),
        ],
        ids,
    )

    response = summarise(user, workout_session)

    muscles = {entry.muscle: entry for entry in response.calculated.muscles_trained}

    # Upper Back is a supporting muscle in the pull-up and the main one in the row
    assert muscles["Upper Back"].role == "PRIMARY"
    assert muscles["Upper Back"].completed_sets == 5
    assert muscles["Upper Back"].exercises == ["Pull-Up", "Seated Cable Row"]
    assert muscles["Chest"].completed_sets == 3
    assert muscles["Chest"].exercises == ["Dumbbell Bench Press", BENCH]
    assert muscles["Lats"].role == "PRIMARY" and muscles["Triceps"].role == "SECONDARY"


def test_the_muscles_trained_list_the_primary_ones_first_in_the_order_first_seen(
    service_session, user, ids, summarise
):
    workout_session = lifting(service_session, user, ids)

    muscles = summarise(user, workout_session).calculated.muscles_trained

    roles = [entry.role for entry in muscles]
    assert roles == ["PRIMARY"] * 3 + ["SECONDARY"] * 4
    assert {entry.muscle for entry in muscles[:2]} == {"Quadriceps", "Glutes"}
    assert muscles[2].muscle == "Chest"
    assert {entry.muscle for entry in muscles[3:]} == {
        "Lower Back",
        "Hamstrings",
        "Front Deltoid",
        "Triceps",
    }
    assert muscles[2].completed_sets == 3 and muscles[2].exercises == [BENCH]
    assert muscles[0].completed_sets == 3 and muscles[0].exercises == [SQUAT]


# exercises logged without sets


def test_a_timed_exercise_logged_without_sets_still_counts(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(service_session, user, profile_fields)
    workout_session = add_workout(service_session, user, [Ex("Farmer's Carry")], ids)

    response = summarise(user, workout_session)

    [carry] = response.calculated.exercises
    assert carry.status == "LOGGED_WITHOUT_SETS"
    assert (carry.sets_logged, carry.completed_sets, carry.total_reps) == (0, 0, 0)
    assert carry.volume_kg is None and carry.average_rpe is None
    forearms = next(
        entry for entry in response.calculated.muscles_trained if entry.muscle == "Forearms"
    )
    assert forearms.role == "PRIMARY" and forearms.completed_sets == 0
    assert forearms.exercises == ["Farmer's Carry"]
    plans = plans_of(response)
    assert plans["Forearms"].status == "REST" and plans["Forearms"].rest_hours == 48
    assert recovery_reason(plans["Forearms"]) is not None
    assert recovery_reason(plans["Core"]) is not None
    # a counted exercise is enough for a post-workout protein range
    assert response.estimates.post_workout_protein_g is not None


def test_the_lower_confidence_reason_is_only_for_muscles_worked_by_timed_exercises_alone(
    service_session, user, ids, summarise
):
    workout_session = add_workout(
        service_session,
        user,
        [Ex("Farmer's Carry"), Ex("Pull-Up", [S(8), S(8)])],
        ids,
    )

    plans = plans_of(summarise(user, workout_session))

    # the pull-up trains these too, with sets
    for muscle in ("Forearms", "Upper Back", "Lats", "Biceps"):
        assert recovery_reason(plans[muscle]) is None, muscle
    # only the carry works the core
    assert recovery_reason(plans["Core"]) == (
        "Based on exercises logged without sets (for example timed ones), so how much work "
        "was done is unknown."
    )


# sections


def test_warm_up_and_cool_down_exercises_make_no_rest_window(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(service_session, user, profile_fields)
    plan = add_plan(
        service_session, user, exercise_ids=[ids["Push-Up"], ids[SQUAT], ids["Pull-Up"]]
    )
    # the plan puts the push-up in the warm-up and the pull-up in the cool-down
    warm_up, main, cool_down = plan.exercises
    warm_up.section = "WARM_UP"
    cool_down.section = "COOL_DOWN"
    service_session.flush()
    workout_session = add_workout(
        service_session,
        user,
        [
            Ex("Push-Up", [S(10)], plan_exercise_id=warm_up.id),
            Ex(SQUAT, [S(5, 100.0), S(5, 100.0)], plan_exercise_id=main.id),
            Ex("Pull-Up", [S(5)], plan_exercise_id=cool_down.id),
            # not linked to a plan: the catalog says where it belongs
            Ex("Arm Circles", [S(20)]),
            Ex("Standing Calf Stretch", [S(1)]),
            Ex("Bodyweight Squat", [S(15)]),
        ],
        ids,
        workout_plan_id=plan.id,
    )

    response = summarise(user, workout_session)

    sections = {item.name: item.section for item in response.calculated.exercises}
    assert sections == {
        "Push-Up": "WARM_UP",
        SQUAT: "MAIN_WORKOUT",
        "Pull-Up": "COOL_DOWN",
        "Arm Circles": "WARM_UP",
        "Standing Calf Stretch": "COOL_DOWN",
        # suits the warm-up and the main workout, so it is main work
        "Bodyweight Squat": "MAIN_WORKOUT",
    }
    # warm-up and cool-down exercises are in the calculated facts, and in the totals
    assert response.calculated.completed_sets == 2 + 1 + 1 + 1 + 1 + 1
    assert response.calculated.total_reps == 10 + 10 + 5 + 20 + 1 + 15
    # but they train no muscle and give no window: Chest is the push-up's, Lats the pull-up's
    counted = set(trained_names(response))
    assert counted == {"Quadriceps", "Glutes", "Lower Back", "Hamstrings", "Core"}
    assert set(plans_of(response)) == counted
    for muscle in ("Chest", "Lats", "Shoulders", "Calves"):
        assert muscle not in plans_of(response)
    assert response.estimates.post_workout_protein_g is not None


def test_a_session_with_only_warm_up_work_has_no_muscles_and_no_post_workout_protein(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(service_session, user, profile_fields)
    workout_session = add_workout(
        service_session,
        user,
        [Ex("Arm Circles", [S(20)]), Ex("Standing Quad Stretch", [S(1)])],
        ids,
    )

    response = summarise(user, workout_session)

    assert response.calculated.muscles_trained == []
    assert response.guidance.recovery.muscles == []
    assert response.estimates.post_workout_protein_g is None
    assert any(item.field == "exercises" for item in response.missing_data)
    # the daily targets do not depend on what was counted
    assert response.estimates.daily_protein_g is not None


def test_an_exercise_that_formiq_has_not_classified_is_main_work(
    service_session, user, ids, unclassified_exercise, summarise
):
    workout_session = add_workout(service_session, user, [Ex(unclassified_exercise, [S(10)])], ids)

    response = summarise(user, workout_session)

    [item] = response.calculated.exercises
    assert item.section == "MAIN_WORKOUT"
    assert trained_names(response) == ["Chest"]


# no profile


def test_without_a_profile_there_is_no_estimate_but_the_rest_of_the_summary(
    service_session, user, ids, summarise, monkeypatch
):
    def not_called(*args, **kwargs):
        raise AssertionError("an estimate rule ran without a profile")

    for name in (
        "post_workout_protein",
        "daily_protein",
        "daily_carbohydrate",
        "rapid_refuel",
        "active_energy",
    ):
        monkeypatch.setattr(nutrition, name, not_called)
    workout_session = lifting(service_session, user, ids)

    response = summarise(user, workout_session)

    assert response.estimates == Estimates()
    assert [(item.field, item.effect) for item in response.missing_data] == [
        (
            "profile",
            "no profile is recorded, so no per-kg or energy estimate is given and food "
            "examples are not filtered by diet",
        )
    ]
    assert response.calculated.profile_values_used is None
    assert response.guidance.sleep is None
    assert response.guidance.hydration
    assert response.guidance.post_workout_carbohydrate
    assert plans_of(response)["Quadriceps"].rest_hours == 48
    foods_shown = response.guidance.food_suggestions
    assert foods_shown.preference_status == "NOT_SET"
    assert foods_shown.dietary_pattern is None
    assert foods_shown.items
    assert response.safety.status == "OK"
    # the calculated facts do not need a profile
    assert response.calculated.duration_minutes == 55.0
    assert response.calculated.volume_kg == 1500.0 + 1440.0


def test_the_sleep_note_is_for_a_profile_that_reports_under_seven_hours(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(service_session, user, profile_fields, sleep_hours=6.0)
    workout_session = lifting(service_session, user, ids)

    sleep = summarise(user, workout_session).guidance.sleep

    assert sleep.code == "SLEEP_BELOW_RECOMMENDED"
    assert sleep.source_ids == ["AASM_SLEEP_2015"]


# time


@pytest.mark.parametrize("minutes", [600, 2])
def test_an_implausible_duration_withholds_the_estimates_that_need_it(
    service_session, user, ids, profile_fields, summarise, minutes
):
    add_profile(service_session, user, profile_fields)
    workout_session = lifting(
        service_session, user, ids, completed_at=STARTED + timedelta(minutes=minutes)
    )

    response = summarise(
        user, workout_session, clock=clock_at(STARTED + timedelta(minutes=minutes + 60))
    )

    assert response.calculated.duration_minutes == minutes
    assert response.calculated.duration_plausible is False
    assert given(response) == {"post_workout_protein_g", "daily_protein_g"}
    fields = [item.field for item in response.missing_data]
    assert fields == ["duration_minutes"] * 3
    assert len({item.effect for item in response.missing_data}) == 3
    # the rest windows do not depend on the duration
    assert plans_of(response)["Chest"].rest_hours == 48


def test_a_session_with_no_completion_time_uses_its_last_update(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(service_session, user, profile_fields)
    workout_session = lifting(service_session, user, ids, completed_at=None)
    service_session.commit()
    updated_at = workout_session.updated_at

    response = summarise(user, workout_session, clock=clock_at(updated_at + timedelta(hours=1)))

    assert response.completed_at == updated_at
    assert response.hours_since_completed == 1.0
    assert response.calculated.duration_minutes is None
    assert response.calculated.duration_plausible is False
    assert plans_of(response)["Chest"].rest_until == updated_at + timedelta(hours=48)
    assert [item.field for item in response.missing_data][0] == "completed_at"
    assert response.missing_data[0].effect == (
        "no completion time is recorded, so the time of the last update is used for rest "
        "windows and the session length is not given"
    )
    # the estimates that need the length are withheld, the others stay
    assert given(response) == {"post_workout_protein_g", "daily_protein_g"}


def test_a_completion_time_before_the_start_gives_no_duration(
    service_session, user, ids, summarise
):
    workout_session = lifting(
        service_session, user, ids, completed_at=STARTED - timedelta(hours=1)
    )

    calculated = summarise(user, workout_session, clock=CLOCK).calculated

    assert calculated.duration_minutes is None
    assert calculated.duration_plausible is False


@pytest.mark.parametrize(
    ("hours", "given_after"),
    [(24.0, True), (24.5, False)],
)
def test_more_than_24_hours_after_the_workout_the_post_workout_estimates_are_withheld(
    service_session, user, ids, profile_fields, summarise, hours, given_after
):
    add_profile(service_session, user, profile_fields)
    workout_session = lifting(service_session, user, ids)

    response = summarise(user, workout_session, clock=clock_at(DONE + timedelta(hours=hours)))

    assert response.hours_since_completed == hours
    estimates = response.estimates
    assert (estimates.post_workout_protein_g is not None) is given_after
    assert (estimates.rapid_refuel_carbohydrate_g_per_hour is not None) is given_after
    assert estimates.daily_protein_g is not None
    assert estimates.daily_carbohydrate_g is not None
    assert estimates.active_energy_kcal is not None
    assert plans_of(response)["Quadriceps"].rest_hours == 48
    withheld = {item.field for item in response.missing_data}
    assert ("hours_since_completed" in withheld) is (not given_after)


# the profile's gates


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"age": 17}, set()),
        ({"age": 19}, ALL_ESTIMATES),
        ({"age": 59}, ALL_ESTIMATES),
        ({"age": 60}, ALL_ESTIMATES - {"active_energy_kcal"}),
        ({"weight_kg": 25.0}, set()),
        ({"weight_kg": 29.9}, set()),
        ({"weight_kg": 30.0}, ALL_ESTIMATES),
        ({"weight_kg": 300.0}, ALL_ESTIMATES),
        ({"weight_kg": 350.0}, set()),
    ],
)
def test_the_profile_gates_decide_which_estimates_are_given(
    service_session, user, ids, profile_fields, summarise, changes, expected
):
    add_profile(service_session, user, profile_fields, **changes)
    workout_session = lifting(service_session, user, ids)

    response = summarise(user, workout_session)

    assert given(response) == expected
    # each estimate that is withheld says why, in an entry of its own
    assert len(response.missing_data) == len(ALL_ESTIMATES - expected)
    # the calculated facts and the recovery windows do not depend on the profile's gates
    assert response.calculated.volume_kg == 2940.0
    assert plans_of(response)["Chest"].rest_hours == 48
    assert response.guidance.hydration


# notes


def with_note(service_session, user, ids, where, note, **fields):
    """The lifting session with the note on the session, the squat or the squat's first set."""
    workout_session = lifting(service_session, user, ids, **fields)
    if where == "session":
        workout_session.notes = note
    elif where == "exercise":
        workout_session.exercises[0].notes = note
    else:
        workout_session.exercises[0].sets[0].notes = note
    service_session.flush()
    return workout_session


def assert_no_text_of(response, *texts):
    dumped = response.model_dump_json()
    for text in texts:
        assert text not in dumped
    assert "ZQXTOKEN" not in dumped


@pytest.mark.parametrize("where", ["exercise", "set"])
def test_a_flagged_note_on_an_exercise_sends_its_primary_muscles_to_a_professional(
    service_session, user, ids, summarise, where
):
    workout_session = with_note(service_session, user, ids, where, PAIN_NOTE)

    response = summarise(user, workout_session)

    plans = plans_of(response)
    for muscle in ("Quadriceps", "Glutes"):
        assert plans[muscle].status == "SEE_PROFESSIONAL"
        assert plans[muscle].rest_hours is None and plans[muscle].rest_until is None
        assert plans[muscle].reasons[-1] == (
            "A note on this workout mentions pain, an injury or a health concern: "
            + recovery.PAIN_ADVICE
        )
    # the squat's supporting muscles, and the bench press's, are as they were
    assert plans["Chest"].status == "REST" and plans["Chest"].rest_hours == 48
    assert plans["Hamstrings"].status == "ALSO_WORKED"
    assert plans["Lower Back"].status == "ALSO_WORKED"
    assert response.safety.status == "CAUTION"
    assert notice_codes(response) == ["NOTES_FLAGGED"]
    [notice] = response.safety.notices
    assert notice.source_ids == []
    assert notice.message == (
        "A note on this workout mentions pain, an injury or a health concern. Formiq reads "
        "notes only by keywords and cannot judge them: if something hurts, stop exercises "
        "that load it and see a doctor or physiotherapist."
    )
    assert_no_text_of(response, PAIN_NOTE, "knee pain")


def test_a_flagged_note_on_the_session_sends_every_counted_muscle_to_a_professional(
    service_session, user, ids, summarise
):
    workout_session = with_note(service_session, user, ids, "session", PAIN_NOTE)

    response = summarise(user, workout_session)

    plans = plans_of(response)
    assert set(plans) == set(trained_names(response)) and len(plans) == 7
    for plan in plans.values():
        assert plan.status == "SEE_PROFESSIONAL"
        assert plan.rest_hours is None and plan.rest_until is None
    assert notice_codes(response) == ["NOTES_FLAGGED"]
    assert response.safety.status == "CAUTION"
    assert_no_text_of(response, PAIN_NOTE)


def test_several_flagged_notes_give_one_notice_and_the_reason_once(
    service_session, user, ids, summarise
):
    workout_session = with_note(service_session, user, ids, "exercise", PAIN_NOTE)
    workout_session.notes = PAIN_NOTE
    workout_session.exercises[1].sets[1].notes = "my chest pain returned ZQXTOKEN"
    service_session.flush()

    response = summarise(user, workout_session)

    assert notice_codes(response) == ["NOTES_FLAGGED"]
    for plan in plans_of(response).values():
        assert len([reason for reason in plan.reasons if "A note on this workout" in reason]) == 1
    assert_no_text_of(response, PAIN_NOTE, "chest pain returned")


@pytest.mark.parametrize("where", ["session", "exercise", "set"])
def test_a_note_about_extreme_dieting_gives_a_nutrition_notice_and_changes_no_muscle(
    service_session, user, ids, summarise, where
):
    baseline = summarise(user, lifting(service_session, user, ids))
    workout_session = with_note(service_session, user, ids, where, DIET_NOTE)

    response = summarise(user, workout_session)

    assert notice_codes(response) == ["NOTES_DIET_FLAGGED"]
    [notice] = response.safety.notices
    assert notice.message == (
        "A note on this workout mentions extreme dieting or weight loss. Formiq's targets "
        "here fuel training and are not a diet: please talk to a doctor or dietitian."
    )
    assert response.safety.status == "CAUTION"
    assert response.guidance.recovery == baseline.guidance.recovery
    assert_no_text_of(response, DIET_NOTE, "500 calories")


@pytest.mark.parametrize("where", ["session", "exercise", "set"])
def test_a_note_about_extreme_weight_loss_gives_the_nutrition_notice_too(
    service_session, user, ids, summarise, where
):
    note = "I want to lose 15 kg in two weeks ZQXTOKEN"
    workout_session = with_note(service_session, user, ids, where, note)

    response = summarise(user, workout_session)

    assert notice_codes(response) == ["NOTES_DIET_FLAGGED"]
    assert response.safety.status == "CAUTION"
    assert_no_text_of(response, note)


def test_a_benign_note_changes_nothing(service_session, user, ids, summarise):
    baseline = summarise(user, lifting(service_session, user, ids))
    workout_session = with_note(service_session, user, ids, "session", "felt great ZQXTOKEN")
    workout_session.exercises[0].notes = "good depth today"
    workout_session.exercises[1].sets[0].notes = "easy"
    service_session.flush()

    response = summarise(user, workout_session)

    assert response.safety.status == "OK"
    assert response.safety.notices == []
    assert response.guidance.recovery == baseline.guidance.recovery
    assert_no_text_of(response, "felt great", "good depth")


def test_empty_and_blank_notes_are_skipped(service_session, user, ids, summarise):
    workout_session = with_note(service_session, user, ids, "session", "   ")
    workout_session.exercises[0].notes = ""
    workout_session.exercises[0].sets[0].notes = "\n"
    service_session.flush()

    response = summarise(user, workout_session)

    assert response.safety.status == "OK" and response.safety.notices == []


@pytest.mark.parametrize("where", ["session", "exercise", "set"])
def test_a_note_that_is_too_long_is_not_scanned_and_says_so(
    service_session, user, ids, summarise, where
):
    # long enough to be skipped, and with a pain in it that would be flagged if it were read
    note = note_of_length(MAX_NOTE_LENGTH + 1)
    workout_session = with_note(service_session, user, ids, where, note)

    response = summarise(user, workout_session)

    assert notice_codes(response) == ["NOTE_TOO_LONG_TO_CHECK"]
    [notice] = response.safety.notices
    assert notice.message == "A note on this workout was too long for Formiq to check."
    assert response.safety.status == "CAUTION"
    assert all(plan.status != "SEE_PROFESSIONAL" for plan in plans_of(response).values())
    assert_no_text_of(response, note, "sharp knee pain")


def test_the_notice_for_a_too_long_note_is_given_once(service_session, user, ids, summarise):
    note = "x" * (MAX_NOTE_LENGTH + 1)
    workout_session = with_note(service_session, user, ids, "session", note)
    workout_session.exercises[0].notes = note
    workout_session.exercises[1].sets[0].notes = note
    service_session.flush()

    assert notice_codes(summarise(user, workout_session)) == ["NOTE_TOO_LONG_TO_CHECK"]


def test_a_note_of_exactly_the_longest_length_is_scanned(service_session, user, ids, summarise):
    note = note_of_length(MAX_NOTE_LENGTH)
    assert len(note) == MAX_NOTE_LENGTH
    workout_session = with_note(service_session, user, ids, "exercise", note)

    response = summarise(user, workout_session)

    assert notice_codes(response) == ["NOTES_FLAGGED"]
    assert_no_text_of(response, note)


def test_a_note_that_is_too_long_does_not_hide_one_that_is_flagged(
    service_session, user, ids, summarise
):
    workout_session = with_note(service_session, user, ids, "exercise", PAIN_NOTE)
    workout_session.notes = "x" * (MAX_NOTE_LENGTH + 1)
    service_session.flush()

    response = summarise(user, workout_session)

    assert notice_codes(response) == ["NOTES_FLAGGED", "NOTE_TOO_LONG_TO_CHECK"]


def test_the_longest_note_is_as_long_as_a_coach_message():
    CoachMessageRequest(message="a" * MAX_NOTE_LENGTH)
    with pytest.raises(ValidationError):
        CoachMessageRequest(message="a" * (MAX_NOTE_LENGTH + 1))


def test_a_flagged_note_on_a_skipped_exercise_gives_the_notice_but_no_muscle_to_flag(
    service_session, user, ids, summarise
):
    workout_session = add_workout(
        service_session,
        user,
        [
            Ex(BENCH, [S(8, 60.0)]),
            Ex("Dumbbell Biceps Curl", [S(12, 15.0, completed=False)], notes=PAIN_NOTE),
        ],
        ids,
    )

    response = summarise(user, workout_session)

    # the curl was not done, so Biceps has no recovery entry to turn over
    assert notice_codes(response) == ["NOTES_FLAGGED"]
    assert "Biceps" not in plans_of(response)
    assert all(plan.status != "SEE_PROFESSIONAL" for plan in plans_of(response).values())
    assert response.safety.status == "CAUTION"


# reported discomfort


def test_reported_pain_sends_its_muscles_to_a_professional_with_no_return_time(
    service_session, user, ids, summarise
):
    workout_session = lifting(service_session, user, ids)

    response = summarise(user, workout_session, discomfort=[reported("KNEES", "PAIN", 5)])

    plans = plans_of(response)
    for muscle in ("Quadriceps", "Hamstrings", "Calves"):
        assert plans[muscle].status == "SEE_PROFESSIONAL"
        assert plans[muscle].rest_hours is None and plans[muscle].rest_until is None
        for reason in plans[muscle].reasons:
            assert not re.search(r"\d", reason), reason
            assert not re.search(r"\b(hours?|days?|weeks?|minutes?)\b", reason, re.I), reason
        assert "doctor or physiotherapist" in " ".join(plans[muscle].reasons)
    assert plans["Chest"].status == "REST"
    assert response.safety.status == "CAUTION"
    assert notice_codes(response) == ["PAIN_OR_INJURY"]
    [notice] = response.safety.notices
    assert not re.search(r"\b(hours?|days?|weeks?)\b", notice.message, re.I)


@pytest.mark.parametrize(
    ("severity", "hours", "status", "codes"),
    [
        (0, 48, "OK", []),
        (3, 48, "OK", []),
        (4, 72, "CAUTION", []),
        (6, 72, "CAUTION", []),
        (7, 72, "CAUTION", ["SEVERE_SORENESS"]),
        (10, 72, "CAUTION", ["SEVERE_SORENESS"]),
    ],
)
def test_reported_soreness_sets_the_rest_window(
    service_session, user, ids, summarise, severity, hours, status, codes
):
    workout_session = lifting(service_session, user, ids)

    response = summarise(
        user, workout_session, discomfort=[reported("FRONT_THIGHS", "SORENESS", severity)]
    )

    quadriceps = plans_of(response)["Quadriceps"]
    assert (quadriceps.status, quadriceps.rest_hours) == ("REST", hours)
    assert quadriceps.rest_until == DONE + timedelta(hours=hours)
    assert response.safety.status == status
    assert notice_codes(response) == codes
    # a muscle that is not sore keeps its own window
    assert plans_of(response)["Chest"].rest_hours == 48


def test_mild_soreness_changes_nothing(service_session, user, ids, summarise):
    workout_session = lifting(service_session, user, ids)
    baseline = summarise(user, workout_session)

    response = summarise(
        user, workout_session, discomfort=[reported("FRONT_THIGHS", "SORENESS", 3)]
    )

    assert response.model_dump() == baseline.model_dump()


def test_the_severe_soreness_notice_lists_the_warning_signs_and_cites_its_source(
    service_session, user, ids, summarise
):
    workout_session = lifting(service_session, user, ids)

    response = summarise(
        user, workout_session, discomfort=[reported("CHEST", "SORENESS", 8)]
    )

    [notice] = response.safety.notices
    assert notice.source_ids == ["CDC_RHABDO"]
    for name in recovery.WARNING_SIGN_NAMES.values():
        assert name in notice.message
    assert "CDC_RHABDO" in [source.id for source in response.sources]


# warning signs


def withheld_texts():
    """Every text of the guidance a warning sign withholds."""
    texts = [item.text for item in nutrition.hydration_items()]
    texts += [item.text for item in nutrition.post_workout_carbohydrate_items()]
    texts += [item.text for item in recovery.general_recovery_items()]
    texts += [item.text for item in [recovery.sleep_item(5.0)] if item]
    texts += [food.name for food in foods.FOODS]
    texts += ["Trained as a main muscle in this workout", "Worked as a supporting muscle only"]
    texts += [
        "Assumes a healthy adult",
        "Your goal is fat loss",
        "Allergies are not recorded",
        "Not trained in this workout",
    ]
    return texts


@pytest.mark.parametrize("sign", ["CHEST_PAIN", "DARK_URINE", "NUMBNESS_OR_TINGLING"])
def test_a_warning_sign_withholds_everything_but_the_calculated_facts(
    service_session, user, ids, profile_fields, summarise, sign, monkeypatch
):
    def not_called(*args, **kwargs):
        raise AssertionError("a withheld rule ran")

    add_profile(service_session, user, profile_fields, sleep_hours=5.0)
    workout_session = lifting(service_session, user, ids)
    normal = summarise(user, workout_session)
    # the texts first: they come from the functions that are about to be disabled
    texts = withheld_texts()
    for module, names in (
        (
            nutrition,
            (
                "post_workout_protein",
                "daily_protein",
                "daily_carbohydrate",
                "rapid_refuel",
                "active_energy",
                "hydration_items",
                "post_workout_carbohydrate_items",
            ),
        ),
        (foods, ("suggest_foods",)),
        (recovery, ("muscle_recovery", "general_recovery_items", "sleep_item")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, not_called)

    response = summarise(
        user,
        workout_session,
        warning_signs=[sign],
        # none of these changes what a warning sign withholds
        discomfort=[reported("KNEES", "PAIN", 8)],
        avoid_allergens=["MILK"],
    )

    assert response.safety.status == "SEEK_MEDICAL_CARE"
    assert [notice.code for notice in response.safety.notices] == ["SEEK_MEDICAL_CARE"]
    [notice] = response.safety.notices
    assert "Stop training and seek medical care now" in notice.message
    assert response.estimates == Estimates()
    assert response.guidance == Guidance()
    assert response.guidance.hydration == [] and response.guidance.post_workout_carbohydrate == []
    assert response.guidance.sleep is None
    assert response.guidance.recovery is None and response.guidance.food_suggestions is None
    assert response.missing_data == []
    # the calculated facts stay
    assert response.calculated == normal.calculated
    assert response.calculated.exercises and response.calculated.muscles_trained
    assert response.calculated.profile_values_used is not None
    assert [source.id for source in response.sources] == ["ACSM_POSITION_2011", "CDC_RHABDO"]
    dumped = response.model_dump_json()
    for text in texts:
        assert text not in dumped, text
    # the normal summary does contain them, so the check above can fail
    normal_dump = normal.model_dump_json()
    assert sum(text in normal_dump for text in texts) >= 8


def test_every_warning_sign_withholds_guidance(service_session, user, ids, summarise):
    workout_session = lifting(service_session, user, ids)

    for sign in recovery.WARNING_SIGN_NAMES:
        response = summarise(user, workout_session, warning_signs=[sign])
        assert response.safety.status == "SEEK_MEDICAL_CARE"
        assert response.guidance == Guidance()
        assert response.estimates == Estimates()
        assert recovery.WARNING_SIGN_NAMES[sign] in response.safety.notices[0].message


def test_a_warning_sign_with_flagged_notes_still_shows_only_the_urgent_notice(
    service_session, user, ids, summarise
):
    workout_session = with_note(service_session, user, ids, "session", PAIN_NOTE)

    response = summarise(user, workout_session, warning_signs=["SUDDEN_SEVERE_PAIN"])

    assert notice_codes(response) == ["SEEK_MEDICAL_CARE"]
    assert_no_text_of(response, PAIN_NOTE)


# foods


@pytest.mark.parametrize(
    ("preference", "pattern", "excluded"),
    [
        ("vegetarian", "VEGETARIAN", ANIMAL_FOODS),
        ("Vegetarian", "VEGETARIAN", ANIMAL_FOODS),
        ("vegan", "VEGAN", ANIMAL_FOODS | {"DAIRY"}),
        ("eggetarian", "EGGETARIAN", {"MEAT", "POULTRY", "FISH", "SHELLFISH"}),
        ("pescatarian", "PESCATARIAN", {"MEAT", "POULTRY"}),
        ("non_vegetarian", "NO_RESTRICTION", set()),
    ],
)
def test_the_foods_fit_the_dietary_preference(
    service_session, user, ids, profile_fields, summarise, preference, pattern, excluded
):
    add_profile(service_session, user, profile_fields, dietary_preference=preference)
    workout_session = lifting(service_session, user, ids)

    suggestions = summarise(user, workout_session).guidance.food_suggestions

    assert suggestions.preference_status == "APPLIED"
    assert suggestions.dietary_pattern == pattern
    assert suggestions.items
    for item in suggestions.items:
        assert not excluded & set(item.contains), item.name
        assert pattern in item.suits


def test_the_foods_avoid_the_allergens_given(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(service_session, user, profile_fields, dietary_preference="non_vegetarian")
    workout_session = lifting(service_session, user, ids)

    suggestions = summarise(
        user, workout_session, avoid_allergens=["SOY", "MILK", "FISH", "WHEAT"]
    ).guidance.food_suggestions

    assert suggestions.allergens_excluded == ["MILK", "FISH", "WHEAT", "SOY"]
    assert suggestions.items
    for item in suggestions.items:
        assert not {"MILK", "FISH", "WHEAT", "SOY"} & set(item.allergens), item.name
    assert any(
        "Other allergens are not checked: check labels" in text for text in suggestions.caveats
    )


def test_a_food_item_carries_its_nutrients_and_what_it_contains(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(service_session, user, profile_fields, dietary_preference="non_vegetarian")
    workout_session = lifting(service_session, user, ids)

    items = summarise(user, workout_session).guidance.food_suggestions.items

    chicken = next(item for item in items if item.name == "Chicken breast, roasted")
    assert chicken.contains == ["POULTRY"] and chicken.allergens == []
    assert chicken.suits == ["NO_RESTRICTION"]
    assert chicken.protein_g == pytest.approx(26.7) and chicken.carbohydrate_g == 0.0
    assert chicken.source_id == "USDA_FDC"
    assert next(item for item in items if item.name.startswith("Salmon")).allergens == ["FISH"]


def test_an_unrecognised_dietary_preference_gives_no_foods(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(service_session, user, profile_fields, dietary_preference="keto")
    workout_session = lifting(service_session, user, ids)

    response = summarise(user, workout_session)

    suggestions = response.guidance.food_suggestions
    assert suggestions.preference_status == "NOT_RECOGNISED"
    assert suggestions.dietary_pattern is None
    assert suggestions.items == []
    accepted = ", ".join(foods.DIET_ALIASES)
    assert any(f"Accepted values: {accepted}" in caveat for caveat in suggestions.caveats)
    # no foods, so the food source is not cited
    assert "USDA_FDC" not in [source.id for source in response.sources]
    # the rest of the summary is unaffected
    assert response.guidance.hydration and given(response) == ALL_ESTIMATES


def test_an_unset_dietary_preference_filters_nothing_and_says_so(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(service_session, user, profile_fields, dietary_preference=None)
    workout_session = lifting(service_session, user, ids)

    suggestions = summarise(user, workout_session).guidance.food_suggestions

    assert suggestions.preference_status == "NOT_SET"
    assert suggestions.items
    assert any("not filtered by diet" in caveat for caveat in suggestions.caveats)


# goal rate


@pytest.mark.parametrize(
    ("weight", "target", "weeks", "too_fast"),
    [
        (80.0, 60.0, 4, True),
        (80.0, 79.0, 4, False),
        # exactly 2 kg a week is not more than 2 kg a week
        (80.0, 72.0, 4, False),
        (80.0, 71.9, 4, True),
        # a period under a week counts as one week
        (80.0, 79.0, 0, False),
        (80.0, 77.0, 0, True),
        # a goal to gain, or to stay, is not a loss
        (80.0, 90.0, 1, False),
        (80.0, 80.0, 1, False),
    ],
)
def test_a_goal_that_loses_weight_too_fast_adds_a_caution_and_keeps_the_estimates(
    service_session, user, ids, profile_fields, summarise, weight, target, weeks, too_fast
):
    add_profile(
        service_session,
        user,
        profile_fields,
        weight_kg=weight,
        target_weight_kg=target,
        goal_period_weeks=weeks,
    )
    workout_session = lifting(service_session, user, ids)

    response = summarise(user, workout_session)

    assert (notice_codes(response) == ["GOAL_RATE_TOO_FAST"]) is too_fast
    assert response.safety.status == ("CAUTION" if too_fast else "OK")
    # the targets are still shown
    assert given(response) == ALL_ESTIMATES
    if too_fast:
        [notice] = response.safety.notices
        assert notice.message == (
            "Your recorded goal needs losing more than 2 kg a week, which Formiq treats as "
            "too fast: please talk to a doctor or dietitian. The ranges below only fuel "
            "training."
        )
        assert notice.source_ids == []


def test_a_goal_without_a_target_or_a_period_adds_no_caution(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(
        service_session,
        user,
        profile_fields,
        weight_kg=80.0,
        target_weight_kg=60.0,
        goal_period_weeks=None,
    )
    workout_session = lifting(service_session, user, ids)

    assert summarise(user, workout_session).safety.notices == []


def test_the_goal_rate_is_not_a_caution_in_a_summary_without_a_profile(
    service_session, user, ids, summarise
):
    assert summarise(user, lifting(service_session, user, ids)).safety.notices == []


# ownership and status


def test_another_users_completed_session_is_not_found(
    service_session, user, other_user, ids, summarise
):
    others = lifting(service_session, other_user, ids)

    with pytest.raises(WorkoutSessionNotFoundError, match="has no workout session"):
        summarise(user, others)


def test_a_missing_session_is_not_found(service_session, user, ids, summarise):
    own = lifting(service_session, user, ids)

    with pytest.raises(WorkoutSessionNotFoundError):
        summarise(user, own, session_id=2_000_000_000)


@pytest.mark.parametrize("status", ["IN_PROGRESS", "CANCELLED"])
def test_a_session_that_is_not_completed_has_no_summary(
    service_session, user, ids, summarise, status
):
    workout_session = lifting(service_session, user, ids, status=status, completed_at=None)
    session_id = workout_session.id

    with pytest.raises(WorkoutSessionNotCompletedError) as raised:
        summarise(user, workout_session)

    assert isinstance(raised.value, WorkoutSessionConflictError)
    assert str(raised.value) == (
        f"workout session {session_id} is {status}; "
        "only COMPLETED workout sessions have a recovery summary"
    )


@pytest.mark.parametrize("status", ["IN_PROGRESS", "CANCELLED"])
def test_another_users_unfinished_session_is_not_found_not_not_completed(
    service_session, user, other_user, ids, summarise, status
):
    others = lifting(service_session, other_user, ids, status=status, completed_at=None)

    with pytest.raises(WorkoutSessionNotFoundError):
        summarise(user, others)


# determinism


def test_the_same_clock_gives_the_same_summary(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(service_session, user, profile_fields, dietary_preference="vegetarian")
    workout_session = lifting(service_session, user, ids)
    request = {
        "discomfort": [reported("KNEES", "SORENESS", 5), reported("NECK", "PAIN", 2)],
        "avoid_allergens": ["PEANUTS"],
    }

    first = summarise(user, workout_session, **request)
    second = summarise(user, workout_session, **request)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.model_dump_json() == second.model_dump_json()


@pytest.mark.parametrize(
    ("later", "hours"),
    [
        (timedelta(0), 0.0),
        (timedelta(minutes=90), 1.5),
        (timedelta(hours=1), 1.0),
        (timedelta(hours=30), 30.0),
        # a clock before the workout never gives negative hours
        (timedelta(hours=-2), 0.0),
    ],
)
def test_the_hours_since_the_workout_come_from_the_clock(
    service_session, user, ids, summarise, later, hours
):
    workout_session = lifting(service_session, user, ids)

    response = summarise(user, workout_session, clock=clock_at(DONE + later))

    assert response.hours_since_completed == hours
    assert response.completed_at == DONE


def test_the_default_clock_is_the_current_time(service_session, user, ids):
    now = datetime.now(UTC)
    workout_session = lifting(
        service_session,
        user,
        ids,
        started_at=now - timedelta(hours=2),
        completed_at=now - timedelta(hours=1),
    )
    owner_id, session_id = user.id, workout_session.id
    service_session.commit()

    response = RecoverySummaryService(service_session).build_summary(
        owner_id, session_id, request_of()
    )

    assert response.hours_since_completed == pytest.approx(1.0, abs=0.05)


# nothing is written


def table_state(engine):
    """Row counts of the tables a summary reads, and the session's and profile's rows, read
    through a connection of its own."""
    with Session(engine) as session:
        counts = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (
                User,
                UserProfile,
                WorkoutSession,
                WorkoutSessionExercise,
                WorkoutSet,
                WorkoutPlan,
            )
        }
        rows = [columns(row) for row in session.scalars(select(WorkoutSession))]
        rows += [columns(row) for row in session.scalars(select(WorkoutSessionExercise))]
        rows += [columns(row) for row in session.scalars(select(WorkoutSet))]
        rows += [columns(row) for row in session.scalars(select(UserProfile))]
        return counts, rows


def test_nothing_is_written(
    service_session, test_engine, user, ids, profile_fields, monkeypatch
):
    add_profile(service_session, user, profile_fields, dietary_preference="vegetarian")
    plan = add_plan(service_session, user, exercise_ids=[ids[SQUAT]])
    workout_session = with_note(service_session, user, ids, "exercise", PAIN_NOTE)
    workout_session.exercises[0].plan_exercise_id = plan.exercises[0].id
    owner_id, session_id = user.id, workout_session.id
    service_session.commit()
    before = table_state(test_engine)
    original_flush = service_session.flush

    def commit_not_allowed(*args, **kwargs):
        raise AssertionError("the summary committed")

    def flush_with_changes_not_allowed(*args, **kwargs):
        # a flush with nothing pending (a query's autoflush) writes nothing
        if service_session.new or service_session.dirty or service_session.deleted:
            raise AssertionError("the summary flushed changes")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(service_session, "commit", commit_not_allowed)
    monkeypatch.setattr(service_session, "flush", flush_with_changes_not_allowed)

    with recorded_statements(test_engine) as statements:
        service = RecoverySummaryService(service_session, clock=CLOCK)
        response = service.build_summary(
            owner_id,
            session_id,
            request_of(
                discomfort=[reported("KNEES", "SORENESS", 5)], avoid_allergens=["MILK"]
            ),
        )

    assert response.safety.status == "CAUTION"
    assert statements
    # only reads: no insert, update, delete or lock
    for statement in statements:
        assert statement.lstrip().upper().startswith("SELECT"), statement
        assert "FOR UPDATE" not in statement.upper() and "FOR SHARE" not in statement.upper()
    assert not (service_session.new or service_session.dirty or service_session.deleted)
    assert table_state(test_engine) == before


def test_the_queries_do_not_grow_with_the_number_of_exercises(
    service_session, test_engine, user, ids, profile_fields
):
    add_profile(service_session, user, profile_fields)
    few = add_workout(service_session, user, [Ex(SQUAT, [S(5, 100.0)])], ids)
    names = [SQUAT, BENCH, "Pull-Up", "Seated Cable Row", "Walking Lunge", "Romanian Deadlift"]
    many = add_workout(
        service_session,
        user,
        [Ex(name, [S(5, 50.0), S(5, 50.0, notes="fine")], notes="ok") for name in names],
        ids,
    )
    service_session.commit()
    owner_id, few_id, many_id = user.id, few.id, many.id

    def count(session_id):
        service_session.expire_all()
        service = RecoverySummaryService(service_session, clock=CLOCK)
        with recorded_statements(test_engine) as statements:
            service.build_summary(owner_id, session_id, request_of())
        return len(statements)

    assert count(few_id) == count(many_id)
    assert count(many_id) <= 10


# sources


@pytest.mark.parametrize(
    "request_fields",
    [
        {},
        {"avoid_allergens": ["PEANUTS"]},
        {"discomfort": [reported("CHEST", "SORENESS", 9), reported("KNEES", "PAIN", 4)]},
        {"warning_signs": ["DARK_URINE"]},
    ],
)
def test_the_sources_are_exactly_the_ones_cited(
    service_session, user, ids, profile_fields, summarise, request_fields
):
    add_profile(
        service_session, user, profile_fields, dietary_preference="vegetarian", sleep_hours=6.0
    )
    workout_session = lifting(service_session, user, ids)

    response = summarise(user, workout_session, **request_fields)

    dumped = response.model_dump(mode="json")
    sources = [source["id"] for source in dumped["sources"]]
    assert sources
    cited = cited_ids({key: value for key, value in dumped.items() if key != "sources"})
    if "warning_signs" not in request_fields:
        # the food suggestions' own sources have no field in the response but its sources
        extra = foods.suggest_foods("vegetarian", request_fields.get("avoid_allergens", ()))
        cited |= {str(source_id) for source_id in extra.source_ids}
    assert set(sources) == cited
    assert len(sources) == len(set(sources))
    for source in response.sources:
        assert source.citation and source.url.startswith("https://")


def test_the_food_and_allergen_sources_are_cited_when_those_are_shown(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(service_session, user, profile_fields, dietary_preference="vegetarian")
    workout_session = lifting(service_session, user, ids)

    plain = summarise(user, workout_session)
    excluding = summarise(user, workout_session, avoid_allergens=["PEANUTS"])

    plain_ids = [source.id for source in plain.sources]
    excluding_ids = [source.id for source in excluding.sources]
    assert "USDA_FDC" in plain_ids and "FDA_ALLERGENS" not in plain_ids
    assert "USDA_FDC" in excluding_ids and "FDA_ALLERGENS" in excluding_ids
    # in the order of the registry, not the order they were cited in
    registry = [source.id.value for source in SOURCES]
    assert excluding_ids == sorted(excluding_ids, key=registry.index)


def test_the_estimates_cite_their_own_sources(
    service_session, user, ids, profile_fields, summarise
):
    add_profile(service_session, user, profile_fields)
    workout_session = lifting(service_session, user, ids)

    response = summarise(user, workout_session)

    sources = {source.id for source in response.sources}
    assert {"ISSN_TIMING_2017", "ACSM_NUTRITION_2016", "COMPENDIUM_2024"} <= sources
    for estimate in response.estimates.model_dump().values():
        assert set(estimate["source_ids"]) <= sources


# the repositories' batch queries


def test_exercises_are_found_by_id_in_one_batch_with_their_muscles(
    service_session, test_engine, ids
):
    wanted = [ids[BENCH], ids[SQUAT], ids[BENCH], 2_000_000_000]

    with recorded_statements(test_engine) as statements:
        found = ExerciseRepository(service_session).find_by_ids(wanted)
        for exercise in found:
            [link.muscle_group.name for link in exercise.muscles]
            [item.name for item in exercise.equipment]

    assert [exercise.id for exercise in found] == sorted({ids[BENCH], ids[SQUAT]})
    assert {exercise.name for exercise in found} == {BENCH, SQUAT}
    # the exercises, then their muscles and their equipment: three queries however many
    assert len(statements) == 3


def test_no_exercise_ids_is_no_query(service_session, test_engine):
    with recorded_statements(test_engine) as statements:
        assert ExerciseRepository(service_session).find_by_ids([]) == []
        assert ExerciseRepository(service_session).find_by_ids(set()) == []
    assert statements == []


def test_plan_exercises_are_found_by_id(service_session, test_engine, user, ids):
    plan = add_plan(service_session, user, exercise_ids=[ids[SQUAT], ids[BENCH], ids["Pull-Up"]])
    first, second, third = plan.exercises

    with recorded_statements(test_engine) as statements:
        found = WorkoutPlanExerciseRepository(service_session).find_by_ids(
            {third.id, first.id, 2_000_000_000}
        )

    assert [item.id for item in found] == [first.id, third.id]
    assert second.id not in [item.id for item in found]
    assert statements


def test_no_plan_exercise_ids_is_no_query(service_session, test_engine):
    with recorded_statements(test_engine) as statements:
        assert WorkoutPlanExerciseRepository(service_session).find_by_ids([]) == []
    assert statements == []
