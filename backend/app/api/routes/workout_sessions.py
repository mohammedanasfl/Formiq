from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.api.dependencies import DbSession
from app.api.routes.users import UserId
from app.schemas import (
    WorkoutSessionCreate,
    WorkoutSessionExerciseCreate,
    WorkoutSessionExerciseResponse,
    WorkoutSessionExerciseUpdate,
    WorkoutSessionFilters,
    WorkoutSessionResponse,
    WorkoutSessionUpdate,
    WorkoutSetCreate,
    WorkoutSetResponse,
    WorkoutSetUpdate,
)
from app.services import WorkoutSessionExerciseService, WorkoutSessionService, WorkoutSetService
from app.services.exceptions import (
    ExerciseNotFoundError,
    InactiveExerciseError,
    InvalidWorkoutSessionError,
    UserNotFoundError,
    WorkoutSessionConflictError,
    WorkoutSessionExerciseNotFoundError,
    WorkoutSessionNotFoundError,
    WorkoutSetNotFoundError,
)

# Each route is scoped to the user in the path: another user's session is not found.
router = APIRouter(prefix="/users/{user_id}/workout-sessions", tags=["workout sessions"])

# Like users.id, these are PostgreSQL integer columns: IDs outside their range
# would fail in the database, so they are rejected with 422.
SessionId = Annotated[int, Path(ge=1, le=2_147_483_647)]
SessionExerciseId = Annotated[int, Path(ge=1, le=2_147_483_647)]
SetId = Annotated[int, Path(ge=1, le=2_147_483_647)]

# service errors about the request body
INVALID_REQUEST_ERRORS = (InvalidWorkoutSessionError, ExerciseNotFoundError, InactiveExerciseError)


@router.post("", response_model=WorkoutSessionResponse, status_code=status.HTTP_201_CREATED)
def create_workout_session(user_id: UserId, session_data: WorkoutSessionCreate, db: DbSession):
    try:
        return WorkoutSessionService(db).create_session(user_id, session_data)
    except UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except InvalidWorkoutSessionError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except WorkoutSessionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("", response_model=list[WorkoutSessionResponse])
def list_workout_sessions(
    user_id: UserId, filters: Annotated[WorkoutSessionFilters, Query()], db: DbSession
):
    try:
        return WorkoutSessionService(db).list_sessions(user_id, filters)
    except UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/{session_id}", response_model=WorkoutSessionResponse)
def get_workout_session(user_id: UserId, session_id: SessionId, db: DbSession):
    workout_session = WorkoutSessionService(db).get_session(user_id, session_id)
    if workout_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"user {user_id} has no workout session {session_id}",
        )
    return workout_session


@router.patch("/{session_id}", response_model=WorkoutSessionResponse)
def update_workout_session(
    user_id: UserId, session_id: SessionId, session_data: WorkoutSessionUpdate, db: DbSession
):
    try:
        return WorkoutSessionService(db).update_session(user_id, session_id, session_data)
    except WorkoutSessionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except InvalidWorkoutSessionError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except WorkoutSessionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workout_session(user_id: UserId, session_id: SessionId, db: DbSession):
    try:
        WorkoutSessionService(db).delete_session(user_id, session_id)
    except WorkoutSessionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except WorkoutSessionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/{session_id}/exercises",
    response_model=WorkoutSessionExerciseResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_workout_session_exercise(
    user_id: UserId,
    session_id: SessionId,
    exercise_data: WorkoutSessionExerciseCreate,
    db: DbSession,
):
    try:
        return WorkoutSessionExerciseService(db).add_exercise(user_id, session_id, exercise_data)
    except WorkoutSessionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except INVALID_REQUEST_ERRORS as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except WorkoutSessionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.patch(
    "/{session_id}/exercises/{session_exercise_id}",
    response_model=WorkoutSessionExerciseResponse,
)
def update_workout_session_exercise(
    user_id: UserId,
    session_id: SessionId,
    session_exercise_id: SessionExerciseId,
    exercise_data: WorkoutSessionExerciseUpdate,
    db: DbSession,
):
    try:
        return WorkoutSessionExerciseService(db).update_exercise(
            user_id, session_id, session_exercise_id, exercise_data
        )
    except (WorkoutSessionNotFoundError, WorkoutSessionExerciseNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except INVALID_REQUEST_ERRORS as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except WorkoutSessionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.delete(
    "/{session_id}/exercises/{session_exercise_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_workout_session_exercise(
    user_id: UserId, session_id: SessionId, session_exercise_id: SessionExerciseId, db: DbSession
):
    try:
        WorkoutSessionExerciseService(db).remove_exercise(user_id, session_id, session_exercise_id)
    except (WorkoutSessionNotFoundError, WorkoutSessionExerciseNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except WorkoutSessionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/{session_id}/exercises/{session_exercise_id}/sets",
    response_model=WorkoutSetResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_workout_set(
    user_id: UserId,
    session_id: SessionId,
    session_exercise_id: SessionExerciseId,
    set_data: WorkoutSetCreate,
    db: DbSession,
):
    try:
        return WorkoutSetService(db).add_set(user_id, session_id, session_exercise_id, set_data)
    except (WorkoutSessionNotFoundError, WorkoutSessionExerciseNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except WorkoutSessionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.patch(
    "/{session_id}/exercises/{session_exercise_id}/sets/{set_id}",
    response_model=WorkoutSetResponse,
)
def update_workout_set(
    user_id: UserId,
    session_id: SessionId,
    session_exercise_id: SessionExerciseId,
    set_id: SetId,
    set_data: WorkoutSetUpdate,
    db: DbSession,
):
    try:
        return WorkoutSetService(db).update_set(
            user_id, session_id, session_exercise_id, set_id, set_data
        )
    except (
        WorkoutSessionNotFoundError,
        WorkoutSessionExerciseNotFoundError,
        WorkoutSetNotFoundError,
    ) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except InvalidWorkoutSessionError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except WorkoutSessionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.delete(
    "/{session_id}/exercises/{session_exercise_id}/sets/{set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workout_set(
    user_id: UserId,
    session_id: SessionId,
    session_exercise_id: SessionExerciseId,
    set_id: SetId,
    db: DbSession,
):
    try:
        WorkoutSetService(db).remove_set(user_id, session_id, session_exercise_id, set_id)
    except (
        WorkoutSessionNotFoundError,
        WorkoutSessionExerciseNotFoundError,
        WorkoutSetNotFoundError,
    ) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except WorkoutSessionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
