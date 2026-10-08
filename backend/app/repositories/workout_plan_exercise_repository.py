from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorkoutPlanExercise


class WorkoutPlanExerciseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, plan_exercise: WorkoutPlanExercise) -> WorkoutPlanExercise:
        self.session.add(plan_exercise)
        self.session.flush()
        return plan_exercise

    def get_for_plan(
        self, workout_plan_id: int, plan_exercise_id: int
    ) -> WorkoutPlanExercise | None:
        """The plan exercise, or None if it does not exist or belongs to another plan."""
        return self.session.scalars(
            select(WorkoutPlanExercise).where(
                WorkoutPlanExercise.id == plan_exercise_id,
                WorkoutPlanExercise.workout_plan_id == workout_plan_id,
            )
        ).one_or_none()

    def get_by_order(self, workout_plan_id: int, exercise_order: int) -> WorkoutPlanExercise | None:
        return self.session.scalars(
            select(WorkoutPlanExercise).where(
                WorkoutPlanExercise.workout_plan_id == workout_plan_id,
                WorkoutPlanExercise.exercise_order == exercise_order,
            )
        ).one_or_none()

    def update(self, plan_exercise: WorkoutPlanExercise) -> WorkoutPlanExercise:
        self.session.add(plan_exercise)
        self.session.flush()
        return plan_exercise

    def delete(self, plan_exercise: WorkoutPlanExercise) -> None:
        self.session.delete(plan_exercise)
        self.session.flush()
