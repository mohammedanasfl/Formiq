from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Path, status

from app.api.dependencies import DbSession, PathUserIsCurrentUser, UserId
from app.schemas import RecoverySummaryRequest, RecoverySummaryResponse
from app.services import RecoverySummaryService
from app.services.exceptions import WorkoutSessionNotCompletedError, WorkoutSessionNotFoundError

# Each route is scoped to the user in the path, who must be the signed-in user:
# another user's session is not found.
router = APIRouter(
    prefix="/users/{user_id}/workout-sessions",
    tags=["recovery summaries"],
    dependencies=[PathUserIsCurrentUser],
)

# Like users.id, workout_sessions.id is a PostgreSQL integer column: IDs outside its
# range would fail in the database, so they are rejected with 422.
SessionId = Annotated[int, Path(ge=1, le=2_147_483_647)]


# A POST because it takes what the user reports; nothing is written, so the answer is 200.
# The body is optional: without one, or with {}, nothing is reported.
@router.post("/{session_id}/recovery-summary", response_model=RecoverySummaryResponse)
def get_recovery_summary(
    user_id: UserId,
    session_id: SessionId,
    db: DbSession,
    request_data: Annotated[RecoverySummaryRequest | None, Body()] = None,
):
    if request_data is None:
        request_data = RecoverySummaryRequest()
    try:
        return RecoverySummaryService(db).build_summary(user_id, session_id, request_data)
    except WorkoutSessionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except WorkoutSessionNotCompletedError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
