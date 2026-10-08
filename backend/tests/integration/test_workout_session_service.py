"""Integration tests for WorkoutSessionService, and for the session history
surviving later changes to plans and exercises.

They require the local PostgreSQL container to be running (test database).
Services commit, so the service_session fixture empties the user, workout plan
and workout session tables before and after each test.
"""

from unittest.mock import patch

import pytest
from sqlalchemy.exc import DataError

from app.models import WorkoutSession
from app.schemas import (
    UserCreate,
    WorkoutPlanCreate,
    WorkoutPlanExerciseCreate,
    WorkoutPlanExerciseUpdate,
    WorkoutPlanUpdate,
    WorkoutSessionCreate,
    WorkoutSessionExerciseCreate,
    WorkoutSessionFilters,
    WorkoutSessionUpdate,
    WorkoutSetCreate,
)
from app.services import (
    UserService,
    WorkoutPlanExerciseService,
    WorkoutPlanService,
    WorkoutSessionExerciseService,
    WorkoutSessionService,
    WorkoutSetService,
)
from app.services.exceptions import (
    InvalidSessionStatusTransitionError,
    InvalidWorkoutSessionError,
    SessionAlreadyInProgressError,
    UserNotFoundError,
    WorkoutSessionNotDeletableError,
    WorkoutSessionNotEditableError,
    WorkoutSessionNotFoundError,
)
from tests.integration.workout_plans import DATE, count_rows, retire_exercise
from tests.integration.workout_sessions import stored_session


@pytest.fixture
def service(service_session):
    return WorkoutSessionService(service_session)


@pytest.fixture
def user(service_session):
    return UserService(service_session).create_user(UserCreate(email="session-service@example.com"))


@pytest.fixture
def other_user(service_session):
    return UserService(service_session).create_user(UserCreate(email="session-other@example.com"))


