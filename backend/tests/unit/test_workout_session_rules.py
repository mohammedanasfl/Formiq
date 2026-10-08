import pytest

from app.models import WorkoutSession, WorkoutSessionExercise, WorkoutSet
from app.schemas import WorkoutSessionExerciseUpdate, WorkoutSessionUpdate, WorkoutSetUpdate
from app.services.exceptions import (
    InvalidSessionStatusTransitionError,
    InvalidWorkoutSessionError,
    WorkoutSessionNotEditableError,
)
from app.services.workout_session_rules import (
    REQUIRED_SESSION_EXERCISE_FIELDS,
    REQUIRED_SESSION_FIELDS,
    REQUIRED_SET_FIELDS,
    check_completed_session,
    check_in_progress,
    check_no_null_required_fields,
    check_plan_exercise,
    check_status_change,
)

STATUSES = ["IN_PROGRESS", "COMPLETED", "CANCELLED"]
ALLOWED = {
    ("IN_PROGRESS", "IN_PROGRESS"),
    ("IN_PROGRESS", "COMPLETED"),
    ("IN_PROGRESS", "CANCELLED"),
    ("COMPLETED", "COMPLETED"),
    ("CANCELLED", "CANCELLED"),
}


def not_null_columns(model):
    return {column.name for column in model.__table__.columns if not column.nullable}


@pytest.mark.parametrize(
    ("required", "model", "schema"),
    [
        (REQUIRED_SESSION_FIELDS, WorkoutSession, WorkoutSessionUpdate),
        (REQUIRED_SESSION_EXERCISE_FIELDS, WorkoutSessionExercise, WorkoutSessionExerciseUpdate),
        (REQUIRED_SET_FIELDS, WorkoutSet, WorkoutSetUpdate),
    ],
)
def test_required_fields_are_the_not_null_updatable_columns(required, model, schema):
    assert required == not_null_columns(model) & set(schema.model_fields)


@pytest.mark.parametrize("current", STATUSES)
@pytest.mark.parametrize("new", STATUSES)
def test_status_changes(current, new):
    if (current, new) in ALLOWED:
        check_status_change(current, new)
    else:
        with pytest.raises(
            InvalidSessionStatusTransitionError, match=f"a {current} .* cannot become {new}"
        ):
            check_status_change(current, new)


def test_only_an_in_progress_session_can_be_changed():
    check_in_progress(WorkoutSession(id=1, status="IN_PROGRESS"))

    for status in ["COMPLETED", "CANCELLED"]:
        with pytest.raises(WorkoutSessionNotEditableError, match=f"is {status}"):
            check_in_progress(WorkoutSession(id=1, status=status))


def test_completed_session_needs_an_exercise():
    check_completed_session("COMPLETED", 1)
    check_completed_session("IN_PROGRESS", 0)
    check_completed_session("CANCELLED", 0)

    with pytest.raises(InvalidWorkoutSessionError, match="needs at least one exercise"):
        check_completed_session("COMPLETED", 0)


def test_null_is_rejected_only_for_required_fields():
    check_no_null_required_fields({"weight_kg": None, "rpe": None}, REQUIRED_SET_FIELDS)

    with pytest.raises(InvalidWorkoutSessionError, match="cannot be null: completed, reps"):
        check_no_null_required_fields({"reps": None, "completed": None}, REQUIRED_SET_FIELDS)


class PlanExercises:
    """Stands in for WorkoutPlanExerciseRepository: plan 10 has plan exercise 100."""

    def get_for_plan(self, plan_id, plan_exercise_id):
        return object() if (plan_id, plan_exercise_id) == (10, 100) else None


def test_plan_exercise_must_belong_to_the_sessions_plan():
    planned = WorkoutSession(id=1, workout_plan_id=10)
    manual = WorkoutSession(id=2, workout_plan_id=None)

    check_plan_exercise(PlanExercises(), planned, 100)
    check_plan_exercise(PlanExercises(), planned, None)
    check_plan_exercise(PlanExercises(), manual, None)
    with pytest.raises(InvalidWorkoutSessionError, match="workout plan 10 has no exercise 200"):
        check_plan_exercise(PlanExercises(), planned, 200)
    with pytest.raises(InvalidWorkoutSessionError, match="has no workout plan"):
        check_plan_exercise(PlanExercises(), manual, 100)
