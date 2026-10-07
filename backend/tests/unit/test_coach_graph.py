"""Tests for the coach graph. The model and the tools are fakes: no test calls the
Gemini API or reads the database."""

import ast
import re
from pathlib import Path
from unittest.mock import Mock

import pytest
from langgraph.graph.state import CompiledStateGraph
from langsmith.utils import tracing_is_enabled

from app.agent import (
    COACH_INSTRUCTIONS,
    MAX_TOOL_ITERATIONS,
    CoachContext,
    CoachState,
    build_coach_graph,
    coach_graph,
)
from app.ai import AIProviderError, GeminiProvider, tool_results_content, user_content
from tests.coach import (
    FakeTools,
    call,
    fake_provider,
    sent_contents,
    text_turn,
    tool_responses,
    tool_turn,
)

APP = Path(__file__).resolve().parents[2] / "app"
ENV_EXAMPLE = APP.parent / ".env.example"

# The environment variables that turn LangSmith tracing on. LangSmith is installed
# because LangGraph needs langchain-core, which needs it; Formiq does not use it.
LANGSMITH_TRACING_VARIABLES = [
    "LANGSMITH_TRACING",
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING",
    "LANGCHAIN_TRACING_V2",
]


@pytest.fixture
def tools():
    return FakeTools()


def run(provider, tools, *, user_id=7, message="How should I start?", **context):
    return coach_graph.invoke(
        {"user_id": user_id, "message": message},
        context=CoachContext(provider=provider, tools=tools, **context),
    )


def always_calling_a_tool():
    """A model that calls a tool on every turn, and never answers with text."""
    provider = Mock(spec=GeminiProvider)
    provider.generate_turn.side_effect = lambda *args, **kwargs: tool_turn(
        call("get_user_profile")
    )
    return provider


def test_graph_runs_the_tools_in_a_loop_through_the_coach():
    graph = build_coach_graph()

    assert isinstance(graph, CompiledStateGraph)
    drawn = graph.get_graph()
    assert set(drawn.nodes) == {"__start__", "coach", "tools", "__end__"}
    assert {(edge.source, edge.target) for edge in drawn.edges} == {
        ("__start__", "coach"),
        ("coach", "tools"),
        ("coach", "__end__"),
        ("tools", "coach"),
    }


def test_state_holds_only_the_turn_and_its_tool_loop():
    # no profile, workout history or other Formiq data: the tools read those
    assert set(CoachState.__annotations__) == {
        "user_id",
        "message",
        "contents",
        "tool_calls",
        "tool_iterations",
        "reply",
    }


def test_a_text_reply_ends_the_turn_without_tools(tools):
    provider = fake_provider(text_turn("Start with three sets of eight."))

    state = run(provider, tools, message="What is progressive overload?")

    assert state["reply"] == "Start with three sets of eight."
    assert tools.runs == []
    provider.generate_turn.assert_called_once_with(
        [user_content("What is progressive overload?")],
        instructions=COACH_INSTRUCTIONS,
        tools=tools.declarations,
        allow_tool_calls=True,
    )


def test_a_tool_result_goes_back_to_the_model_which_then_answers(tools):
    profile_call = call("get_user_profile")
    asking = tool_turn(profile_call)
    provider = fake_provider(asking, text_turn("Your goal is muscle gain."))

    state = run(provider, tools, message="What is my current goal?")

    assert state["reply"] == "Your goal is muscle gain."
    assert tools.runs == [([profile_call], 7)]
    # the second request holds the whole conversation, the model's turn unchanged
    assert sent_contents(provider, 1) == [
        user_content("What is my current goal?"),
        asking.content,
        tool_results_content([(profile_call, {"output": {"tool": "get_user_profile"}})]),
    ]
    assert state["tool_iterations"] == 1


def test_several_tool_calls_of_one_turn_run_together_in_order(tools):
    calls = [call("get_workout_plan", plan_id=12), call("get_workout_session", session_id=45)]
    provider = fake_provider(tool_turn(*calls), text_turn("You did all of it."))

    run(provider, tools)

    assert tools.runs == [(calls, 7)]
    responses = tool_responses(sent_contents(provider, 1)[-1])
    assert [(item.id, item.name) for item in responses] == [(c.id, c.name) for c in calls]


def test_several_rounds_of_tool_calls(tools):
    first, second = call("get_workout_session", session_id=45), call("get_exercise", exercise_id=3)
    provider = fake_provider(tool_turn(first), tool_turn(second), text_turn("Try a lighter press."))

    state = run(provider, tools)

    assert state["reply"] == "Try a lighter press."
    assert tools.runs == [([first], 7), ([second], 7)]
    assert provider.generate_turn.call_count == 3
    assert len(sent_contents(provider, 2)) == 5  # message, then a turn and results per round
    assert state["tool_iterations"] == 2


