"""Integration tests for WorkoutSetService.

They require the local PostgreSQL container to be running (test database).
Services commit, so the service_session fixture empties the user, workout plan
and workout session tables before and after each test.
"""

from unittest.mock import patch

import pytest
from sqlalchemy.exc import DataError

from app.schemas import (
    UserCreate,
    WorkoutSessionCreate,
    WorkoutSessionExerciseCreate,
    WorkoutSessionUpdate,
    WorkoutSetCreate,
    WorkoutSetUpdate,
)
from app.services import (
    UserService,
    WorkoutSessionExerciseService,
    WorkoutSessionService,
    WorkoutSetService,
)
from app.services.exceptions import (
    InvalidWorkoutSessionError,
    SetNumberTakenError,
    WorkoutSessionExerciseNotFoundError,
    WorkoutSessionNotEditableError,
    WorkoutSessionNotFoundError,
    WorkoutSetNotFoundError,
)
from tests.integration.workout_sessions import stored_session


@pytest.fixture
def service(service_session):
    return WorkoutSetService(service_session)


@pytest.fixture
def user(service_session):
    return UserService(service_session).create_user(UserCreate(email="session-sets@example.com"))


@pytest.fixture
def other_user(service_session):
    return UserService(service_session).create_user(
        UserCreate(email="session-sets-other@example.com")
    )


