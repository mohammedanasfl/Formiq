from sqlalchemy.orm import Session

from app.models import WorkoutPlan, WorkoutPlanExercise
from app.repositories import ExerciseRepository, UserRepository, WorkoutPlanRepository
from app.schemas import WorkoutPlanCreate, WorkoutPlanFilters, WorkoutPlanUpdate
from app.services.exceptions import UserNotFoundError, WorkoutPlanNotDeletableError
from app.services.workout_plan_rules import (
    DRAFT,
    PLANNED,
    REQUIRED_PLAN_FIELDS,
    check_editable,
    check_exercise_available,
    check_no_null_required_fields,
    check_planned_plan,
    check_status_change,
    check_unique_orders,
    get_owned_plan,
)


class WorkoutPlanService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.plans = WorkoutPlanRepository(session)
        self.exercises = ExerciseRepository(session)

    def create_plan(self, user_id: int, plan_data: WorkoutPlanCreate) -> WorkoutPlan:
        """Creates the plan and, if given, its exercises, in one transaction."""
        try:
            if self.users.get_by_id(user_id) is None:
                raise UserNotFoundError(f"user {user_id} does not exist")
            check_unique_orders(plan_data.exercises)
            check_planned_plan(
                plan_data.status, plan_data.scheduled_date, len(plan_data.exercises)
            )
            for exercise in plan_data.exercises:
                check_exercise_available(self.exercises, exercise.exercise_id)

            plan = self.plans.create(
                WorkoutPlan(
                    user_id=user_id,
                    **plan_data.model_dump(exclude={"exercises"}),
                    exercises=[
                        WorkoutPlanExercise(**exercise.model_dump())
                        for exercise in plan_data.exercises
                    ],
                )
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(plan)
        return plan

    def list_plans(self, user_id: int, filters: WorkoutPlanFilters) -> list[WorkoutPlan]:
        if self.users.get_by_id(user_id) is None:
            raise UserNotFoundError(f"user {user_id} does not exist")
        return self.plans.find_by_user(
            user_id, status=filters.status, scheduled_date=filters.scheduled_date
        )

    def get_plan(self, user_id: int, plan_id: int) -> WorkoutPlan | None:
        """The user's plan, or None if the user has no plan with this id."""
        return self.plans.get_for_user(user_id, plan_id)

    def get_current_plan(self, user_id: int) -> WorkoutPlan | None:
        """The user's current plan: their PLANNED plan with the latest scheduled
        date (then the most recently created), in the order the plans are
        listed; None if they have no PLANNED plan. DRAFT plans are not ready and
        CANCELLED plans are not to be done, so neither is current."""
        plans = self.plans.find_by_user(user_id, status=PLANNED, limit=1)
        return plans[0] if plans else None

    def update_plan(
        self, user_id: int, plan_id: int, plan_data: WorkoutPlanUpdate
    ) -> WorkoutPlan:
        changes = plan_data.model_dump(exclude_unset=True)
        try:
            plan = get_owned_plan(self.plans, user_id, plan_id)
            # a CANCELLED plan accepts nothing but being cancelled again
            if set(changes) - {"status"}:
                check_editable(plan)
            check_no_null_required_fields(changes, REQUIRED_PLAN_FIELDS)
            status = changes.get("status", plan.status)
            check_status_change(plan.status, status)
            check_planned_plan(
                status, changes.get("scheduled_date", plan.scheduled_date), len(plan.exercises)
            )

            for field, value in changes.items():
                setattr(plan, field, value)
            self.plans.update(plan)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(plan)
        return plan

    def delete_plan(self, user_id: int, plan_id: int) -> None:
        """Deletes a DRAFT plan with its exercises. A PLANNED plan is cancelled
        instead (status CANCELLED), and cancelled plans are kept."""
        try:
            plan = get_owned_plan(self.plans, user_id, plan_id)
            if plan.status != DRAFT:
                raise WorkoutPlanNotDeletableError(
                    f"workout plan {plan.id} is {plan.status}; only DRAFT workout plans "
                    "can be deleted"
                )
            self.plans.delete(plan)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
