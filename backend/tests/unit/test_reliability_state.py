"""The coach graph's state between turns: every turn starts from nothing,
whatever ran before it or runs beside it on the same compiled graph.

Each scenario is a turn with its own user, message, history, model, tool
results, context limits and outcome. A turn run after others, or at the same
time as others, must end exactly as it does alone: same reply, decision,
counts, conversation, messages, tool calls and trusted user. The model and
tools are fakes: no test calls Gemini or touches the database.
"""

import copy
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from google.genai import types
from langgraph.errors import GraphRecursionError

from app.agent import (
    MAX_GRAPH_STEPS,
    NO_CONVERSATION,
    POLICY,
    SAFETY_POLICY,
    CoachContext,
    ConversationTurn,
    coach_graph,
    initial_state,
)
from app.agent.context import COMPACTED_RESULT
from app.agent.policy import RESPOND
from app.ai import AIProviderError, ModelTurn, ToolCall, ToolDeclaration
from app.observability import TRACING_OFF, Tracer
from app.tools import TOOL_DECLARATIONS
from tests.reliability import WAIT_SECONDS, concurrently
from tests.unit.test_coach_conversation_context import BIG_PLAN, budget_for_rounds


def turn(*calls: tuple[str, dict[str, Any]], number: int) -> ModelTurn:
    """A model turn with these calls; ids fixed, so equal turns compare equal."""
    tool_calls = tuple(
        ToolCall(name=name, arguments=args, id=f"t{number}-{index}")
        for index, (name, args) in enumerate(calls)
    )
    content = types.Content(
        role="model",
        parts=[
            types.Part(function_call=types.FunctionCall(id=c.id, name=c.name, args=c.arguments))
            for c in tool_calls
        ],
    )
    return ModelTurn(content=content, tool_calls=tool_calls)


def respond(intent: str, decision: str, reply: str, number: int) -> ModelTurn:
    return turn(("respond", {"intent": intent, "decision": decision, "reply": reply}), number=number)


class ScenarioModel:
    """A model playing a fixed list of turns (or failures); one per turn run.
    With a barrier, its first request waits there for the other turns."""

    model = "scenario"

    def __init__(self, script: list[Any], barrier: threading.Barrier | None) -> None:
        self.script = list(script)
        self.barrier = barrier
        self.requests: list[Any] = []

    def generate_turn(self, contents, **kwargs):
        if self.barrier is not None and not self.requests:
            self.barrier.wait(WAIT_SECONDS)
        self.requests.append(contents)
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


class ScenarioTools:
    """Tools answering from fixed results, recording whose data was asked for."""

    declarations = TOOL_DECLARATIONS

    def __init__(self, results: dict[str, dict[str, Any]]) -> None:
        self.results = results
        self.user_ids: list[int] = []

    def run(self, calls, *, user_id):
        self.user_ids.append(user_id)
        return [copy.deepcopy(self.results[call.name]) for call in calls[:5]] + [
            {"error": {"code": "TOOL_LIMIT_REACHED", "message": "not run"}} for _ in calls[5:]
        ]


@dataclass(frozen=True)
class Scenario:
    user_id: int
    message: str
    script: tuple[Any, ...]
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: tuple[ConversationTurn, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)


def outcome(
    scenario: Scenario, barrier: threading.Barrier | None = None, tracer: Tracer = TRACING_OFF
) -> dict[str, Any]:
    """Everything the turn ended with, or what it raised: built from scratch
    for every run, so two runs share nothing but the compiled graph (and the
    tracer, when one is given)."""
    model = ScenarioModel(copy.deepcopy(list(scenario.script)), barrier)
    tools = ScenarioTools(copy.deepcopy(scenario.results))
    try:
        with tracer.request(
            "coach_request", request_id=uuid.uuid4().hex, user_id=scenario.user_id
        ) as trace:
            state = coach_graph.invoke(
                initial_state(scenario.message, scenario.history),
                context=CoachContext(
                    user_id=scenario.user_id,
                    provider=model,
                    tools=tools,
                    trace=trace,
                    **scenario.context,
                ),
            )
    except Exception as error:  # noqa: BLE001 - part of the outcome
        state = {"raised": type(error).__name__}
    return {
        **state,
        "tool_user_ids": tools.user_ids,
        "model_requests": len(model.requests),
        # what the model was sent, which history and data it saw
        "sent": [repr(contents) for contents in model.requests],
    }


PROFILE_A = {"output": {"user_id": 101, "profile": {"goal": "fat_loss"}}}
PLAN_B = {**BIG_PLAN, "output": {**BIG_PLAN["output"], "owner": 202}}

