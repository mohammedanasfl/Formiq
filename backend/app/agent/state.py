from typing import Any, NotRequired, TypedDict

from app.ai import ToolCall


class CoachState(TypedDict):
    """One turn of the coach graph: the user's message in, the reply out.

    The user's profile, workouts and other Formiq data are not copied in: the
    model reads what it needs with tools, which go through Formiq's services,
    scoped to user_id.
    """

    user_id: int
    message: str
    # The turn's conversation with the model, as the provider records it: the
    # user's message, the model's turns and the tool results.
    contents: NotRequired[list[Any]]
    # the tool calls of the model's latest turn, which the tools node runs next
    tool_calls: NotRequired[list[ToolCall]]
    # rounds of tool calls run so far in this turn
    tool_iterations: NotRequired[int]
    # set by the coach node when the model answers with text
    reply: NotRequired[str]