@pytest.fixture
def bench_press(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Bench Press"]


@pytest.fixture
def squat(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Back Squat"]


@pytest.fixture
def make_plan(service_session, user, bench_press):
    """Creates a committed plan of the user with a bench press at exercise_order 1."""

    def make(status="PLANNED", owner=None):
        return WorkoutPlanService(service_session).create_plan(
            (owner or user).id,
            WorkoutPlanCreate(
                name="Push Day",
                status=status,
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
    """Creates a committed session of the user in the given status, by default
    with one bench press of one set."""

    def make(status="IN_PROGRESS", *, owner=None, with_exercise=True, workout_plan_id=None):
        owner_id = (owner or user).id
        workout_session = service.create_session(
            owner_id, WorkoutSessionCreate(workout_plan_id=workout_plan_id)
        )
        if with_exercise:
            session_exercise = WorkoutSessionExerciseService(service_session).add_exercise(
                owner_id,
                workout_session.id,
                WorkoutSessionExerciseCreate(exercise_id=bench_press, exercise_order=1),
            )
            WorkoutSetService(service_session).add_set(
                owner_id,
                workout_session.id,
                session_exercise.id,
                WorkoutSetCreate(set_number=1, reps=8, weight_kg=50.0),
            )
        if status != "IN_PROGRESS":
            workout_session = service.update_session(
                owner_id, workout_session.id, WorkoutSessionUpdate(status=status)
            )
        return workout_session

    return make


# create_session


def test_create_manual_session(service, user, test_engine):
    workout_session = service.create_session(user.id, WorkoutSessionCreate(notes="Quick one"))

    stored = stored_session(test_engine, workout_session.id)  # committed
    assert (stored["user_id"], stored["status"], stored["workout_plan_id"]) == (
        user.id,
        "IN_PROGRESS",
        None,
    )
    assert (stored["notes"], stored["completed_at"], stored["exercises"]) == ("Quick one", None, [])
    # started_at comes from the database clock, in the session's own transaction
    assert stored["started_at"] == stored["created_at"]


def test_create_session_from_the_users_planned_plan(service, user, make_plan, test_engine):
    plan = make_plan("PLANNED")

    workout_session = service.create_session(user.id, WorkoutSessionCreate(workout_plan_id=plan.id))

    assert stored_session(test_engine, workout_session.id)["workout_plan_id"] == plan.id


def test_create_session_requires_an_existing_user(service, test_engine):
    with pytest.raises(UserNotFoundError):
        service.create_session(-1, WorkoutSessionCreate())

    assert count_rows(test_engine, WorkoutSession) == 0


@pytest.mark.parametrize("plan_owner", ["other user", "missing"])
def test_create_session_needs_one_of_the_users_plans(
    service, user, other_user, make_plan, test_engine, plan_owner
):
    if plan_owner == "other user":
        plan_id = make_plan("PLANNED", owner=other_user).id
    else:
        plan_id = 2_147_483_647

    with pytest.raises(InvalidWorkoutSessionError, match=f"user {user.id} has no workout plan"):
        service.create_session(user.id, WorkoutSessionCreate(workout_plan_id=plan_id))

    assert count_rows(test_engine, WorkoutSession) == 0


@pytest.mark.parametrize("plan_status", ["DRAFT", "CANCELLED"])
def test_create_session_needs_a_planned_plan(
    service, service_session, user, make_plan, test_engine, plan_status
):
    if plan_status == "DRAFT":
        plan = make_plan("DRAFT")
    else:
        plan = WorkoutPlanService(service_session).update_plan(
            user.id, make_plan("PLANNED").id, WorkoutPlanUpdate(status="CANCELLED")
        )

    with pytest.raises(
        InvalidWorkoutSessionError,
        match=f"workout plan {plan.id} is {plan_status}; only PLANNED workout plans",
    ):
        service.create_session(user.id, WorkoutSessionCreate(workout_plan_id=plan.id))

    assert count_rows(test_engine, WorkoutSession) == 0


@pytest.mark.parametrize("second", ["manual", "planned"])
@pytest.mark.parametrize("first", ["manual", "planned"])
def test_create_session_rejects_a_second_session_in_progress(
    service, user, make_plan, test_engine, first, second
):
    plan_id = make_plan().id
    running = service.create_session(
        user.id, WorkoutSessionCreate(workout_plan_id=plan_id if first == "planned" else None)
    )
    before = stored_session(test_engine, running.id)

    with pytest.raises(
        SessionAlreadyInProgressError,
        match=f"user {user.id} already has workout session {running.id} IN_PROGRESS",
    ):
        service.create_session(
            user.id, WorkoutSessionCreate(workout_plan_id=plan_id if second == "planned" else None)
        )

    assert count_rows(test_engine, WorkoutSession) == 1
    assert stored_session(test_engine, running.id) == before


@pytest.mark.parametrize("new", ["manual", "planned"])
@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED"])
def test_finishing_the_session_in_progress_allows_another(
    service, user, make_plan, make_session, status, new
):
    finished = make_session(status)
    plan_id = make_plan().id if new == "planned" else None

    started = service.create_session(user.id, WorkoutSessionCreate(workout_plan_id=plan_id))

    assert {s.id: s.status for s in service.list_sessions(user.id, WorkoutSessionFilters())} == {
        finished.id: status,
        started.id: "IN_PROGRESS",
    }


def test_another_users_session_in_progress_does_not_block(service, user, other_user, make_session):
    make_session(owner=other_user)

    assert service.create_session(user.id, WorkoutSessionCreate()).status == "IN_PROGRESS"


# list_sessions and get_session


def test_list_sessions_returns_only_the_users_sessions(service, user, other_user, make_session):
    completed = make_session("COMPLETED")
    in_progress = make_session()
    make_session(owner=other_user)

    assert [s.id for s in service.list_sessions(user.id, WorkoutSessionFilters())] == [
        in_progress.id,
        completed.id,
    ]
    assert [
        s.id for s in service.list_sessions(user.id, WorkoutSessionFilters(status="COMPLETED"))
    ] == [completed.id]


def test_list_sessions_of_a_missing_user_is_an_error(service):
    with pytest.raises(UserNotFoundError):
        service.list_sessions(-1, WorkoutSessionFilters())


def test_get_session_returns_only_the_users_session(service, user, other_user, make_session):
    workout_session = make_session()

    assert service.get_session(user.id, workout_session.id).id == workout_session.id
    assert service.get_session(other_user.id, workout_session.id) is None
    assert service.get_session(user.id, -1) is None


# update_session


def test_update_notes_of_an_in_progress_session(service, user, make_session, test_engine):
    workout_session = make_session()

    service.update_session(user.id, workout_session.id, WorkoutSessionUpdate(notes="Gym was busy"))

    stored = stored_session(test_engine, workout_session.id)
    assert (stored["notes"], stored["status"]) == ("Gym was busy", "IN_PROGRESS")


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("IN_PROGRESS", "IN_PROGRESS"),
        ("IN_PROGRESS", "COMPLETED"),
        ("IN_PROGRESS", "CANCELLED"),
        ("COMPLETED", "COMPLETED"),
        ("CANCELLED", "CANCELLED"),
    ],
)
def test_allowed_status_changes(service, user, make_session, test_engine, current, new):
    workout_session = make_session(current)

    service.update_session(user.id, workout_session.id, WorkoutSessionUpdate(status=new))

    assert stored_session(test_engine, workout_session.id)["status"] == new


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("COMPLETED", "IN_PROGRESS"),
        ("COMPLETED", "CANCELLED"),
        ("CANCELLED", "IN_PROGRESS"),
        ("CANCELLED", "COMPLETED"),
    ],
)
def test_finished_sessions_keep_their_status(
    service, user, make_session, test_engine, current, new
):
    workout_session = make_session(current)
    before = stored_session(test_engine, workout_session.id)

    with pytest.raises(InvalidSessionStatusTransitionError):
        service.update_session(user.id, workout_session.id, WorkoutSessionUpdate(status=new))

    assert stored_session(test_engine, workout_session.id) == before


