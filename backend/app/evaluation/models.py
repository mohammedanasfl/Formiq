"""The evaluation's data: a case (a request, how the model behaves, and what
Formiq must do), the observable result of running it, and the verdicts.

A case's expectations are about observable behavior only: the validated
decision, the tool trajectory, the safety path, the status, the counts. Never
the model's reasoning, and never data or text beyond what a check needs.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

# --- how the model behaves in a deterministic run ---


@dataclass(frozen=True)
class Call:
    """A tool call the model makes. Argument values may name a fixture, such as
    "{plan_id}", filled in when the case runs."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CallTools:
    """A model turn of tool calls."""

    calls: tuple[Call, ...]


@dataclass(frozen=True)
class Respond:
    """A model turn that ends the turn with a decision."""

    intent: str
    decision: str
    reply: str


@dataclass(frozen=True)
class Text:
    """A model turn of plain text: invalid, since every turn must call a tool."""

    text: str


Turn = CallTools | Respond | Text

# how the provider fails, for a case about provider failures
ProviderFailure = Literal[
    "not_configured", "timeout", "rate_limit", "unavailable", "gateway_timeout", "network"
]


@dataclass(frozen=True)
class Bounds:
    """An inclusive range for a count."""

    low: int = 0
    high: int | None = None

    def contains(self, value: int) -> bool:
        return value >= self.low and (self.high is None or value <= self.high)

    def __str__(self) -> str:
        return f"{self.low}..{'' if self.high is None else self.high}"


def exactly(value: int) -> Bounds:
    return Bounds(value, value)


@dataclass(frozen=True)
class Overrides:
    """Limits a case runs with instead of the production ones, to reach a path
    the production limits make rare or unreachable. Evaluation only."""

    # the context budget in characters, or "rounds:N": room for N rounds of the
    # case's canned results and no more
    context_chars: int | str | None = None
    tool_iterations: int | None = None
    graph_steps: int | None = None


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    description: str
    message: str
    tags: tuple[str, ...] = ()
    # earlier turns, oldest first: (role, text), role "user" or "coach"
    history: tuple[tuple[str, str], ...] = ()
    # the request's user: the fixture user, or one that does not exist
    user: Literal["fixture", "missing"] = "fixture"

    # --- how the case runs deterministically ---
    script: tuple[Turn, ...] = ()
    provider_failure: ProviderFailure | None = None
    # outputs the tools give instead of reading the database, by tool name
    canned_tools: dict[str, dict[str, Any]] | None = None
    overrides: Overrides = field(default_factory=Overrides)

    # --- what Formiq must do (None: not checked) ---
    expected_intent: str | None = None
    expected_decision: str | None = None
    # tools that must have run and returned data
    required_tools: tuple[str, ...] = ()
    # tools that must not have run
    forbidden_tools: tuple[str, ...] = ()
    # the order the required tools ran in, when it matters
    expected_tool_order: tuple[str, ...] | None = None
    executed_tool_calls: Bounds | None = None
    model_requests: Bounds | None = None
    expected_safety_category: str | None = None
    expected_safety_path: Literal["model", "fixed_safe_response"] | None = None
    expected_status: str | None = None
    expected_termination: str | None = None
    # calls that must have been refused, as (tool, error code)
    expected_refused_calls: tuple[tuple[str, str], ...] = ()
    decision_rejections: Bounds | None = None
    reply_rejections: Bounds | None = None
    compactions: Bounds | None = None
    # a decision relying on a compacted result was rejected (the evidence left
    # the compacted result out)
    expect_compacted_evidence_excluded: bool = False

    # --- running modes ---
    # eligible for the opt-in live run against the real model
    live: bool = False
    # a documented gap between this expectation and the current contract: the
    # case is expected to fail until the contract changes
    known_gap: str | None = None


# --- what a run shows ---


@dataclass(frozen=True)
class ToolRecord:
    """One requested tool call, as the trace shows it."""

    name: str
    executed: bool
    # the failure category when it failed or was refused
    failure: str | None = None
    error_code: str | None = None
    data_status: str | None = None
    # for a call outside Formiq's reads: whether it named a write operation,
    # and the graph's authorization ("denied")
    write_requested: bool = False
    authorization: str | None = None


@dataclass(frozen=True)
class ValidationRecord:
    accepted: bool | None
    rejected_by: str | None = None
    compacted_excluded: int = 0
    reason: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    """What one run of a case shows: safe metadata only. No message, reply,
    history, tool data, instructions or reasoning."""

    status: str | None
    termination: str | None
    intent: str | None
    decision: str | None
    safety_category: str | None
    safety_path: str | None
    tools: tuple[ToolRecord, ...]
    # per round of tool calls: (requested, executed)
    rounds: tuple[tuple[int, int], ...]
    model_requests: int
    provider_attempts: int | None
    iterations: int | None
    compactions: int | None
    compacted_results: int
    decision_validations: tuple[ValidationRecord, ...]
    reply_validations: tuple[ValidationRecord, ...]
    # the users the tools read for, and the request's trusted user
    tool_user_ids: tuple[int, ...]
    trusted_user_id: int
    # the failure category, when the request raised
    error: str | None
    # whether the raised error's message held its cause's details
    error_leaks_cause: bool
    # about the reply, without the reply
    reply_chars: int | None
    reply_is_fixed_safe_reply: bool
    reply_repeats_instructions: bool
    # every observation started was ended
    trace_complete: bool
    # calls naming a write operation, refused by the graph
    write_calls_refused: int = 0

    @property
    def tools_requested(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools)

    @property
    def tools_executed(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools if tool.executed)

    @property
    def tools_with_data(self) -> tuple[str, ...]:
        return tuple(
            tool.name
            for tool in self.tools
            if tool.executed and tool.data_status in ("AVAILABLE", "INCOMPLETE")
        )


# --- verdicts ---


@dataclass(frozen=True)
class EvaluatorResult:
    name: str
    passed: bool
    expected: Any
    actual: Any
    reason: str


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    results: tuple[EvaluatorResult, ...]
    known_gap: str | None = None

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def failures(self) -> tuple[EvaluatorResult, ...]:
        return tuple(result for result in self.results if not result.passed)


@dataclass(frozen=True)
class Failure:
    case_id: str
    evaluator: str
    expected: Any
    actual: Any
    reason: str


@dataclass(frozen=True)
class EvaluationRunResult:
    total_cases: int
    passed: int
    failed: int
    failures: tuple[Failure, ...]
    # per evaluator: (passed, failed)
    evaluator_summary: dict[str, tuple[int, int]]
    # cases expected to fail (known gaps), and those that unexpectedly passed
    known_gaps: tuple[str, ...] = ()
    fixed_gaps: tuple[str, ...] = ()

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total_cases if self.total_cases else 1.0
