from sqlalchemy.orm import Session

from app.models import WorkoutPlanExercise
from app.repositories import (
    ExerciseRepository,
    WorkoutPlanExerciseRepository,
    WorkoutPlanRepository,
)
from app.schemas import WorkoutPlanExerciseCreate, WorkoutPlanExerciseUpdate
from app.services.exceptions import ExerciseOrderTakenError, WorkoutPlanExerciseNotFoundError
from app.services.workout_plan_rules import (
    REQUIRED_PLAN_EXERCISE_FIELDS,
    check_editable,
    check_exercise_available,
    check_no_null_required_fields,
    check_planned_plan,
    get_owned_plan,
)


class WorkoutPlanExerciseService:
    """Adds, changes and removes the exercises of a user's workout plan."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.plans = WorkoutPlanRepository(session)
        self.plan_exercises = WorkoutPlanExerciseRepository(session)
        self.exercises = ExerciseRepository(session)

    def add_exercise(
        self, user_id: int, plan_id: int, exercise_data: WorkoutPlanExerciseCreate
    ) -> WorkoutPlanExercise:
        try:
            plan = get_owned_plan(self.plans, user_id, plan_id)
            check_editable(plan)
            check_exercise_available(self.exercises, exercise_data.exercise_id)
            self.check_order_free(plan.id, exercise_data.exercise_order)

            plan_exercise = self.plan_exercises.create(
                WorkoutPlanExercise(workout_plan_id=plan.id, **exercise_data.model_dump())
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(plan_exercise)
        return plan_exercise

    def update_exercise(
        self,
        user_id: int,
        plan_id: int,
        plan_exercise_id: int,
        exercise_data: WorkoutPlanExerciseUpdate,
    ) -> WorkoutPlanExercise:
        changes = exercise_data.model_dump(exclude_unset=True)
        try:
            plan = get_owned_plan(self.plans, user_id, plan_id)
            plan_exercise = self.get_plan_exercise(plan.id, plan_exercise_id)
            check_editable(plan)
            check_no_null_required_fields(changes, REQUIRED_PLAN_EXERCISE_FIELDS)
            if changes.get("exercise_id", plan_exercise.exercise_id) != plan_exercise.exercise_id:
                check_exercise_available(self.exercises, changes["exercise_id"])
            if (
                changes.get("exercise_order", plan_exercise.exercise_order)
                != plan_exercise.exercise_order
            ):
                self.check_order_free(plan.id, changes["exercise_order"])

            for field, value in changes.items():
                setattr(plan_exercise, field, value)
            self.plan_exercises.update(plan_exercise)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(plan_exercise)
        return plan_exercise

    def remove_exercise(self, user_id: int, plan_id: int, plan_exercise_id: int) -> None:
        """Deletes the exercise from the plan. The other exercises keep their order."""
        try:
            plan = get_owned_plan(self.plans, user_id, plan_id)
            plan_exercise = self.get_plan_exercise(plan.id, plan_exercise_id)
            check_editable(plan)
            # a PLANNED plan must keep at least one exercise
            check_planned_plan(plan.status, plan.scheduled_date, len(plan.exercises) - 1)

            self.plan_exercises.delete(plan_exercise)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def get_plan_exercise(self, plan_id: int, plan_exercise_id: int) -> WorkoutPlanExercise:
        plan_exercise = self.plan_exercises.get_for_plan(plan_id, plan_exercise_id)
        if plan_exercise is None:
            raise WorkoutPlanExerciseNotFoundError(
                f"workout plan {plan_id} has no exercise {plan_exercise_id}"
            )
        return plan_exercise

    def check_order_free(self, plan_id: int, exercise_order: int) -> None:
        if self.plan_exercises.get_by_order(plan_id, exercise_order) is not None:
            raise ExerciseOrderTakenError(
                f"workout plan {plan_id} already has an exercise at exercise_order "
                f"{exercise_order}"
            )
