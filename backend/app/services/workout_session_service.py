from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import WorkoutSession
from app.repositories import UserRepository, WorkoutPlanRepository, WorkoutSessionRepository
from app.schemas import WorkoutSessionCreate, WorkoutSessionFilters, WorkoutSessionUpdate
from app.services.exceptions import (
    InvalidWorkoutSessionError,
    SessionAlreadyInProgressError,
    UserNotFoundError,
    WorkoutSessionNotDeletableError,
)
from app.services.workout_plan_rules import PLANNED
from app.services.workout_session_rules import (
    COMPLETED,
    IN_PROGRESS,
    REQUIRED_SESSION_FIELDS,
    check_completed_session,
    check_in_progress,
    check_no_null_required_fields,
    check_status_change,
    get_owned_session,
)


class WorkoutSessionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.plans = WorkoutPlanRepository(session)
        self.sessions = WorkoutSessionRepository(session)

    def create_session(
        self, user_id: int, session_data: WorkoutSessionCreate
    ) -> WorkoutSession:
        """Starts an IN_PROGRESS session now, from one of the user's PLANNED plans
        or as a manual workout without one. The database sets started_at. A user
        has at most one IN_PROGRESS session."""
        try:
            if self.users.get_by_id(user_id) is None:
                raise UserNotFoundError(f"user {user_id} does not exist")
            plan_id = session_data.workout_plan_id
            if plan_id is not None:
                plan = self.plans.get_for_user(user_id, plan_id)
                if plan is None:
                    raise InvalidWorkoutSessionError(
                        f"user {user_id} has no workout plan {plan_id}"
                    )
                # a DRAFT plan is not ready yet, and a CANCELLED plan is not to be done
                if plan.status != PLANNED:
                    raise InvalidWorkoutSessionError(
                        f"workout plan {plan_id} is {plan.status}; only PLANNED workout "
                        "plans can start a workout session"
                    )
            # one session at a time, manual or planned: the user completes or
            # cancels the running one first
            in_progress = self.sessions.get_first_with_status(user_id, IN_PROGRESS)
            if in_progress is not None:
                raise SessionAlreadyInProgressError(
                    f"user {user_id} already has workout session {in_progress.id} "
                    "IN_PROGRESS; complete or cancel it first"
                )

            workout_session = self.sessions.create(
                WorkoutSession(user_id=user_id, status=IN_PROGRESS, **session_data.model_dump())
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(workout_session)
        return workout_session

    def list_sessions(self, user_id: int, filters: WorkoutSessionFilters) -> list[WorkoutSession]:
        if self.users.get_by_id(user_id) is None:
            raise UserNotFoundError(f"user {user_id} does not exist")
        return self.sessions.find_by_user(user_id, status=filters.status)

    def get_session(self, user_id: int, session_id: int) -> WorkoutSession | None:
        """The user's session, or None if the user has no session with this id."""
        return self.sessions.get_for_user(user_id, session_id)

    def update_session(
        self, user_id: int, session_id: int, session_data: WorkoutSessionUpdate
    ) -> WorkoutSession:
        changes = session_data.model_dump(exclude_unset=True)
        try:
            workout_session = get_owned_session(self.sessions, user_id, session_id)
            # a finished session accepts nothing but its own status again
            if set(changes) - {"status"}:
                check_in_progress(workout_session)
            check_no_null_required_fields(changes, REQUIRED_SESSION_FIELDS)
            status = changes.get("status", workout_session.status)
            check_status_change(workout_session.status, status)
            check_completed_session(status, len(workout_session.exercises))

            if status == COMPLETED and workout_session.status != COMPLETED:
                # the database clock, like started_at
                workout_session.completed_at = func.now()
            for field, value in changes.items():
                setattr(workout_session, field, value)
            self.sessions.update(workout_session)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(workout_session)
        return workout_session

    def delete_session(self, user_id: int, session_id: int) -> None:
        """Deletes an IN_PROGRESS session with its exercises and sets. COMPLETED
        and CANCELLED sessions are history and are kept."""
        try:
            workout_session = get_owned_session(self.sessions, user_id, session_id)
            if workout_session.status != IN_PROGRESS:
                raise WorkoutSessionNotDeletableError(
                    f"workout session {workout_session.id} is {workout_session.status}; "
                    "only IN_PROGRESS workout sessions can be deleted"
                )
            self.sessions.delete(workout_session)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
