"""What the coach tells the local debug output (app.observability.debug) of its turn.

The sink knows nothing of the agent or the model: it is handed plain records,
each text tagged by who wrote it. The tags are decided here, where the
provenance is known: the system prompt, the declarations and the replies Formiq
writes are Formiq's (Authored); the user's message, the history, the model's text
and every tool argument or result are data (the sink shows only what it may).

Everything is built from what is actually sent: the request's contents are read
as they go to the provider (app.agent.context.fit_request's output), and the
request's configuration by the same function the provider builds it with
(app.ai.turn_config), so the view cannot drift from the request. Nothing here
changes a thing it reads, and it builds nothing unless AGENT_DEBUG is on: every
entry point returns at once when the trace has no debug output.
"""

import logging
from collections.abc import Callable, Sequence
from functools import wraps
from typing import Any

from app.agent.context import (
    COMPACTED_RESULT,
    SUPERSEDED_RESULT,
    ContextFit,
    ConversationContext,
)
from app.ai import ModelTurn, ToolCall, ToolDeclaration, ToolResult, turn_config
from app.approvals.access import PROPOSAL_ACTIONS, READ_ACTIONS, WRITE_ACTIONS
from app.observability import RunTrace
from app.observability.debug import (
    Authored,
    CallView,
    MessageView,
    PartView,
    Private,
    RequestView,
)

logger = logging.getLogger(__name__)


def quiet(function: Callable[..., None]) -> Callable[..., None]:
    """An entry point that cannot fail the turn: building what the debug output is
    told is part of the turn's path, so a failure in it is logged by its type and
    the turn goes on."""

    @wraps(function)
    def guarded(*args: Any, **kwargs: Any) -> None:
        try:
            function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - debugging must not fail the turn
            logger.warning("Agent debug view (%s) failed (%s); the turn goes on", function.__name__, type(error).__name__)

    return guarded


# the operations Formiq knows by name, whether or not a request offers them: a tool name
# is shown only if it is one of these (or offered), never because it looks like a name
KNOWN_TOOLS = tuple(sorted({str(name) for name in (*READ_ACTIONS, *PROPOSAL_ACTIONS, *WRITE_ACTIONS)}))

# what the request configures besides the prompt, the tools and how they are called
_ALWAYS_SET = frozenset({"system_instruction", "tools", "tool_config", "automatic_function_calling"})


def prompt_variant(safety_category: str | None, pending_note: bool) -> str:
    """Which of the coach's instructions a request carries: the safety variant of
    a flagged request, the base with the note of a proposal awaiting approval, or
    the base."""
    if safety_category is not None:
        return f"safety/{safety_category}"
    return "pending-note" if pending_note else "base"


def config_facts(
    instructions: str, declarations: Sequence[ToolDeclaration]
) -> dict[str, Any]:
    """What the request's configuration holds besides the prompt and the tools,
    read from the configuration the provider sends (turn_config, called as the
    coach's model_turn calls generate_turn): how the model may call tools, and the
    generation settings, none of which Formiq sets."""
    config = turn_config(
        instructions, declarations, True, [declaration.name for declaration in declarations]
    )
    calling = config.tool_config.function_calling_config if config.tool_config else None
    mode = calling.mode if calling is not None else None
    present = [name for name in type(config).model_fields if getattr(config, name) is not None]
    generation = [name for name in present if name not in _ALWAYS_SET]
    automatic = config.automatic_function_calling
    return {
        "function_calling_mode": getattr(mode, "value", mode),
        "allowed_function_names": list(calling.allowed_function_names or []) if calling else [],
        "automatic_function_calling": (
            "disabled" if automatic is not None and automatic.disable else "enabled"
        ),
        "config_fields_set": present,
        "generation_settings": generation or "none set: the model's defaults apply",
    }


def request_view(
    *,
    number: int | None,
    iteration: int,
    kind: str,
    model: str | None,
    variant: str,
    instructions: str,
    declarations: Sequence[ToolDeclaration],
    messages: Sequence[Any],
    fit: ContextFit,
    conversation: ConversationContext,
    budget: int,
    compactions: int,
) -> RequestView:
    """The model request as it is sent: the prompt and the tools apart from the
    context, and the context message by message with its roles and parts."""
    return RequestView(
        number=number,
        round=iteration,
        kind=kind,
        model=model,
        variant=variant,
        instructions=instructions,
        declarations=tuple(
            (declaration.name, declaration.description, declaration.parameters)
            for declaration in declarations
        ),
        known_tools=KNOWN_TOOLS,
        config=config_facts(instructions, declarations),
        facts={
            "messages": len(fit.contents),
            "context_chars": fit.size,
            "chars_before_fit": fit.size_before,
            "budget": budget,
            "compacted_results": fit.compacted_results,
            "superseded_results": len(fit.superseded),
            "compactions_in_turn": compactions,
            "history_turns": len(conversation.turns),
            "history_omitted": conversation.omitted,
        },
        messages=_messages(fit.contents, [m for m in messages if isinstance(m, ToolResult)], conversation),
    )


