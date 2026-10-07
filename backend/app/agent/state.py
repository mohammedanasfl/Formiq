from typing import NotRequired, TypedDict


class CoachState(TypedDict):
    """One turn of the coach graph: the user's message in, the reply out.

    The user's profile, workouts and other Formiq data are not copied in: tools
    will read them through Formiq's services, scoped to user_id.
    """

    user_id: int
    message: str
    # set by the coach node
    reply: NotRequired[str]