@pytest.fixture
def bench_press(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Bench Press"]


@pytest.fixture
def make_session(service, service_session, user, bench_press):
    """Creates a committed session in the given status with two bench press
    exercises; the first has set 1 (8 reps at 50 kg). Returns the session id
    and the two session exercise ids."""
    sessions = WorkoutSessionService(service_session)
    session_exercises = WorkoutSessionExerciseService(service_session)

    def make(status="IN_PROGRESS", *, owner=None):
        owner_id = (owner or user).id
        session_id = sessions.create_session(owner_id, WorkoutSessionCreate()).id
        exercise_ids = [
            session_exercises.add_exercise(
                owner_id,
                session_id,
                WorkoutSessionExerciseCreate(exercise_id=bench_press, exercise_order=order),
            ).id
            for order in (1, 2)
        ]
        service.add_set(
            owner_id,
            session_id,
            exercise_ids[0],
            WorkoutSetCreate(set_number=1, reps=8, weight_kg=50.0),
        )
        if status != "IN_PROGRESS":
            sessions.update_session(owner_id, session_id, WorkoutSessionUpdate(status=status))
        return session_id, exercise_ids

    return make


def stored_sets(engine, session_id, exercise_index=0):
    """The committed sets of the session's exercise at that index."""
    return stored_session(engine, session_id)["exercises"][exercise_index]["sets"]


def summary(sets):
    return [(s["set_number"], s["reps"], s["weight_kg"], s["completed"]) for s in sets]


# add_set


def test_add_set_records_the_performed_set(service, user, make_session, test_engine):
    session_id, (first, _) = make_session()

    added = service.add_set(
        user.id,
        session_id,
        first,
        WorkoutSetCreate(set_number=2, reps=7, weight_kg=52.5, rpe=9.5, notes="Grinder"),
    )

    assert (added.workout_session_exercise_id, added.completed) == (first, True)
    stored = stored_sets(test_engine, session_id)[1]
    assert (stored["reps"], stored["weight_kg"], stored["rpe"], stored["notes"]) == (
        7,
        52.5,
        9.5,
        "Grinder",
    )


def test_add_a_skipped_set(service, user, make_session, test_engine):
    session_id, (first, _) = make_session()

    service.add_set(
        user.id, session_id, first, WorkoutSetCreate(set_number=2, reps=3, completed=False)
    )

    assert summary(stored_sets(test_engine, session_id)) == [
        (1, 8, 50.0, True),
        (2, 3, None, False),
    ]


def test_add_set_rejects_a_taken_set_number_of_the_same_exercise(
    service, user, make_session, test_engine
):
    session_id, (first, second) = make_session()

    with pytest.raises(SetNumberTakenError, match="set_number 1"):
        service.add_set(user.id, session_id, first, WorkoutSetCreate(set_number=1, reps=6))
    # set 1 of another exercise is no conflict
    service.add_set(user.id, session_id, second, WorkoutSetCreate(set_number=1, reps=6))

    assert summary(stored_sets(test_engine, session_id)) == [(1, 8, 50.0, True)]
    assert summary(stored_sets(test_engine, session_id, 1)) == [(1, 6, None, True)]


# update_set


def test_update_set_changes_only_the_supplied_fields(service, user, make_session, test_engine):
    session_id, (first, _) = make_session()
    before = stored_sets(test_engine, session_id)[0]

    updated = service.update_set(
        user.id, session_id, first, before["id"], WorkoutSetUpdate(reps=6, completed=False)
    )

    after = stored_sets(test_engine, session_id)[0]
    assert (updated.reps, after["reps"], after["completed"]) == (6, 6, False)
    unchanged = set(before) - {"reps", "completed", "updated_at"}
    assert {key: after[key] for key in unchanged} == {key: before[key] for key in unchanged}


def test_update_set_can_clear_optional_fields(service, user, make_session, test_engine):
    session_id, (first, _) = make_session()
    set_id = stored_sets(test_engine, session_id)[0]["id"]
    service.update_set(user.id, session_id, first, set_id, WorkoutSetUpdate(rpe=8, notes="x"))
    nullable = {"weight_kg": None, "rpe": None, "notes": None}

    service.update_set(user.id, session_id, first, set_id, WorkoutSetUpdate(**nullable))

    stored = stored_sets(test_engine, session_id)[0]
    assert {key: stored[key] for key in nullable} == nullable


@pytest.mark.parametrize("field", ["set_number", "reps", "completed"])
def test_update_set_rejects_null_for_required_fields(
    service, user, make_session, test_engine, field
):
    session_id, (first, _) = make_session()
    before = stored_session(test_engine, session_id)

    with pytest.raises(InvalidWorkoutSessionError, match=f"cannot be null: {field}"):
        service.update_set(
            user.id,
            session_id,
            first,
            before["exercises"][0]["sets"][0]["id"],
            WorkoutSetUpdate(**{field: None}),
        )

    assert stored_session(test_engine, session_id) == before


def test_update_set_rejects_a_taken_set_number(service, user, make_session, test_engine):
    session_id, (first, _) = make_session()
    set_id = stored_sets(test_engine, session_id)[0]["id"]
    service.add_set(user.id, session_id, first, WorkoutSetCreate(set_number=2, reps=7))

    with pytest.raises(SetNumberTakenError):
        service.update_set(user.id, session_id, first, set_id, WorkoutSetUpdate(set_number=2))
    # keeping its own number is no conflict
    service.update_set(user.id, session_id, first, set_id, WorkoutSetUpdate(set_number=1, reps=9))
    service.update_set(user.id, session_id, first, set_id, WorkoutSetUpdate(set_number=3))

    assert [(s["set_number"], s["reps"]) for s in stored_sets(test_engine, session_id)] == [
        (2, 7),
        (3, 9),
    ]


# remove_set


def test_remove_set_deletes_only_it(service, user, make_session, test_engine):
    session_id, (first, _) = make_session()
    set_id = stored_sets(test_engine, session_id)[0]["id"]
    service.add_set(user.id, session_id, first, WorkoutSetCreate(set_number=2, reps=7))

    service.remove_set(user.id, session_id, first, set_id)

    assert summary(stored_sets(test_engine, session_id)) == [(2, 7, None, True)]


# rules shared by the three operations


@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED"])
@pytest.mark.parametrize("operation", ["add", "update", "remove"])
def test_finished_session_sets_cannot_be_changed(
    service, user, make_session, test_engine, status, operation
):
    session_id, (first, _) = make_session(status)
    before = stored_session(test_engine, session_id)
    set_id = before["exercises"][0]["sets"][0]["id"]

    with pytest.raises(WorkoutSessionNotEditableError):
        if operation == "add":
            service.add_set(user.id, session_id, first, WorkoutSetCreate(set_number=2, reps=8))
        elif operation == "update":
            service.update_set(user.id, session_id, first, set_id, WorkoutSetUpdate(reps=12))
        else:
            service.remove_set(user.id, session_id, first, set_id)

    assert stored_session(test_engine, session_id) == before


@pytest.mark.parametrize("operation", ["add", "update", "remove"])
def test_sets_of_another_users_session_are_not_found(
    service, user, other_user, make_session, test_engine, operation
):
    session_id, (first, _) = make_session(owner=other_user)
    before = stored_session(test_engine, session_id)
    set_id = before["exercises"][0]["sets"][0]["id"]

    with pytest.raises(WorkoutSessionNotFoundError):
        if operation == "add":
            service.add_set(user.id, session_id, first, WorkoutSetCreate(set_number=2, reps=8))
        elif operation == "update":
            service.update_set(user.id, session_id, first, set_id, WorkoutSetUpdate(reps=1))
        else:
            service.remove_set(user.id, session_id, first, set_id)

    assert stored_session(test_engine, session_id) == before


@pytest.mark.parametrize("operation", ["add", "update", "remove"])
def test_sets_of_another_sessions_exercise_are_not_found(
    service, user, make_session, test_engine, operation
):
    # the user's earlier session: one session is IN_PROGRESS at a time
    other_session_id, (other_first, _) = make_session("COMPLETED")
    session_id, _ = make_session()
    before = stored_session(test_engine, other_session_id)
    set_id = before["exercises"][0]["sets"][0]["id"]

    with pytest.raises(WorkoutSessionExerciseNotFoundError):
        if operation == "add":
            service.add_set(
                user.id, session_id, other_first, WorkoutSetCreate(set_number=2, reps=8)
            )
        elif operation == "update":
            service.update_set(user.id, session_id, other_first, set_id, WorkoutSetUpdate(reps=1))
        else:
            service.remove_set(user.id, session_id, other_first, set_id)

    assert stored_session(test_engine, other_session_id) == before


@pytest.mark.parametrize("operation", ["update", "remove"])
def test_set_of_another_exercise_is_not_found(service, user, make_session, test_engine, operation):
    session_id, (_, second) = make_session()
    before = stored_session(test_engine, session_id)
    set_of_first = before["exercises"][0]["sets"][0]["id"]

    with pytest.raises(WorkoutSetNotFoundError, match=f"session exercise {second} has no set"):
        if operation == "update":
            service.update_set(user.id, session_id, second, set_of_first, WorkoutSetUpdate(reps=1))
        else:
            service.remove_set(user.id, session_id, second, set_of_first)

    assert stored_session(test_engine, session_id) == before


def test_failed_add_rolls_back(service, service_session, user, make_session, test_engine):
    session_id, (first, _) = make_session()
    before = stored_session(test_engine, session_id)
    # beyond the reps column: model_construct skips the schema check, so the
    # insert itself fails in the database
    too_many = WorkoutSetCreate.model_construct(set_number=2, reps=2_147_483_648, completed=True)

    with patch.object(service_session, "rollback", wraps=service_session.rollback) as rollback:
        with pytest.raises(DataError):
            service.add_set(user.id, session_id, first, too_many)

    rollback.assert_called_once()
    assert not service_session.in_transaction()
    assert stored_session(test_engine, session_id) == before
    # the session is usable again after the rollback
    service.add_set(user.id, session_id, first, WorkoutSetCreate(set_number=2, reps=8))
    assert len(stored_sets(test_engine, session_id)) == 2