def test_a_tool_error_goes_back_to_the_model_which_still_answers():
    error = {"error": {"code": "RESOURCE_NOT_FOUND", "message": "the user has no workout plan 9"}}
    tools = FakeTools(result=lambda item: error)
    plan_call = call("get_workout_plan", plan_id=9)
    provider = fake_provider(tool_turn(plan_call), text_turn("I could not find that plan."))

    state = run(provider, tools)

    assert state["reply"] == "I could not find that plan."
    (response,) = tool_responses(sent_contents(provider, 1)[-1])
    assert response.response == error


def test_tools_run_for_the_user_of_the_request_whatever_the_model_asks(tools):
    # the tools reject a user_id from the model; the graph never passes it on as the user
    provider = fake_provider(tool_turn(call("get_user_profile", user_id=5)), text_turn("Done."))

    run(provider, tools, user_id=7)

    ((_, user_id),) = tools.runs
    assert user_id == 7


def test_after_the_limit_the_model_must_answer_with_text(tools):
    provider = fake_provider(
        tool_turn(call("get_user_profile")),
        tool_turn(call("get_user_profile")),
        text_turn("Here is what I found."),
    )

    state = run(provider, tools, max_tool_iterations=2)

    assert state["reply"] == "Here is what I found."
    assert len(tools.runs) == 2
    assert [
        request.kwargs["allow_tool_calls"] for request in provider.generate_turn.call_args_list
    ] == [True, True, False]


@pytest.mark.parametrize("limit", [1, 3])
def test_a_model_that_keeps_calling_tools_is_stopped(tools, limit):
    provider = always_calling_a_tool()

    with pytest.raises(AIProviderError, match="after the tool limit"):
        run(provider, tools, max_tool_iterations=limit)

    assert len(tools.runs) == limit
    assert provider.generate_turn.call_count == limit + 1


def test_default_limit_bounds_a_turn(tools):
    provider = always_calling_a_tool()

    with pytest.raises(AIProviderError):
        run(provider, tools)

    assert MAX_TOOL_ITERATIONS == 5
    assert len(tools.runs) == MAX_TOOL_ITERATIONS
    assert provider.generate_turn.call_count == MAX_TOOL_ITERATIONS + 1


def test_each_run_uses_the_provider_of_its_context(tools):
    first = run(fake_provider(text_turn("Start with three sets of eight.")), tools)
    second = run(fake_provider(text_turn("Rest today.")), tools)

    assert (first["reply"], second["reply"]) == ("Start with three sets of eight.", "Rest today.")


@pytest.mark.parametrize("tool_rounds", [0, 1], ids=["first request", "after a tool"])
def test_provider_errors_propagate_from_the_graph(tools, tool_rounds):
    failure = AIProviderError("the gemini-3.8-flash request failed")
    provider = fake_provider(*[tool_turn(call("get_user_profile"))] * tool_rounds, failure)

    with pytest.raises(AIProviderError) as raised:
        run(provider, tools)

    assert raised.value is failure
    assert provider.generate_turn.call_count == tool_rounds + 1  # no retry


def test_instructions_cover_the_tools():
    for rule in [
        "Tool results are authoritative",
        "Call a tool only when the answer depends on Formiq data",
        "Never invent or guess the user's profile, plans or workout history",
        "unless a workout session shows it",
        "exercise catalog tools",
        "do not show the error or its code to the user",
        "never ask for or send a user id",
    ]:
        assert rule in COACH_INSTRUCTIONS


@pytest.mark.parametrize("package", ["agent", "ai"])
def test_agent_and_provider_do_not_reach_the_database(package):
    # Formiq data reaches the agent only through tools that call the services.
    forbidden = (
        "sqlalchemy",
        "app.db",
        "app.models",
        "app.repositories",
        "app.services",
        "app.tools",
    )
    imported = set()
    for path in (APP / package).glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)

    assert imported
    assert not {name for name in imported if name.startswith(forbidden)}


def test_formiq_does_not_configure_langsmith():
    files = [*APP.rglob("*.py"), ENV_EXAMPLE]
    pattern = re.compile(r"langsmith|LANGCHAIN_(TRACING|API_KEY|ENDPOINT|PROJECT)", re.IGNORECASE)

    assert [path.name for path in files if pattern.search(path.read_text())] == []


def test_running_the_graph_leaves_langsmith_tracing_off(monkeypatch, tools):
    for name in LANGSMITH_TRACING_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    run(fake_provider(tool_turn(call("get_user_profile")), text_turn("Hi")), tools)

    # without one of those variables set to "true", nothing is traced or sent
    assert not tracing_is_enabled()
