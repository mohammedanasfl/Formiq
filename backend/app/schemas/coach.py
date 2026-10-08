from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Surrounding whitespace is dropped, and a blank message is rejected. The limit
# keeps one message, and the model request it becomes, a reasonable size.
CoachMessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]


# Earlier turns one request may carry: the coach keeps only the most recent
# (app.agent.context), so more would only make the request larger.
MAX_HISTORY_TURNS = 50
# as long as a coach reply may be (app.agent.policy.MAX_REPLY_LENGTH); the coach
# shortens long turns
MAX_HISTORY_TEXT_LENGTH = 8000


class CoachHistoryTurn(BaseModel):
    """An earlier turn of the conversation: what the user wrote, or the coach's
    reply. Formiq stores no conversation, so the client sends the turns it
    wants the coach to see; they are context, not Formiq data."""

    role: Literal["user", "coach"]
    text: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH
        ),
    ]


class CoachMessageRequest(BaseModel):
    """A message to the coach from the signed-in user. The user is the access
    token's, never the body's: a body that names a user_id, or any other field
    not here, is rejected."""

    model_config = ConfigDict(extra="forbid")

    message: CoachMessageText
    # earlier turns, oldest first; the coach keeps the most recent ones
    history: list[CoachHistoryTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)


class CoachMessageResponse(BaseModel):
    reply: str