def test_completing_sets_completed_at_once(service, user, make_session, test_engine):
    workout_session = make_session()

    service.update_session(user.id, workout_session.id, WorkoutSessionUpdate(status="COMPLETED"))
    completed = stored_session(test_engine, workout_session.id)
    service.update_session(user.id, workout_session.id, WorkoutSessionUpdate(status="COMPLETED"))

    assert completed["completed_at"] >= completed["started_at"]
    assert (
        stored_session(test_engine, workout_session.id)["completed_at"] == completed["completed_at"]
    )


def test_cancelling_leaves_completed_at_empty(service, user, make_session, test_engine):
    workout_session = make_session()

    service.update_session(user.id, workout_session.id, WorkoutSessionUpdate(status="CANCELLED"))

    stored = stored_session(test_engine, workout_session.id)
    assert (stored["status"], stored["completed_at"]) == ("CANCELLED", None)


def test_completing_needs_an_exercise(service, user, make_session, test_engine):
    workout_session = make_session(with_exercise=False)

    with pytest.raises(InvalidWorkoutSessionError, match="needs at least one exercise"):
        service.update_session(
            user.id, workout_session.id, WorkoutSessionUpdate(status="COMPLETED")
        )

    assert stored_session(test_engine, workout_session.id)["status"] == "IN_PROGRESS"
    # an empty session can still be cancelled
    service.update_session(user.id, workout_session.id, WorkoutSessionUpdate(status="CANCELLED"))


@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED"])
@pytest.mark.parametrize(
    "changes", [{"notes": "Rewritten"}, {"notes": None}, {"status": "COMPLETED", "notes": "x"}]
)
def test_finished_session_cannot_be_edited(
    service, user, make_session, test_engine, status, changes
):
    workout_session = make_session(status)
    before = stored_session(test_engine, workout_session.id)

    with pytest.raises(WorkoutSessionNotEditableError, match=f"is {status}"):
        service.update_session(user.id, workout_session.id, WorkoutSessionUpdate(**changes))

    assert stored_session(test_engine, workout_session.id) == before


def test_update_rejects_null_status(service, user, make_session):
    workout_session = make_session()

    with pytest.raises(InvalidWorkoutSessionError, match="cannot be null: status"):
        service.update_session(user.id, workout_session.id, WorkoutSessionUpdate(status=None))


# delete_session


def test_delete_in_progress_session_with_its_exercises_and_sets(
    service, user, make_session, test_engine
):
    workout_session = make_session()

    service.delete_session(user.id, workout_session.id)

    assert stored_session(test_engine, workout_session.id) is None


@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED"])
def test_finished_sessions_cannot_be_deleted(service, user, make_session, test_engine, status):
    workout_session = make_session(status)
    before = stored_session(test_engine, workout_session.id)

    with pytest.raises(WorkoutSessionNotDeletableError, match="only IN_PROGRESS"):
        service.delete_session(user.id, workout_session.id)

    assert stored_session(test_engine, workout_session.id) == before


# ownership and transactions


def test_another_users_session_cannot_be_changed_or_deleted(
    service, user, other_user, make_session, test_engine
):
    workout_session = make_session(owner=other_user)
    before = stored_session(test_engine, workout_session.id)

    with pytest.raises(WorkoutSessionNotFoundError, match=f"user {user.id} has no workout session"):
        service.update_session(user.id, workout_session.id, WorkoutSessionUpdate(notes="Mine"))
    with pytest.raises(WorkoutSessionNotFoundError):
        service.delete_session(user.id, workout_session.id)

    assert stored_session(test_engine, workout_session.id) == before