def _messages(
    contents: Sequence[Any], results: Sequence[ToolResult], conversation: ConversationContext
) -> tuple[MessageView, ...]:
    """The contents the provider is sent, each as its role and its parts. The tool
    results the turn holds are in the same order as the function responses sent, so
    the n-th response is the n-th result: a response that is a note shows what it
    replaced."""
    views = []
    answered = 0
    for index, content in enumerate(contents):
        parts = content.parts or []
        calls = responses = 0
        built = []
        for position, part in enumerate(parts):
            signature = len(part.thought_signature) if getattr(part, "thought_signature", None) else None
            if part.function_call is not None:
                call = part.function_call
                built.append(
                    PartView(
                        kind="function_call",
                        name=call.name,
                        call_id=call.id or f"{call.name}-{calls}",
                        synthesized_id=call.id is None,
                        data=dict(call.args or {}),
                        signature_bytes=signature,
                    )
                )
                calls += 1
            elif part.function_response is not None:
                response = part.function_response
                data = response.response or {}
                status = (
                    "compacted"
                    if data == COMPACTED_RESULT
                    else "superseded" if data == SUPERSEDED_RESULT else "original"
                )
                original = results[answered].result if answered < len(results) else None
                built.append(
                    PartView(
                        kind="function_response",
                        name=response.name,
                        call_id=response.id or f"{response.name}-{responses}",
                        synthesized_id=response.id is None,
                        data=data,
                        status=status,
                        replaced=original if status != "original" else None,
                    )
                )
                responses += 1
                answered += 1
            elif content.role == "model":
                built.append(
                    PartView(
                        kind="thought" if part.thought else "model_text",
                        text=part.text or "",
                        signature_bytes=signature,
                    )
                )
            elif index == 0 and position == 0 and len(parts) > 1:
                # user_content: the earlier conversation first, then the message
                built.append(
                    PartView(
                        kind="history",
                        text=part.text or "",
                        detail={
                            "turns": [turn.role for turn in conversation.turns],
                            "omitted": conversation.omitted,
                        },
                    )
                )
            else:
                built.append(PartView(kind="user_message", text=part.text or ""))
        views.append(MessageView(index=index, role=content.role or "unknown", parts=tuple(built)))
    return tuple(views)


@quiet
def debug_request(trace: RunTrace, **fields: Any) -> None:
    """The request about to be sent (request_view). Built only when debugging."""
    if trace.debug is not None:
        trace.debug.request(lambda: request_view(**fields))


def call_view(call: ToolCall, index: int) -> CallView:
    return CallView(
        name=call.name,
        call_id=call.id or f"{call.name}-{index}",
        synthesized_id=call.id is None,
        arguments=call.arguments,
    )


@quiet
def debug_response(trace: RunTrace, number: int | None, turn: ModelTurn) -> None:
    """What the model returned for the request."""
    if trace.debug is not None:
        trace.debug.response(
            number,
            text=turn.text,
            calls=[call_view(call, index) for index, call in enumerate(turn.tool_calls)],
            usage=turn.usage,
            model_reported=turn.model,
        )


@quiet
def debug_tool(
    trace: RunTrace,
    call: ToolCall,
    index: int,
    result: dict[str, Any],
    *,
    origin: str,
    executed: bool,
    code: str | None,
    category: str | None,
    empty: bool,
    repeat: str,
    duration_ms: int | None,
) -> None:
    """A call's outcome, as the trajectory counts it: blocked (refused before it
    ran), failed (ran, and returned an error), empty (a read of the user's own
    record that found none) or ok."""
    if trace.debug is None:
        return
    failed = executed and code is not None and not empty
    outcome = "blocked" if not executed else "error" if failed else "empty" if empty else "ok"
    trace.debug.tool(
        name=call.name,
        call_id=call.id or f"{call.name}-{index}",
        synthesized_id=call.id is None,
        origin=origin,
        outcome=outcome,
        category=category,
        code=code,
        repeat=repeat,
        duration_ms=duration_ms,
        result=result,
    )


@quiet
def debug_source(trace: RunTrace, source: str, detail: str, reply: str, *, authored: bool) -> None:
    """Who wrote the reply the user gets. source: model, safety_fallback,
    generic_fallback or card_fallback; authored: Formiq wrote it, so it may be shown."""
    if trace.debug is not None:
        trace.debug.response_source(
            source, detail, Authored(reply) if authored else Private(reply, "model reply")
        )
