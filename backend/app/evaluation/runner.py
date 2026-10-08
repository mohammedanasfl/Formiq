"""Runs evaluation cases through the coach and observes what happened.

A case runs through CoachService as a request would: the graph, the policies,
the safety backstop and, unless the case gives canned outputs, the real tools on
the database the session is for. The model is, in a deterministic run, the
case's script, or a real provider whose SDK fails as the case says; in a live
run (opt-in), the configured Gemini model.

What the run shows is read from its trace (app.observability), recorded in
memory, plus a few booleans about the reply and the error: the evaluation never
reads Langfuse, and never keeps the reply, the data or the instructions.

The runner changes nothing in the coach. To reach paths the production limits
make rare, a case may run with other limits (Overrides); that, the fixture
data and the canned tool outputs are the only things it sets up.
"""

import re
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from functools import partial
from typing import Any
from unittest.mock import Mock, patch

import httpx
from google.genai import errors, types

from app.agent import (
    COACH_INSTRUCTIONS,
    SAFETY_POLICY,
    CoachContext,
    ConversationTurn,
    coach_graph,
)
from app.agent.context import fit_request
from app.ai import GeminiProvider, ModelTurn, ToolCall, ToolResult
from app.evaluation.fixtures import MISSING_USER_ID, Fixtures
from app.evaluation.models import (
    CallTools,
    EvalCase,
    ExecutionResult,
    Respond,
    Text,
    ToolRecord,
    Turn,
    ValidationRecord,
)
from app.observability import Tracer, classify
from app.observability.memory import MemoryBackend
from app.services import CoachService
from app.tools import TOOL_DECLARATIONS, FormiqTools
from app.tools.limits import MAX_EXECUTED_TOOL_CALLS_PER_TURN


class ScriptExhausted(Exception):
    """The coach asked the scripted model for more turns than the case has."""


# --- filling in fixture ids ---

_PLACEHOLDER = re.compile(r"^\{(\w+)\}$")


