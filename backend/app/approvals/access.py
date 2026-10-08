"""Which operations read Formiq data and which would change it: Formiq's own
classification, by name, never the model's.

Only the operations listed in READ_ACTIONS are reads. Every other name, a write
listed below or any name Formiq does not know, is treated as a write: it never
runs from a model's call, and running it would need the user's explicit
approval of a proposal (app.approvals.store). Formiq has no write operations
yet; WriteAction names the ones a later phase may add, so that a model asking
for one is recognised and refused.

This module imports nothing from the rest of Formiq, so the coach graph can
check every call against it.
"""

from enum import StrEnum


class Access(StrEnum):
    READ = "read"
    WRITE = "write"


# the coach's tools (app.tools), which only read
READ_ACTIONS = frozenset(
    {
        "get_user_profile",
        "get_workout_plan",
        "get_workout_session",
        "get_exercise",
        "search_exercises",
    }
)


class WriteAction(StrEnum):
    """Operations that would change the user's data. None is implemented."""

    CREATE_WORKOUT_PLAN = "create_workout_plan"
    MODIFY_WORKOUT_PLAN = "modify_workout_plan"
    CANCEL_WORKOUT_PLAN = "cancel_workout_plan"
    RECORD_WORKOUT = "record_workout"
    MODIFY_PROFILE = "modify_profile"
    RECORD_NUTRITION = "record_nutrition"
    DELETE_USER_DATA = "delete_user_data"


WRITE_ACTIONS = frozenset(WriteAction)


def access_of(name: str) -> Access:
    """READ only for the operations Formiq lists as reads; anything else would
    have to be treated as a write."""
    return Access.READ if name in READ_ACTIONS else Access.WRITE


def is_write_action(name: str) -> bool:
    """Whether the name is one of the write operations Formiq knows."""
    return name in WRITE_ACTIONS
