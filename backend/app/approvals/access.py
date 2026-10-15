"""Which operations read Formiq data and which would change it: Formiq's own
classification, by name, never the model's.

Only the operations listed in READ_ACTIONS are reads, and only those in
PROPOSAL_ACTIONS are proposals: they change nothing, but describe a write for
the user to approve (app.services.plan_proposal_service). Every other name, a
write listed below or any name Formiq does not know, is treated as a write: it
never runs from a model's call. The one write Formiq performs, creating a workout plan,
runs only from the user's own approval of a proposal; WriteAction also names
the writes a later phase may add, so that a model asking for one is recognised
and refused.

This module imports nothing from the rest of Formiq, so the coach graph can
check every call against it.
"""

from enum import StrEnum


class Access(StrEnum):
    READ = "read"
    PROPOSE = "propose"
    WRITE = "write"


# the coach's tools (app.tools), which only read
READ_ACTIONS = frozenset(
    {
        "get_user_profile",
        "get_workout_plan",
        "list_workout_plans",
        "get_workout_session",
        "get_current_workout_plan",
        "get_latest_workout_session",
        "get_pending_proposal",
        "get_exercise",
        "search_exercises",
    }
)


class WriteAction(StrEnum):
    """Operations that would change the user's data. Only CREATE_WORKOUT_PLAN
    is implemented, and only behind the user's approval."""

    CREATE_WORKOUT_PLAN = "create_workout_plan"
    MODIFY_WORKOUT_PLAN = "modify_workout_plan"
    CANCEL_WORKOUT_PLAN = "cancel_workout_plan"
    RECORD_WORKOUT = "record_workout"
    MODIFY_PROFILE = "modify_profile"
    RECORD_NUTRITION = "record_nutrition"
    DELETE_USER_DATA = "delete_user_data"


WRITE_ACTIONS = frozenset(WriteAction)

# the coach's proposals (app.tools), and the write each one proposes
PROPOSAL_ACTIONS = {"propose_workout_plan": WriteAction.CREATE_WORKOUT_PLAN}


def access_of(name: str) -> Access:
    """READ for the operations Formiq lists as reads, PROPOSE for its proposals;
    anything else would have to be treated as a write."""
    if name in READ_ACTIONS:
        return Access.READ
    if name in PROPOSAL_ACTIONS:
        return Access.PROPOSE
    return Access.WRITE


def is_write_action(name: str) -> bool:
    """Whether the name is one of the write operations Formiq knows."""
    return name in WRITE_ACTIONS