def fill(value: Any, names: dict[str, int]) -> Any:
    """The value with fixture names filled in: "{plan_id}" alone becomes the id,
    inside text it becomes the id's digits."""
    if isinstance(value, str):
        if match := _PLACEHOLDER.match(value):
            return names[match.group(1)]
        return value.format_map(names) if "{" in value else value
    if isinstance(value, dict):
        return {key: fill(item, names) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [fill(item, names) for item in value]
    return value


# --- the model ---


def model_turn(turn: Turn, names: dict[str, int], number: int) -> ModelTurn:
    if isinstance(turn, Text):
        return ModelTurn(
            content=types.Content(role="model", parts=[types.Part(text=turn.text)]), text=turn.text
        )
    if isinstance(turn, Respond):
        specs = [("respond", {"intent": turn.intent, "decision": turn.decision, "reply": turn.reply})]
    else:
        specs = [(call.name, fill(call.args, names)) for call in turn.calls]
    calls = tuple(
        ToolCall(name=name, arguments=args, id=f"eval-{number}-{index}")
        for index, (name, args) in enumerate(specs)
    )
    content = types.Content(
        role="model",
        parts=[
            types.Part(function_call=types.FunctionCall(id=c.id, name=c.name, args=c.arguments))
            for c in calls
        ],
    )
    return ModelTurn(content=content, tool_calls=calls)


def scripted_provider(script: Sequence[Turn], names: dict[str, int]) -> Mock:
    """A model that plays the script, turn by turn."""
    turns = iter([model_turn(turn, names, number) for number, turn in enumerate(script)])
    provider = Mock(spec=GeminiProvider)
    provider.model = "scripted"

    def next_turn(*args: Any, **kwargs: Any) -> ModelTurn:
        try:
            return next(turns)
        except StopIteration:
            raise ScriptExhausted("the coach asked for more model turns than scripted") from None

    provider.generate_turn.side_effect = next_turn
    return provider


def provider_failure(kind: str) -> BaseException:
    """What the SDK raises for each failure. The messages carry details that
    must never reach the caller."""
    def api(code: int, status: str) -> dict:
        return {"error": {"code": code, "message": "eval: upstream detail", "status": status}}

    return {
        "timeout": lambda: httpx.ReadTimeout("eval: upstream detail"),
        "rate_limit": lambda: errors.ClientError(429, api(429, "RESOURCE_EXHAUSTED")),
        "unavailable": lambda: errors.ServerError(503, api(503, "UNAVAILABLE")),
        "gateway_timeout": lambda: errors.ServerError(504, api(504, "DEADLINE_EXCEEDED")),
        "network": lambda: ConnectionError("eval: upstream detail"),
    }[kind]()


# --- the tools ---


class CannedTools:
    """Tools that answer with the case's outputs instead of reading the database,
    within the same per-turn limit as the real tools."""

    declarations = TOOL_DECLARATIONS

    def __init__(self, outputs: dict[str, dict[str, Any]], user_ids: list[int]) -> None:
        self.outputs = outputs
        self.user_ids = user_ids

    def run(self, calls: Sequence[ToolCall], *, user_id: int) -> list[dict[str, Any]]:
        self.user_ids.append(user_id)
        unknown = {"error": {"code": "UNKNOWN_TOOL", "message": "there is no tool with this name"}}
        limit = {"error": {"code": "TOOL_LIMIT_REACHED", "message": "too many calls"}}
        return [
            self.outputs.get(call.name, unknown) if index < MAX_EXECUTED_TOOL_CALLS_PER_TURN else limit
            for index, call in enumerate(calls)
        ]


def _recording_run(user_ids: list[int]):
    original = FormiqTools.run

    def run(self: FormiqTools, calls: Sequence[ToolCall], *, user_id: int) -> list[dict[str, Any]]:
        user_ids.append(user_id)
        return original(self, calls, user_id=user_id)

    return run


def rounds_budget(case: EvalCase, rounds: int, message: str, names: dict[str, int]) -> int:
    """A context budget with room for this many rounds of the case's first tool
    call and its canned output, and no more."""
    first = next(turn for turn in case.script if isinstance(turn, CallTools))
    call = first.calls[0]
    output = fill(case.canned_tools[call.name], names)
    messages: list[Any] = []
    for number in range(rounds):
        turn = model_turn(CallTools((call,)), names, number)
        messages += [turn, ToolResult(call=turn.tool_calls[0], result=output)]
    return fit_request(message, None, messages, COACH_INSTRUCTIONS, 10**9).size + 500


# --- running a case ---


@contextmanager
def _provider(case: EvalCase, names: dict[str, int], given: Any) -> Iterator[tuple[Any, Any]]:
    """The provider for the case, and what counts its attempts."""
    if given is not None:
        yield given, None
    elif case.provider_failure == "not_configured":
        yield GeminiProvider(None, "gemini-eval", timeout_seconds=30), None
    elif case.provider_failure is not None:
        with patch("app.ai.gemini.genai.Client") as client_class:
            generate = client_class.return_value.models.generate_content
            generate.side_effect = provider_failure(case.provider_failure)
            yield GeminiProvider("eval-key-not-a-secret", "gemini-eval", timeout_seconds=30), generate
    else:
        provider = scripted_provider(case.script, names)
        yield provider, provider.generate_turn


def run_case(
    case: EvalCase, session: Any, fixtures: Fixtures, provider: Any = None
) -> ExecutionResult:
    """Runs the case once and returns what it showed. A provider given (a live
    model) replaces the case's script."""
    names = fixtures.names()
    message = fill(case.message, names)
    history = [ConversationTurn(role, fill(text, names)) for role, text in case.history]
    user_id = fixtures.user_id if case.user == "fixture" else MISSING_USER_ID
    backend = MemoryBackend()
    tool_user_ids: list[int] = []
    reply: str | None = None
    error: BaseException | None = None
    with ExitStack() as stack:
        model, attempts = stack.enter_context(_provider(case, names, provider))
        stack.enter_context(patch.object(FormiqTools, "run", _recording_run(tool_user_ids)))
        if case.canned_tools is not None:
            canned = CannedTools(fill(case.canned_tools, names), tool_user_ids)
            stack.enter_context(patch.object(CoachService, "_tools", lambda self: canned))
        _apply_overrides(case, message, names, stack)
        try:
            reply = CoachService(session, model, Tracer(backend)).reply(user_id, message, history)
        except Exception as raised:  # noqa: BLE001 - the error is what the case observes
            error = raised
        provider_attempts = attempts.call_count if attempts is not None else None
    return observe(backend, reply, error, provider_attempts, tool_user_ids, user_id)


def _apply_overrides(case: EvalCase, message: str, names: dict[str, int], stack: ExitStack) -> None:
    overrides = case.overrides
    limits: dict[str, int] = {}
    if isinstance(overrides.context_chars, int):
        limits["max_context_chars"] = overrides.context_chars
    elif isinstance(overrides.context_chars, str):
        rounds = int(overrides.context_chars.removeprefix("rounds:"))
        limits["max_context_chars"] = rounds_budget(case, rounds, message, names)
    if overrides.tool_iterations is not None:
        limits["max_tool_iterations"] = overrides.tool_iterations
    if limits:
        stack.enter_context(
            patch("app.services.coach_service.CoachContext", partial(CoachContext, **limits))
        )
    if overrides.graph_steps is not None:
        stack.enter_context(
            patch(
                "app.services.coach_service.coach_graph",
                coach_graph.with_config(recursion_limit=overrides.graph_steps),
            )
        )


# --- what the run shows ---

_FIXED_REPLIES = frozenset(policy.fallback_reply for policy in SAFETY_POLICY.values())
# Lines of the instructions long enough that a reply containing one repeats them.
# A check of its own, apart from the coach's reply check (app.agent.trust).
_INSTRUCTION_LINES = tuple(
    line.strip().casefold() for line in COACH_INSTRUCTIONS.splitlines() if len(line.strip()) >= 40
)


def observe(
    backend: MemoryBackend,
    reply: str | None,
    error: BaseException | None,
    provider_attempts: int | None,
    tool_user_ids: Sequence[int],
    trusted_user_id: int,
) -> ExecutionResult:
    root = backend.root
    meta = root.metadata
    tools = tuple(
        ToolRecord(
            name=node.name,
            executed=_executed(node.metadata),
            failure=node.status_message if node.level == "ERROR" else None,
            error_code=node.metadata.get("error_code"),
            data_status=node.metadata.get("data_status"),
        )
        for node in backend.nodes
        if node.kind == "tool"
    )
    rounds = tuple(
        (
            node.metadata.get("requested", 0),
            sum(_executed(child.metadata) for child in backend.children(node)),
        )
        for node in backend.named("tool_calls")
    )
    decisions = tuple(
        ValidationRecord(
            accepted=node.metadata.get("accepted"),
            rejected_by=node.metadata.get("rejected_by"),
            compacted_excluded=node.metadata.get("compacted_results_excluded", 0),
        )
        for node in backend.named("decision_validation")
    )
    replies = tuple(
        ValidationRecord(accepted=node.metadata.get("accepted"), reason=node.metadata.get("reason"))
        for node in backend.named("reply_validation")
    )
    cause = error.__cause__ if error is not None else None
    lowered = (reply or "").casefold()
    return ExecutionResult(
        status=meta.get("status"),
        termination=meta.get("termination"),
        intent=meta.get("intent"),
        decision=meta.get("decision"),
        safety_category=_safety_category(backend, meta),
        safety_path=meta.get("safety_path"),
        tools=tools,
        rounds=rounds,
        model_requests=meta.get("model_requests", 0),
        provider_attempts=provider_attempts,
        iterations=meta.get("iterations"),
        compactions=meta.get("compactions"),
        compacted_results=meta.get("compacted_tool_results", 0),
        decision_validations=decisions,
        reply_validations=replies,
        tool_user_ids=tuple(tool_user_ids),
        trusted_user_id=trusted_user_id,
        error=None if error is None else (meta.get("status") or classify(error)),
        error_leaks_cause=cause is not None and str(cause) in str(error),
        reply_chars=None if reply is None else len(reply),
        reply_is_fixed_safe_reply=reply in _FIXED_REPLIES,
        reply_repeats_instructions=any(line in lowered for line in _INSTRUCTION_LINES),
        trace_complete=all(node.ended for node in backend.nodes),
    )


def _executed(metadata: dict[str, Any]) -> bool:
    """Whether the tool ran the call: sent to it, and not refused for the
    per-turn limit (the tools answer calls past it without running them)."""
    return bool(metadata.get("executed")) and metadata.get("error_code") != "TOOL_LIMIT_REACHED"


def _safety_category(backend: MemoryBackend, meta: dict[str, Any]) -> str | None:
    """The safety check's category: from the decision, or from the check itself
    when the request ended before one."""
    if meta.get("safety_category"):
        return meta["safety_category"]
    checks = backend.named("safety_check")
    return checks[0].metadata.get("safety_category") if checks else None
