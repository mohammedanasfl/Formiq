"""Fakes for the coach tests: model turns, a model and tools. No test calls the
Gemini API."""

from itertools import count
from unittest.mock import Mock

from google.genai import types

from app.ai import GeminiProvider, ModelTurn, ToolCall, ToolDeclaration


def text_turn(text: str) -> ModelTurn:
    return ModelTurn(content=types.Content(role="model", parts=[types.Part(text=text)]), text=text)


_call_ids = count(1)


def call(name: str, **arguments) -> ToolCall:
    return ToolCall(name=name, arguments=arguments, id=f"call-{next(_call_ids)}")


def tool_turn(*calls: ToolCall) -> ModelTurn:
    return ModelTurn(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        id=item.id, name=item.name, args=item.arguments
                    )
                )
                for item in calls
            ],
        ),
        tool_calls=tuple(calls),
    )


def respond_turn(
    reply: str, intent: str = "GENERAL_FITNESS", decision: str = "ANSWER"
) -> ModelTurn:
    """The model's last turn: the respond call with its intent, decision and reply."""
    return tool_turn(call("respond", intent=intent, decision=decision, reply=reply))


def fake_provider(*turns: ModelTurn) -> Mock:
    """A model that gives these turns, in order."""
    provider = Mock(spec=GeminiProvider)
    provider.generate_turn.side_effect = list(turns)
    return provider


class FakeTools:
    """Tools that record their calls and answer each with result(call)."""

    declarations = (ToolDeclaration(name="get_user_profile", description="The profile."),)

    def __init__(self, result=lambda call: {"output": {"tool": call.name}}):
        self.result = result
        self.runs: list[tuple[list[ToolCall], int]] = []

    def run(self, calls, *, user_id):
        self.runs.append((list(calls), user_id))
        return [self.result(item) for item in calls]


def sent_contents(provider: Mock, request: int) -> list[types.Content]:
    """The conversation sent to the model in its request-th request (from 0)."""
    return provider.generate_turn.call_args_list[request].args[0]


def tool_responses(content: types.Content) -> list[types.FunctionResponse]:
    return [part.function_response for part in content.parts]