SCENARIOS = {
    # a profile question with its own history; its first answer, with no data,
    # is rejected, so evidence left by another turn would show
    "A": Scenario(
        user_id=101,
        message="What is my goal?",
        history=(
            ConversationTurn("user", "FORMIQ_HISTORY_USER_A_CANARY: I train on Mondays."),
            ConversationTurn("coach", "Noted."),
        ),
        script=(
            respond("PROFILE", "RETRIEVE_THEN_ANSWER", "Your goal is muscle gain.", 0),
            turn(("get_user_profile", {}), number=1),
            respond("PROFILE", "RETRIEVE_THEN_ANSWER", "Your goal is fat loss.", 2),
        ),
        results={"get_user_profile": PROFILE_A},
    ),
    # a plan read every round up to the limit, its context compacted
    "B": Scenario(
        user_id=202,
        message="Compare plan 12",
        script=(
            *[turn(("get_workout_plan", {"plan_id": 12}), number=n) for n in range(5)],
            respond("WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER", "Plan 12 has one exercise.", 5),
        ),
        results={"get_workout_plan": PLAN_B},
        context={"max_context_chars": budget_for_rounds(2)},
    ),
    # a flagged request whose model fails: Formiq's fixed safe reply
    "C": Scenario(
        user_id=303,
        message="I have sharp knee pain when I squat. Should I push through it?",
        script=(AIProviderError("the model failed"),),
    ),
    # a turn asking for more calls than allowed: an invalid model output
    "D": Scenario(
        user_id=404,
        message="Tell me about exercise 9.",
        script=(turn(*[("get_exercise", {"exercise_id": 9})] * 21, number=0),),
        results={"get_exercise": {"output": {"exercise_id": 9}}},
    ),
    # many calls a turn: five run, the rest are refused
    "E": Scenario(
        user_id=505,
        message="Tell me about exercise 9.",
        script=(
            turn(*[("get_exercise", {"exercise_id": 9})] * 20, number=0),
            respond("EXERCISE", "RETRIEVE_THEN_ANSWER", "Exercise 9 is a press.", 1),
        ),
        results={"get_exercise": {"output": {"exercise_id": 9}}},
    ),
}


@pytest.fixture(scope="module")
def alone():
    """Each scenario's outcome when it runs by itself."""
    return {name: outcome(scenario) for name, scenario in SCENARIOS.items()}


def test_the_scenarios_differ_in_everything_compared(alone):
    # so a leak between them would change an outcome
    assert alone["A"]["decision"].intent == "PROFILE" and alone["A"]["iteration_count"] == 2
    assert alone["B"]["iteration_count"] == 5 and alone["B"]["context_compactions"] > 0
    assert alone["C"]["decision"].safety == "PAIN_OR_INJURY"
    assert alone["D"] == {**alone["D"], "raised": "AIModelOutputError"}
    assert alone["E"]["iteration_count"] == 1
    assert [alone[n]["tool_user_ids"] for n in "ABCE"] == [[101], [202] * 5, [], [505]]
    assert alone["A"]["conversation"].turns and not alone["B"]["conversation"].turns


def test_a_turn_ends_the_same_after_any_other_turns(alone):
    sequence = ["A", "B", "C", "D", "E", "A", "C", "B", "A", "E", "D", "A"]

    for name in sequence:
        assert outcome(SCENARIOS[name]) == alone[name], name


def test_simultaneous_turns_on_the_shared_graph_end_as_they_do_alone(alone):
    names = list(SCENARIOS) * 4
    barrier = threading.Barrier(len(names))

    results = concurrently([lambda n=name: outcome(SCENARIOS[n], barrier) for name in names])

    for name, result in zip(names, results, strict=True):
        assert result == alone[name], name


def test_each_turn_starts_from_a_new_state():
    first, second = initial_state("a"), initial_state("a")

    assert first == second
    assert first is not second
    assert first["messages"] is not second["messages"]
    # frozen, so nothing a turn does can change another's
    assert first["conversation"] == NO_CONVERSATION
    with pytest.raises(AttributeError):
        first["conversation"].omitted = 1
    assert (first["iteration_count"], first["context_compactions"]) == (0, 0)


def test_the_compiled_graph_keeps_nothing_between_turns():
    # no checkpointer or store: a turn's state is dropped when it ends
    assert coach_graph.checkpointer is None
    assert coach_graph.store is None
    assert coach_graph.config["recursion_limit"] == MAX_GRAPH_STEPS


def test_running_turns_changes_none_of_the_shared_definitions():
    def snapshot():
        return copy.deepcopy(
            {
                "compacted": COMPACTED_RESULT,
                "declarations": [(d.name, d.parameters) for d in TOOL_DECLARATIONS],
                "respond": RESPOND.parameters,
                "policy": {k: (v.decisions, v.data_tools) for k, v in POLICY.items()},
                "safety": {
                    k: (v.fallback_reply, v.respond.parameters, v.decisions)
                    for k, v in SAFETY_POLICY.items()
                },
                "no_conversation": NO_CONVERSATION,
            }
        )

    before = snapshot()
    for scenario in SCENARIOS.values():
        outcome(scenario)

    assert snapshot() == before
    assert isinstance(RESPOND, ToolDeclaration)


def test_the_graph_limit_holds_for_every_turn_however_often_it_is_reached():
    # a context allowing 50 rounds: the compiled graph's step limit stops it
    runaway = Scenario(
        user_id=606,
        message="What is in plan 12?",
        script=tuple(turn(("get_workout_plan", {"plan_id": 12}), number=n) for n in range(60)),
        results={"get_workout_plan": {"output": {"plan_id": 12}}},
        context={"max_tool_iterations": 50},
    )

    runs = [outcome(runaway) for _ in range(5)]

    assert all(run["raised"] == "GraphRecursionError" for run in runs)
    # a coach and a tools step per round: never more steps than the limit
    assert {run["model_requests"] for run in runs} == {(MAX_GRAPH_STEPS + 1) // 2}
    assert issubclass(GraphRecursionError, Exception)
