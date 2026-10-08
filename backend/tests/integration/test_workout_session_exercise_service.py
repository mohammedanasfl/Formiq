"""Integration tests for WorkoutSessionExerciseService.

They require the local PostgreSQL container to be running (test database).
Services commit, so the service_session fixture empties the user, workout plan
and workout session tables before and after each test.
"""

import pytest

from app.schemas import (
    UserCreate,
    WorkoutPlanCreate,
    WorkoutPlanExerciseCreate,
    WorkoutSessionCreate,
    WorkoutSessionExerciseCreate,
    WorkoutSessionExerciseUpdate,
    WorkoutSessionUpdate,
    WorkoutSetCreate,
)
from app.services import (
    UserService,
    WorkoutPlanService,
    WorkoutSessionExerciseService,
    WorkoutSessionService,
    WorkoutSetService,
)
from app.services.exceptions import (
    ExerciseNotFoundError,
    InactiveExerciseError,
    InvalidWorkoutSessionError,
    SessionExerciseOrderTakenError,
    WorkoutSessionExerciseNotFoundError,
    WorkoutSessionNotEditableError,
    WorkoutSessionNotFoundError,
)
from tests.integration.workout_plans import DATE, retire_exercise
from tests.integration.workout_sessions import stored_session


@pytest.fixture
def service(service_session):
    return WorkoutSessionExerciseService(service_session)


@pytest.fixture
def user(service_session):
    return UserService(service_session).create_user(
        UserCreate(email="session-exercise@example.com")
    )


@pytest.fixture
def other_user(service_session):
    return UserService(service_session).create_user(
        UserCreate(email="session-ex-other@example.com")
    )


