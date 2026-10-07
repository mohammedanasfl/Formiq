"""Tool calling between the model and the coach graph.

A turn's conversation is the user's message, then CoachMessages:

    user message -> ModelTurn(tool calls) -> ToolResult, ToolResult, ...
                 -> ModelTurn(tool calls) -> ToolResult ... -> ModelTurn(text)

The declarations and calls hold no Formiq data; a ToolResult holds the data a
tool returned for the call.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDeclaration:
    """A tool the model may call: its name, what it does for the model, and its
    arguments as a JSON schema object (None for a tool without arguments)."""

    name: str
    description: str
    parameters: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolCall:
    """The model's request to run a tool with these arguments."""

    name: str
    arguments: dict[str, Any]
    # the provider's id for the call, if it gives one; sent back with the result
    id: str | None = None


@dataclass(frozen=True)
class ModelTurn:
    """The model's next turn: a text reply, or tool calls to run before it answers."""

    # The turn as the provider records it, to send back unchanged with the rest
    # of the conversation: Gemini needs its thought signatures back.
    content: Any
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class ToolResult:
    """A tool's answer to one call of the model.

    It goes back to the model as data, the function response of that call, never
    as text from the user.
    """

    call: ToolCall
    # {"output": ...} or {"error": {"code": ..., "message": ...}}
    result: dict[str, Any]


# The messages of a turn that follow the user's message, in order: the model's
# turns, and after a turn with tool calls, one result per call.
CoachMessage = ModelTurn | ToolResult
