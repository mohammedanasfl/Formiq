"""Rules shared by WorkoutPlanService and WorkoutPlanExerciseService."""

from collections import Counter
from datetime import date

from app.models import WorkoutPlan
from app.repositories import ExerciseRepository, WorkoutPlanRepository
from app.schemas import WorkoutPlanExerciseCreate, WorkoutPlanStatus
from app.services.exceptions import (
    ExerciseNotFoundError,
    InactiveExerciseError,
    InvalidStatusTransitionError,
    InvalidWorkoutPlanError,
    WorkoutPlanNotEditableError,
    WorkoutPlanNotFoundError,
)

DRAFT = WorkoutPlanStatus.DRAFT
PLANNED = WorkoutPlanStatus.PLANNED
CANCELLED = WorkoutPlanStatus.CANCELLED

# The statuses that a plan in each status can change to. A PLANNED plan cannot
# go back to DRAFT, and a CANCELLED plan stays CANCELLED.
ALLOWED_STATUS_CHANGES = {
    DRAFT: {DRAFT, PLANNED, CANCELLED},
    PLANNED: {PLANNED, CANCELLED},
    CANCELLED: {CANCELLED},
}

# Fields that are NOT NULL in the tables. The update schemas accept null for
# every field, so an update must not set these to null.
REQUIRED_PLAN_FIELDS = frozenset({"name", "status"})
REQUIRED_PLAN_EXERCISE_FIELDS = frozenset({"exercise_id", "exercise_order", "sets", "reps"})


def get_owned_plan(plans: WorkoutPlanRepository, user_id: int, plan_id: int) -> WorkoutPlan:
    """The user's plan. A plan of another user is treated as missing."""
    plan = plans.get_for_user(user_id, plan_id)
    if plan is None:
        raise WorkoutPlanNotFoundError(f"user {user_id} has no workout plan {plan_id}")
    return plan


def check_exercise_available(exercises: ExerciseRepository, exercise_id: int) -> None:
    """The exercise exists and is active. Retired exercises are not added to plans,
    but plan exercises that already reference one stay as they are."""
    exercise = exercises.get_by_id(exercise_id)
    if exercise is None:
        raise ExerciseNotFoundError(f"exercise {exercise_id} does not exist")
    if not exercise.is_active:
        raise InactiveExerciseError(
            f"exercise {exercise_id} is inactive and cannot be added to a workout plan"
        )


def check_editable(plan: WorkoutPlan) -> None:
    """A CANCELLED plan and its exercises cannot be changed."""
    if plan.status == CANCELLED:
        raise WorkoutPlanNotEditableError(
            f"workout plan {plan.id} is CANCELLED and cannot be changed"
        )


def check_status_change(current: str, new: str) -> None:
    if new not in ALLOWED_STATUS_CHANGES[current]:
        raise InvalidStatusTransitionError(f"a {current} workout plan cannot become {new}")


def check_planned_plan(status: str, scheduled_date: date | None, exercise_count: int) -> None:
    """A PLANNED plan needs a scheduled date and at least one exercise."""
    if status != PLANNED:
        return
    if scheduled_date is None:
        raise InvalidWorkoutPlanError("a PLANNED workout plan needs a scheduled_date")
    if exercise_count == 0:
        raise InvalidWorkoutPlanError("a PLANNED workout plan needs at least one exercise")


def check_no_null_required_fields(changes: dict, required_fields: frozenset[str]) -> None:
    null_fields = sorted(
        field for field, value in changes.items() if value is None and field in required_fields
    )
    if null_fields:
        raise InvalidWorkoutPlanError(f"these fields cannot be null: {', '.join(null_fields)}")


def check_unique_orders(exercises: list[WorkoutPlanExerciseCreate]) -> None:
    counts = Counter(exercise.exercise_order for exercise in exercises)
    repeated = sorted(order for order, count in counts.items() if count > 1)
    if repeated:
        raise InvalidWorkoutPlanError(
            "each exercise_order can be used once in a workout plan: "
            + ", ".join(str(order) for order in repeated)
        )