@pytest.fixture
def bench_press(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Bench Press"]


@pytest.fixture
def squat(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Back Squat"]


@pytest.fixture
def make_plan(service_session, user, bench_press):
    """Creates a committed PLANNED plan with a bench press at exercise_order 1."""

    def make(owner=None):
        return WorkoutPlanService(service_session).create_plan(
            (owner or user).id,
            WorkoutPlanCreate(
                name="Push Day",
                status="PLANNED",
                scheduled_date=DATE,
                exercises=[
                    WorkoutPlanExerciseCreate(
                        exercise_id=bench_press, exercise_order=1, sets=3, reps=8
                    )
                ],
            ),
        )

    return make


@pytest.fixture
def make_session(service, service_session, user, bench_press):
    """Creates a committed session in the given status, by default with one
    bench press at exercise_order 1, with one set."""
    sessions = WorkoutSessionService(service_session)

    def make(status="IN_PROGRESS", *, owner=None, workout_plan_id=None, with_exercise=True):
        owner_id = (owner or user).id
        workout_session = sessions.create_session(
            owner_id, WorkoutSessionCreate(workout_plan_id=workout_plan_id)
        )
        if with_exercise:
            session_exercise = service.add_exercise(
                owner_id,
                workout_session.id,
                WorkoutSessionExerciseCreate(exercise_id=bench_press, exercise_order=1),
            )
            WorkoutSetService(service_session).add_set(
                owner_id,
                workout_session.id,
                session_exercise.id,
                WorkoutSetCreate(set_number=1, reps=8),
            )
        if status != "IN_PROGRESS":
            sessions.update_session(
                owner_id, workout_session.id, WorkoutSessionUpdate(status=status)
            )
        return workout_session

    return make


def session_exercise(exercise_id, exercise_order=1, **fields):
    return WorkoutSessionExerciseCreate(
        exercise_id=exercise_id, exercise_order=exercise_order, **fields
    )


def stored_exercises(engine, session_id):
    """(exercise_order, exercise_id, plan_exercise_id) of the session's committed exercises."""
    return [
        (item["exercise_order"], item["exercise_id"], item["plan_exercise_id"])
        for item in stored_session(engine, session_id)["exercises"]
    ]


# add_exercise


def test_add_exercise_to_a_manual_session(service, user, make_session, squat, test_engine):
    workout_session = make_session(with_exercise=False)

    added = service.add_exercise(
        user.id, workout_session.id, session_exercise(squat, 1, notes="Felt heavy")
    )

    assert (added.workout_session_id, added.exercise_id, added.sets) == (
        workout_session.id,
        squat,
        [],
    )
    stored = stored_session(test_engine, workout_session.id)["exercises"]
    assert [(item["exercise_id"], item["plan_exercise_id"], item["notes"]) for item in stored] == [
        (squat, None, "Felt heavy")
    ]


def test_add_a_substitute_for_a_planned_exercise(
    service, user, make_plan, make_session, squat, test_engine
):
    plan = make_plan()
    planned = plan.exercises[0]  # a bench press
    workout_session = make_session(workout_plan_id=plan.id, with_exercise=False)

    service.add_exercise(
        user.id, workout_session.id, session_exercise(squat, 1, plan_exercise_id=planned.id)
    )

    # did a squat instead of the planned bench press
    assert stored_exercises(test_engine, workout_session.id) == [(1, squat, planned.id)]


@pytest.mark.parametrize(
    ("session_plan", "linked_plan", "message"),
    [
        ("none", "own", "has no workout plan, so it cannot link"),
        ("own", "another of the user", "has no exercise"),
        ("own", "another user's", "has no exercise"),
    ],
)
def test_plan_exercise_link_must_be_in_the_sessions_plan(
    service,
    user,
    other_user,
    make_plan,
    make_session,
    bench_press,
    test_engine,
    session_plan,
    linked_plan,
    message,
):
    own_plan = make_plan()
    linked = {
        "own": own_plan,
        "another of the user": make_plan(),
        "another user's": make_plan(owner=other_user),
    }[linked_plan]
    workout_session = make_session(
        workout_plan_id=own_plan.id if session_plan == "own" else None, with_exercise=False
    )

    with pytest.raises(InvalidWorkoutSessionError, match=message):
        service.add_exercise(
            user.id,
            workout_session.id,
            session_exercise(bench_press, 1, plan_exercise_id=linked.exercises[0].id),
        )

    assert stored_exercises(test_engine, workout_session.id) == []


def test_add_exercise_rejects_an_unknown_exercise(service, user, make_session, test_engine):
    workout_session = make_session(with_exercise=False)

    with pytest.raises(ExerciseNotFoundError):
        service.add_exercise(user.id, workout_session.id, session_exercise(2_147_483_647))

    assert stored_exercises(test_engine, workout_session.id) == []


def test_add_exercise_rejects_an_inactive_exercise(
    service, user, make_session, retirable_exercise_id, test_engine
):
    workout_session = make_session(with_exercise=False)
    retire_exercise(test_engine, retirable_exercise_id)

    with pytest.raises(InactiveExerciseError):
        service.add_exercise(user.id, workout_session.id, session_exercise(retirable_exercise_id))

    assert stored_exercises(test_engine, workout_session.id) == []


def test_add_exercise_rejects_a_taken_order_but_repeats_exercises(
    service, user, make_session, bench_press, squat, test_engine
):
    workout_session = make_session()

    with pytest.raises(SessionExerciseOrderTakenError, match="exercise_order 1"):
        service.add_exercise(user.id, workout_session.id, session_exercise(squat, 1))
    service.add_exercise(user.id, workout_session.id, session_exercise(bench_press, 2))

    assert stored_exercises(test_engine, workout_session.id) == [
        (1, bench_press, None),
        (2, bench_press, None),
    ]


# update_exercise


def test_update_exercise_changes_only_the_supplied_fields(
    service, user, make_session, squat, test_engine
):
    workout_session = make_session()
    before = stored_session(test_engine, workout_session.id)["exercises"][0]

    updated = service.update_exercise(
        user.id,
        workout_session.id,
        before["id"],
        WorkoutSessionExerciseUpdate(exercise_id=squat, notes="Swapped"),
    )

    after = stored_session(test_engine, workout_session.id)["exercises"][0]
    assert (updated.exercise_id, after["exercise_id"], after["notes"]) == (squat, squat, "Swapped")
    unchanged = set(before) - {"exercise_id", "notes", "updated_at"}
    assert {key: after[key] for key in unchanged} == {key: before[key] for key in unchanged}


def test_update_exercise_links_and_unlinks_a_planned_exercise(
    service, user, make_plan, make_session, bench_press, test_engine
):
    plan = make_plan()
    planned_id = plan.exercises[0].id
    workout_session = make_session(workout_plan_id=plan.id)
    session_exercise_id = stored_session(test_engine, workout_session.id)["exercises"][0]["id"]

    service.update_exercise(
        user.id,
        workout_session.id,
        session_exercise_id,
        WorkoutSessionExerciseUpdate(plan_exercise_id=planned_id),
    )
    assert stored_exercises(test_engine, workout_session.id) == [(1, bench_press, planned_id)]

    service.update_exercise(
        user.id,
        workout_session.id,
        session_exercise_id,
        WorkoutSessionExerciseUpdate(plan_exercise_id=None),
    )
    assert stored_exercises(test_engine, workout_session.id) == [(1, bench_press, None)]


def test_update_exercise_cannot_link_another_plans_exercise(
    service, user, make_plan, make_session, test_engine
):
    plan = make_plan()
    other_plan = make_plan()
    workout_session = make_session(workout_plan_id=plan.id)
    before = stored_session(test_engine, workout_session.id)

    with pytest.raises(InvalidWorkoutSessionError, match=f"workout plan {plan.id} has no exercise"):
        service.update_exercise(
            user.id,
            workout_session.id,
            before["exercises"][0]["id"],
            WorkoutSessionExerciseUpdate(plan_exercise_id=other_plan.exercises[0].id),
        )

    assert stored_session(test_engine, workout_session.id) == before


@pytest.mark.parametrize("field", ["exercise_id", "exercise_order"])
def test_update_exercise_rejects_null_for_required_fields(
    service, user, make_session, test_engine, field
):
    workout_session = make_session()
    before = stored_session(test_engine, workout_session.id)

    with pytest.raises(InvalidWorkoutSessionError, match=f"cannot be null: {field}"):
        service.update_exercise(
            user.id,
            workout_session.id,
            before["exercises"][0]["id"],
            WorkoutSessionExerciseUpdate(**{field: None}),
        )

    assert stored_session(test_engine, workout_session.id) == before


def test_update_exercise_cannot_switch_to_an_inactive_exercise(
    service, user, make_session, retirable_exercise_id, test_engine
):
    workout_session = make_session()
    before = stored_session(test_engine, workout_session.id)
    retire_exercise(test_engine, retirable_exercise_id)

    with pytest.raises(InactiveExerciseError):
        service.update_exercise(
            user.id,
            workout_session.id,
            before["exercises"][0]["id"],
            WorkoutSessionExerciseUpdate(exercise_id=retirable_exercise_id),
        )

    assert stored_session(test_engine, workout_session.id) == before


def test_exercise_retired_during_the_session_stays_editable(
    service, user, make_session, retirable_exercise_id, test_engine
):
    workout_session = make_session(with_exercise=False)
    added = service.add_exercise(
        user.id, workout_session.id, session_exercise(retirable_exercise_id)
    )
    retire_exercise(test_engine, retirable_exercise_id)

    # it keeps its exercise, so the active check does not apply
    service.update_exercise(
        user.id,
        workout_session.id,
        added.id,
        WorkoutSessionExerciseUpdate(exercise_id=retirable_exercise_id, notes="Still here"),
    )

    stored = stored_session(test_engine, workout_session.id)["exercises"]
    assert [(item["exercise_id"], item["notes"]) for item in stored] == [
        (retirable_exercise_id, "Still here")
    ]


def test_update_exercise_rejects_a_taken_order(
    service, user, make_session, bench_press, squat, test_engine
):
    workout_session = make_session()
    first_id = stored_session(test_engine, workout_session.id)["exercises"][0]["id"]
    service.add_exercise(user.id, workout_session.id, session_exercise(squat, 2))

    with pytest.raises(SessionExerciseOrderTakenError):
        service.update_exercise(
            user.id, workout_session.id, first_id, WorkoutSessionExerciseUpdate(exercise_order=2)
        )
    # keeping its own position is no conflict
    service.update_exercise(
        user.id, workout_session.id, first_id, WorkoutSessionExerciseUpdate(exercise_order=1)
    )
    service.update_exercise(
        user.id, workout_session.id, first_id, WorkoutSessionExerciseUpdate(exercise_order=3)
    )

    assert stored_exercises(test_engine, workout_session.id) == [
        (2, squat, None),
        (3, bench_press, None),
    ]


# remove_exercise


def test_remove_exercise_deletes_it_and_its_sets(service, user, make_session, squat, test_engine):
    workout_session = make_session()
    first_id = stored_session(test_engine, workout_session.id)["exercises"][0]["id"]
    service.add_exercise(user.id, workout_session.id, session_exercise(squat, 2))

    service.remove_exercise(user.id, workout_session.id, first_id)

    assert stored_exercises(test_engine, workout_session.id) == [(2, squat, None)]


# rules shared by the three operations


@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED"])
@pytest.mark.parametrize("operation", ["add", "update", "remove"])
def test_finished_session_exercises_cannot_be_changed(
    service, user, make_session, squat, test_engine, status, operation
):
    workout_session = make_session(status)
    before = stored_session(test_engine, workout_session.id)
    session_exercise_id = before["exercises"][0]["id"]

    with pytest.raises(WorkoutSessionNotEditableError):
        if operation == "add":
            service.add_exercise(user.id, workout_session.id, session_exercise(squat, 2))
        elif operation == "update":
            service.update_exercise(
                user.id,
                workout_session.id,
                session_exercise_id,
                WorkoutSessionExerciseUpdate(exercise_id=squat),
            )
        else:
            service.remove_exercise(user.id, workout_session.id, session_exercise_id)

    assert stored_session(test_engine, workout_session.id) == before


@pytest.mark.parametrize("operation", ["add", "update", "remove"])
def test_another_users_session_exercises_are_not_found(
    service, user, other_user, make_session, squat, test_engine, operation
):
    workout_session = make_session(owner=other_user)
    before = stored_session(test_engine, workout_session.id)
    session_exercise_id = before["exercises"][0]["id"]

    with pytest.raises(WorkoutSessionNotFoundError, match=f"user {user.id} has no workout session"):
        if operation == "add":
            service.add_exercise(user.id, workout_session.id, session_exercise(squat, 2))
        elif operation == "update":
            service.update_exercise(
                user.id,
                workout_session.id,
                session_exercise_id,
                WorkoutSessionExerciseUpdate(notes="Mine"),
            )
        else:
            service.remove_exercise(user.id, workout_session.id, session_exercise_id)

    assert stored_session(test_engine, workout_session.id) == before


@pytest.mark.parametrize("operation", ["update", "remove"])
def test_exercise_of_another_session_is_not_found(
    service, user, make_session, test_engine, operation
):
    # the user's earlier session: one session is IN_PROGRESS at a time
    other_session = make_session("COMPLETED")
    workout_session = make_session()
    other_exercise_id = stored_session(test_engine, other_session.id)["exercises"][0]["id"]
    before = stored_session(test_engine, other_session.id)

    with pytest.raises(WorkoutSessionExerciseNotFoundError):
        if operation == "update":
            service.update_exercise(
                user.id,
                workout_session.id,
                other_exercise_id,
                WorkoutSessionExerciseUpdate(notes="Moved"),
            )
        else:
            service.remove_exercise(user.id, workout_session.id, other_exercise_id)

    assert stored_session(test_engine, other_session.id) == before
