"""Tool calling between the model and the coach graph.

These types hold no Formiq data: the graph passes tool calls to the tools and
their results back to the model.
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
