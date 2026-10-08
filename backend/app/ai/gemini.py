"""Gemini, called through the Google GenAI SDK (google-genai).

The provider only turns messages into replies or tool calls. It reads no
Formiq data: the coach graph runs the tools the model calls.
"""

import logging
import math
from collections.abc import Iterable, Sequence
from typing import Any

from google import genai
from google.genai import types

from app.ai.exceptions import (
    AIModelOutputError,
    AIProviderError,
    AIProviderNotConfiguredError,
)
from app.ai.tool_calling import CoachMessage, ModelTurn, ToolCall, ToolDeclaration, ToolResult

logger = logging.getLogger(__name__)


class GeminiProvider:
    def __init__(self, api_key: str | None, model: str, *, timeout_seconds: float) -> None:
        self.model = model
        # The key is always passed explicitly, so the SDK never falls back to
        # other environment variables. Without a key there is no client.
        self._client = (
            genai.Client(
                api_key=api_key,
                # The SDK takes milliseconds, and reads 0 as no timeout, so it is
                # rounded up. Without retry_options it makes a single attempt.
                http_options=types.HttpOptions(timeout=math.ceil(timeout_seconds * 1000)),
            )
            if api_key
            else None
        )

    def generate(self, message: str, *, instructions: str) -> str:
        """The model's reply to the message, following the system instructions."""
        response = self._generate_content(
            message, types.GenerateContentConfig(system_instruction=instructions)
        )
        if not response.text:
            # for example when the prompt or the reply was blocked
            logger.warning("%s returned no text: %s", self.model, response.prompt_feedback)
            raise AIModelOutputError(f"{self.model} returned no text")
        return response.text

    def generate_turn(
        self,
        contents: Sequence[types.Content],
        *,
        instructions: str,
        tools: Sequence[ToolDeclaration],
        allow_tool_calls: bool = True,
        required_tool_names: Sequence[str] | None = None,
    ) -> ModelTurn:
        """The model's next turn in the conversation: a text reply, or the tool
        calls it wants run first.

        With allow_tool_calls false, the model is told to answer with text, and
        a tool call is a provider error. With required_tool_names, the model must
        call one or more of those tools, and a text reply is a provider error.
        """
        config = types.GenerateContentConfig(
            system_instruction=instructions,
            tools=(
                [types.Tool(function_declarations=[_function_declaration(t) for t in tools])]
                if tools
                else None
            ),
            tool_config=_tool_config(tools, allow_tool_calls, required_tool_names),
            # The coach graph runs the tools and limits the rounds; the SDK must
            # not run a loop of its own.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._generate_content(list(contents), config)

        function_calls = response.function_calls or []
        if function_calls:
            if not allow_tool_calls:
                logger.warning("%s called a tool when only text was allowed", self.model)
                raise AIModelOutputError(f"{self.model} returned no text")
            return ModelTurn(
                content=response.candidates[0].content,
                tool_calls=tuple(
                    ToolCall(name=call.name or "", arguments=dict(call.args or {}), id=call.id)
                    for call in function_calls
                ),
                usage=token_usage(response),
            )
        if required_tool_names is not None:
            logger.warning("%s answered without the required tool call", self.model)
            raise AIModelOutputError(f"{self.model} returned no tool call")
        if not response.text:
            # for example when the prompt or the reply was blocked
            logger.warning("%s returned no text: %s", self.model, response.prompt_feedback)
            raise AIModelOutputError(f"{self.model} returned no text")
        return ModelTurn(
            content=response.candidates[0].content, text=response.text, usage=token_usage(response)
        )

    def _generate_content(
        self, contents: str | list[types.Content], config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        if self._client is None:
            raise AIProviderNotConfiguredError("GEMINI_API_KEY is not set")
        try:
            return self._client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except Exception as error:
            # The cause, such as a rate limit, a network error or a timeout, goes
            # to the server log only.
            logger.exception("Gemini request to %s failed", self.model)
            raise AIProviderError(f"the {self.model} request failed") from error


def token_usage(response: types.GenerateContentResponse) -> dict[str, int] | None:
    """The token counts Gemini reported for the response, or None when it reported
    none. Only counts: nothing of the content."""
    usage = response.usage_metadata
    if usage is None:
        return None
    counts = {
        "input_tokens": usage.prompt_token_count,
        "output_tokens": usage.candidates_token_count,
        "reasoning_tokens": usage.thoughts_token_count,
        "total_tokens": usage.total_token_count,
    }
    return {name: count for name, count in counts.items() if isinstance(count, int)} or None


def conversation(
    user_message: str, messages: Sequence[CoachMessage], context: str | None = None
) -> list[types.Content]:
    """The turn's conversation as Gemini contents, for generate_turn.

    The earlier conversation, if any, comes first as its own text, ahead of the
    user's message. The model's turns are sent back as the exact contents Gemini
    returned, so their tool calls and thought signatures stay as they were. The
    results that answer one turn's tool calls go together in one content, as
    function responses: data for the model, not text from the user.
    """
    contents = [user_content(user_message, context)]
    results: list[ToolResult] = []
    for message in messages:
        if isinstance(message, ToolResult):
            results.append(message)
            continue
        if results:
            contents.append(tool_results_content((item.call, item.result) for item in results))
            results = []
        contents.append(message.content)
    if results:
        contents.append(tool_results_content((item.call, item.result) for item in results))
    return contents


def user_content(message: str, context: str | None = None) -> types.Content:
    """The user's message, as the first content of a conversation, after the
    earlier conversation when there is one: two parts, so the message stays as
    the user wrote it."""
    parts = [types.Part(text=context)] if context else []
    return types.Content(role="user", parts=[*parts, types.Part(text=message)])


def tool_results_content(results: Iterable[tuple[ToolCall, dict[str, Any]]]) -> types.Content:
    """The results of the model's tool calls, each paired with its call, to send
    back to the model."""
    return types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=call.id, name=call.name, response=result
                )
            )
            for call, result in results
        ],
    )


def _tool_config(
    tools: Sequence[ToolDeclaration],
    allow_tool_calls: bool,
    required_tool_names: Sequence[str] | None,
) -> types.ToolConfig | None:
    if not tools:
        return None
    if required_tool_names is not None:
        return types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.ANY,
                allowed_function_names=list(required_tool_names),
            )
        )
    if not allow_tool_calls:
        return types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.NONE
            )
        )
    return None


def _function_declaration(tool: ToolDeclaration) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=tool.name,
        description=tool.description,
        parameters_json_schema=tool.parameters,
    )
