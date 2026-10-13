from datetime import date

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
            plan = self.add_plan(user_id, plan_data)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(plan)
        return plan

    def add_plan(self, user_id: int, plan_data: WorkoutPlanCreate) -> WorkoutPlan:
        """Adds the plan and its exercises to the session's transaction, after
        the same checks as create_plan, without committing it: for a caller
        whose own change must be saved with the plan, or not at all
        (app.services.plan_proposal_service)."""
        if self.users.get_by_id(user_id) is None:
            raise UserNotFoundError(f"user {user_id} does not exist")
        check_unique_orders(plan_data.exercises)
        check_planned_plan(plan_data.status, plan_data.scheduled_date, len(plan_data.exercises))
        for exercise in plan_data.exercises:
            check_exercise_available(self.exercises, exercise.exercise_id)

        return self.plans.create(
            WorkoutPlan(
                user_id=user_id,
                **plan_data.model_dump(exclude={"exercises"}),
                exercises=[
                    WorkoutPlanExercise(**exercise.model_dump())
                    for exercise in plan_data.exercises
                ],
            )
        )

    def list_plans(self, user_id: int, filters: WorkoutPlanFilters) -> list[WorkoutPlan]:
        if self.users.get_by_id(user_id) is None:
            raise UserNotFoundError(f"user {user_id} does not exist")
        return self.plans.find_by_user(
            user_id, status=filters.status, scheduled_date=filters.scheduled_date
        )

    def get_plan(self, user_id: int, plan_id: int) -> WorkoutPlan | None:
        """The user's plan, or None if the user has no plan with this id."""
        return self.plans.get_for_user(user_id, plan_id)

    def get_current_plan(self, user_id: int, today: date) -> WorkoutPlan | None:
        """The user's current plan: their PLANNED plan scheduled for today, or
        else the next one scheduled after today, or else the one scheduled most
        recently before today; None if they have no PLANNED plan. Plans on the
        same date go most recently created first. DRAFT plans are not ready and
        CANCELLED plans are not to be done, so neither is current."""
        plan = self.plans.find_first_scheduled_from(user_id, status=PLANNED, scheduled_from=today)
        if plan is not None:
            return plan
        # none today or later: the latest scheduled, as the plans are listed
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