def test_failed_create_rolls_back(service, service_session, user, test_engine):
    # beyond the integer column: model_construct skips the schema check, so the
    # plan lookup itself fails in the database
    too_large = WorkoutSessionCreate.model_construct(workout_plan_id=2_147_483_648, notes=None)

    with patch.object(service_session, "rollback", wraps=service_session.rollback) as rollback:
        with pytest.raises(DataError):
            service.create_session(user.id, too_large)

    rollback.assert_called_once()
    assert not service_session.in_transaction()
    assert count_rows(test_engine, WorkoutSession) == 0
    # the session is usable again after the rollback
    assert service.create_session(user.id, WorkoutSessionCreate()).id is not None


# history survives later changes to plans and exercises


@pytest.fixture
def planned_history(service_session, service, user, make_plan, bench_press):
    """A COMPLETED session done from a PLANNED plan: its bench press, linked to
    the planned one, with one set. Returns the plan and the session."""
    plan = make_plan()
    workout_session = service.create_session(user.id, WorkoutSessionCreate(workout_plan_id=plan.id))
    session_exercise = WorkoutSessionExerciseService(service_session).add_exercise(
        user.id,
        workout_session.id,
        WorkoutSessionExerciseCreate(
            exercise_id=bench_press, exercise_order=1, plan_exercise_id=plan.exercises[0].id
        ),
    )
    WorkoutSetService(service_session).add_set(
        user.id, workout_session.id, session_exercise.id, WorkoutSetCreate(set_number=1, reps=8)
    )
    service.update_session(user.id, workout_session.id, WorkoutSessionUpdate(status="COMPLETED"))
    return plan, workout_session


def without_links(stored):
    """The stored session without its links to the plan, and timestamps."""
    return {
        **{
            key: value
            for key, value in stored.items()
            if key not in {"workout_plan_id", "updated_at"}
        },
        "exercises": [
            {key: value for key, value in item.items() if key != "plan_exercise_id"}
            for item in stored["exercises"]
        ],
    }


def test_history_survives_deleting_the_plan(
    service_session, service, user, planned_history, test_engine
):
    plan, workout_session = planned_history
    before = stored_session(test_engine, workout_session.id)

    # Through the services only DRAFT plans can be deleted, and only PLANNED
    # plans start sessions, so the plan is deleted in the database itself.
    service_session.delete(plan)
    service_session.commit()

    after = stored_session(test_engine, workout_session.id)
    assert after["workout_plan_id"] is None
    assert [item["plan_exercise_id"] for item in after["exercises"]] == [None]
    assert without_links(after) == without_links(before)
    assert service.get_session(user.id, workout_session.id).status == "COMPLETED"


def test_history_survives_removing_the_planned_exercise(
    service_session, user, planned_history, squat, test_engine
):
    plan, workout_session = planned_history
    # a PLANNED plan keeps at least one exercise
    WorkoutPlanExerciseService(service_session).add_exercise(
        user.id,
        plan.id,
        WorkoutPlanExerciseCreate(exercise_id=squat, exercise_order=2, sets=3, reps=5),
    )
    before = stored_session(test_engine, workout_session.id)

    WorkoutPlanExerciseService(service_session).remove_exercise(
        user.id, plan.id, before["exercises"][0]["plan_exercise_id"]
    )

    after = stored_session(test_engine, workout_session.id)
    assert after["workout_plan_id"] == plan.id
    assert [item["plan_exercise_id"] for item in after["exercises"]] == [None]
    assert without_links(after) == without_links(before)


def test_history_ignores_later_plan_changes(service_session, user, planned_history, test_engine):
    plan, workout_session = planned_history
    before = stored_session(test_engine, workout_session.id)

    WorkoutPlanExerciseService(service_session).update_exercise(
        user.id, plan.id, plan.exercises[0].id, WorkoutPlanExerciseUpdate(reps=12)
    )
    WorkoutPlanService(service_session).update_plan(
        user.id, plan.id, WorkoutPlanUpdate(status="CANCELLED")
    )

    assert stored_session(test_engine, workout_session.id) == before


def test_history_survives_retiring_the_exercise(
    service_session, service, user, retirable_exercise_id, test_engine
):
    workout_session = service.create_session(user.id, WorkoutSessionCreate())
    WorkoutSessionExerciseService(service_session).add_exercise(
        user.id,
        workout_session.id,
        WorkoutSessionExerciseCreate(exercise_id=retirable_exercise_id, exercise_order=1),
    )
    service.update_session(user.id, workout_session.id, WorkoutSessionUpdate(status="COMPLETED"))
    before = stored_session(test_engine, workout_session.id)

    retire_exercise(test_engine, retirable_exercise_id)

    assert stored_session(test_engine, workout_session.id) == before
    read = service.get_session(user.id, workout_session.id)
    assert [item.exercise_id for item in read.exercises] == [retirable_exercise_id]
