from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import WorkoutPlan

# Loads the exercises of all the plans a query returns in one extra query,
# instead of one query per plan.
LOAD_EXERCISES = (selectinload(WorkoutPlan.exercises),)


class WorkoutPlanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, plan: WorkoutPlan) -> WorkoutPlan:
        self.session.add(plan)
        self.session.flush()
        return plan

    def get_by_id(self, plan_id: int) -> WorkoutPlan | None:
        return self.session.get(WorkoutPlan, plan_id, options=LOAD_EXERCISES)

    def get_for_user(self, user_id: int, plan_id: int) -> WorkoutPlan | None:
        """The plan, or None if it does not exist or belongs to another user."""
        return self.session.scalars(
            select(WorkoutPlan)
            .options(*LOAD_EXERCISES)
            .where(WorkoutPlan.id == plan_id, WorkoutPlan.user_id == user_id)
        ).one_or_none()

    def find_by_user(
        self,
        user_id: int,
        *,
        status: str | None = None,
        scheduled_date: date | None = None,
        limit: int | None = None,
    ) -> list[WorkoutPlan]:
        """The user's plans matching every value that is not None, at most limit
        of them when it is given.

        Latest scheduled date first and plans without a date last, then the
        most recently created first.
        """
        query = (
            select(WorkoutPlan)
            .options(*LOAD_EXERCISES)
            .where(WorkoutPlan.user_id == user_id)
            .order_by(
                WorkoutPlan.scheduled_date.desc().nulls_last(),
                WorkoutPlan.created_at.desc(),
                WorkoutPlan.id.desc(),
            )
        )
        if status is not None:
            query = query.where(WorkoutPlan.status == status)
        if scheduled_date is not None:
            query = query.where(WorkoutPlan.scheduled_date == scheduled_date)
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def update(self, plan: WorkoutPlan) -> WorkoutPlan:
        self.session.add(plan)
        self.session.flush()
        return plan

    def delete(self, plan: WorkoutPlan) -> None:
        self.session.delete(plan)
        self.session.flush()
