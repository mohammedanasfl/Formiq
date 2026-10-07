"""Tool errors. The model gets their code and message, never internal details."""

from enum import StrEnum


class ToolErrorCode(StrEnum):
    USER_NOT_FOUND = "USER_NOT_FOUND"
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    # The resource does not exist or belongs to another user: the two are not
    # told apart, so a tool never reveals that another user's resource exists.
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    # the model called more tools in one turn than are run
    TOOL_LIMIT_REACHED = "TOOL_LIMIT_REACHED"
    # an unexpected failure; its cause is in the server log only
    TOOL_ERROR = "TOOL_ERROR"


class ToolError(Exception):
    """A tool could not return its data, for a reason the model may be told."""

    def __init__(self, code: ToolErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
