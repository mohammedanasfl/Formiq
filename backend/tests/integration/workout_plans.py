"""Helpers for workout plan integration tests."""

from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Exercise, User, WorkoutPlan, WorkoutPlanExercise

DATE = date(2026, 10, 10)


def add_user(session: Session, email: str) -> User:
    user = User(email=email)
    session.add(user)
    session.flush()
    return user


def add_plan(
    session: Session,
    user: User,
    name: str = "Push Day",
    *,
    exercise_ids: list[int] = (),
    status: str = "DRAFT",
    scheduled_date: date | None = None,
    **fields,
) -> WorkoutPlan:
    """A plan with one 3 x 8 exercise per id, at exercise_order 1, 2, ..., flushed only."""
    plan = WorkoutPlan(
        user_id=user.id,
        name=name,
        status=status,
        scheduled_date=scheduled_date,
        exercises=[
            WorkoutPlanExercise(exercise_id=exercise_id, exercise_order=order, sets=3, reps=8)
            for order, exercise_id in enumerate(exercise_ids, start=1)
        ],
        **fields,
    )
    session.add(plan)
    session.flush()
    return plan


def columns(row) -> dict:
    return {column.key: getattr(row, column.key) for column in type(row).__table__.columns}


def stored_plan(engine, plan_id: int) -> dict | None:
    """The plan and its exercises as committed in the database, or None."""
    with Session(engine) as session:
        plan = session.get(WorkoutPlan, plan_id)
        if plan is None:
            return None
        return {**columns(plan), "exercises": [columns(item) for item in plan.exercises]}


def count_rows(engine, model) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model))


def retire_exercise(engine, exercise_id: int) -> None:
    """Marks the catalog exercise inactive and commits, as a catalog change would."""
    with Session(engine) as session:
        session.execute(update(Exercise).where(Exercise.id == exercise_id).values(is_active=False))
        session.commit()
