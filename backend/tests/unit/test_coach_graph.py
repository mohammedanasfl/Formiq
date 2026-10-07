"""Tests for the coach graph. The model is a mock: no test calls the Gemini API."""

import ast
import re
from pathlib import Path
from unittest.mock import Mock

import pytest
from langgraph.graph.state import CompiledStateGraph
from langsmith.utils import tracing_is_enabled

from app.agent import COACH_INSTRUCTIONS, CoachContext, CoachState, build_coach_graph, coach_graph
from app.ai import AIProviderError, GeminiProvider

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
def provider():
    provider = Mock(spec=GeminiProvider)
    provider.generate.return_value = "Start with three sets of eight."
    return provider


def test_graph_compiles_to_start_coach_end():
    graph = build_coach_graph()

    assert isinstance(graph, CompiledStateGraph)
    drawn = graph.get_graph()
    assert set(drawn.nodes) == {"__start__", "coach", "__end__"}
    assert {(edge.source, edge.target) for edge in drawn.edges} == {
        ("__start__", "coach"),
        ("coach", "__end__"),
    }


def test_state_holds_only_the_turn():
    # no profile, workout history or other Formiq data: tools will read those
    assert set(CoachState.__annotations__) == {"user_id", "message", "reply"}


def test_coach_node_replies_with_the_models_answer(provider):
    state = coach_graph.invoke(
        {"user_id": 7, "message": "How should I start?"}, context=CoachContext(provider=provider)
    )

    assert state == {
        "user_id": 7,
        "message": "How should I start?",
        "reply": "Start with three sets of eight.",
    }
    provider.generate.assert_called_once_with(
        "How should I start?", instructions=COACH_INSTRUCTIONS
    )


def test_each_run_uses_the_provider_of_its_context(provider):
    other = Mock(spec=GeminiProvider)
    other.generate.return_value = "Rest today."

    first = coach_graph.invoke({"user_id": 1, "message": "Hi"}, context=CoachContext(provider))
    second = coach_graph.invoke({"user_id": 1, "message": "Hi"}, context=CoachContext(other))

    assert (first["reply"], second["reply"]) == ("Start with three sets of eight.", "Rest today.")


def test_provider_errors_propagate_from_the_graph(provider):
    failure = AIProviderError("the gemini-3.8-flash request failed")
    provider.generate.side_effect = failure

    with pytest.raises(AIProviderError) as raised:
        coach_graph.invoke({"user_id": 1, "message": "Hi"}, context=CoachContext(provider))

    assert raised.value is failure
    provider.generate.assert_called_once()  # no retry


@pytest.mark.parametrize("package", ["agent", "ai"])
def test_agent_and_provider_do_not_reach_the_database(package):
    # Formiq data will reach the agent only through tools that call the services.
    forbidden = ("sqlalchemy", "app.db", "app.models", "app.repositories", "app.services")
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


def test_running_the_graph_leaves_langsmith_tracing_off(monkeypatch, provider):
    for name in LANGSMITH_TRACING_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    coach_graph.invoke({"user_id": 1, "message": "Hi"}, context=CoachContext(provider))

    # without one of those variables set to "true", nothing is traced or sent
    assert not tracing_is_enabled()
