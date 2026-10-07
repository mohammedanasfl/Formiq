from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.schemas.workout_plan import PositiveInteger

# Surrounding whitespace is dropped, and a blank message is rejected. The limit
# keeps one message, and the model request it becomes, a reasonable size.
CoachMessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]


class CoachMessageRequest(BaseModel):
    user_id: PositiveInteger
    message: CoachMessageText


class CoachMessageResponse(BaseModel):
    reply: str
