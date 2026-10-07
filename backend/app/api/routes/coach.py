from fastapi import APIRouter, HTTPException, status

from app.agent import ConversationTurn
from app.ai import AIProviderError, AIProviderNotConfiguredError
from app.api.dependencies import AIProvider, CoachTracer, DbSession
from app.schemas import CoachMessageRequest, CoachMessageResponse
from app.services import CoachService
from app.services.exceptions import UserNotFoundError

router = APIRouter(prefix="/coach", tags=["coach"])


@router.post("/message", response_model=CoachMessageResponse)
def send_coach_message(
    message_data: CoachMessageRequest, db: DbSession, provider: AIProvider, tracer: CoachTracer
):
    try:
        reply = CoachService(db, provider, tracer).reply(
            message_data.user_id,
            message_data.message,
            [ConversationTurn(turn.role, turn.text) for turn in message_data.history],
        )
    except UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    # The provider errors' own messages stay in the server log: the client only
    # learns that the coach is unavailable.
    except AIProviderNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the AI coach is not configured",
        ) from error
    except AIProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="the AI coach could not answer; try again later",
        ) from error
    return CoachMessageResponse(reply=reply)
