from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import WorkoutSession, WorkoutSessionExercise

# Loads the exercises of all the sessions a query returns, and their sets, in
# one extra query each, instead of one query per session or exercise.
LOAD_EXERCISES_AND_SETS = (
    selectinload(WorkoutSession.exercises).selectinload(WorkoutSessionExercise.sets),
)


class WorkoutSessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, workout_session: WorkoutSession) -> WorkoutSession:
        self.session.add(workout_session)
        self.session.flush()
        return workout_session

    def get_by_id(self, session_id: int) -> WorkoutSession | None:
        return self.session.get(WorkoutSession, session_id, options=LOAD_EXERCISES_AND_SETS)

    def get_for_user(self, user_id: int, session_id: int) -> WorkoutSession | None:
        """The session, or None if it does not exist or belongs to another user."""
        return self.session.scalars(
            select(WorkoutSession)
            .options(*LOAD_EXERCISES_AND_SETS)
            .where(WorkoutSession.id == session_id, WorkoutSession.user_id == user_id)
        ).one_or_none()

    def find_by_user(
        self, user_id: int, *, status: str | None = None, limit: int | None = None
    ) -> list[WorkoutSession]:
        """The user's sessions, with the given status if it is not None; the most
        recently started first, at most limit of them when it is given."""
        query = (
            select(WorkoutSession)
            .options(*LOAD_EXERCISES_AND_SETS)
            .where(WorkoutSession.user_id == user_id)
            .order_by(WorkoutSession.started_at.desc(), WorkoutSession.id.desc())
        )
        if status is not None:
            query = query.where(WorkoutSession.status == status)
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def get_first_with_status(self, user_id: int, status: str) -> WorkoutSession | None:
        """The user's earliest created session with this status, or None. Its
        exercises are not loaded."""
        return self.session.scalars(
            select(WorkoutSession)
            .where(WorkoutSession.user_id == user_id, WorkoutSession.status == status)
            .order_by(WorkoutSession.id)
            .limit(1)
        ).first()

    def update(self, workout_session: WorkoutSession) -> WorkoutSession:
        self.session.add(workout_session)
        self.session.flush()
        return workout_session

    def delete(self, workout_session: WorkoutSession) -> None:
        self.session.delete(workout_session)
        self.session.flush()
