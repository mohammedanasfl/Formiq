"""The agent's critical invariants, pinned in code (docs/agent-production-contract.md
describes them; it is not checked word for word against the code).

The limits and safety thresholds are pinned here rather than read from the code
they check: a change to one of them fails until it is made here too, on
purpose. The rest are cross-cutting rules no other test holds: what the model
controls, which operations it can reach, and what observability and the
approval boundary can reach.
"""

import ast
import importlib
from pathlib import Path

import pytest

import app
from app.agent import RESPOND, SAFETY_POLICY, CoachState
from app.agent.policy import Respond
from app.ai import ModelTurn, ToolCall
from app.approvals import READ_ACTIONS
from app.tools import TOOL_DECLARATIONS

APP = Path(app.__file__).parent

# Formiq's limits and safety thresholds, as of Phase 4.
PINNED = {
    "app.agent.graph": {
        "MAX_TOOL_ITERATIONS": 5,
        "MAX_REQUESTED_TOOL_CALLS_PER_TURN": 20,
        "MAX_GRAPH_STEPS": 13,
    },
    "app.tools.limits": {
        "MAX_EXECUTED_TOOL_CALLS_PER_TURN": 5,
        "MAX_SEARCH_RESULTS": 10,
        "MAX_EXERCISES": 30,
        "MAX_SETS": 15,
        "MAX_TEXT_LENGTH": 500,
    },
    "app.agent.context": {
        "MAX_CONTEXT_COMPACTIONS": 6,
        "CONTEXT_MAX_CHARS": 350_000,
        "CONTEXT_KEEP_RECENT_TURNS": 6,
        "CONTEXT_MAX_TURN_CHARS": 1_000,
        "CONTEXT_MAX_CONVERSATION_CHARS": 8_000,
        "MAX_TOOL_RESULT_CHARS": 50_000,
    },
    "app.schemas.coach": {"MAX_HISTORY_TURNS": 50, "MAX_HISTORY_TEXT_LENGTH": 8_000},
    "app.agent.policy": {"MAX_REPLY_LENGTH": 8_000},
    "app.agent.safety": {
        "MAX_WEEKLY_LOSS_KG": 2.0,
        "MIN_DAILY_CALORIES": 800,
        "MAX_FAST_HOURS": 72,
    },
}

# The only operations a model's call may run: Formiq's reads. Pinned, so a write
# slipping into them fails here.
READS = frozenset(
    {
        "get_user_profile",
        "get_workout_plan",
        "get_workout_session",
        "get_current_workout_plan",
        "get_latest_workout_session",
        "get_exercise",
        "search_exercises",
    }
)


def imported_modules(package: str) -> set[str]:
    names = set()
    for path in (APP / package).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
    return names


@pytest.mark.parametrize("module", PINNED)
def test_the_pinned_limits_are_the_production_limits(module):
    actual = {name: getattr(importlib.import_module(module), name) for name in PINNED[module]}

    assert actual == PINNED[module]


def test_the_model_can_reach_only_formiqs_reads():
    assert {declaration.name for declaration in TOOL_DECLARATIONS} == READS
    assert READ_ACTIONS == READS


def test_the_model_controls_only_its_calls_and_its_respond_arguments():
    # what a model returns: calls by name with arguments, and nothing that
    # reaches identity, safety, limits or authorization
    assert set(ModelTurn.__dataclass_fields__) == {"content", "text", "tool_calls", "usage"}
    assert set(ToolCall.__dataclass_fields__) == {"name", "arguments", "id"}
    # its decision is an intent, a decision and a reply, from fixed enums
    for declaration in (RESPOND, *(policy.respond for policy in SAFETY_POLICY.values())):
        assert set(declaration.parameters["properties"]) == {"intent", "decision", "reply"}
    assert Respond.model_config["extra"] == "forbid"
    # the state a turn's output lands in holds no identity, safety or authority
    for key in CoachState.__annotations__:
        assert not any(
            word in key for word in ("user_id", "safety", "approv", "authoriz", "limit")
        ), key


def test_observability_cannot_reach_what_it_could_change():
    forbidden = (
        "app.agent",
        "app.tools",
        "app.services",
        "app.repositories",
        "app.db",
        "app.models",
        "app.approvals",
        "app.api",
        "sqlalchemy",
    )
    imported = imported_modules("observability")
    assert imported
    assert sorted(name for name in imported if name.startswith(forbidden)) == []


def test_no_production_code_reads_a_trace_back():
    # a trace is written to, never read: no decision can depend on it
    readers = []
    for path in APP.rglob("*.py"):
        if "observability" in path.relative_to(APP).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Attribute)
                and node.attr in {"counts", "status"}
                and "trace" in ast.unparse(node.value)
            ):
                readers.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert readers == []


def test_the_approval_boundary_reaches_no_data():
    forbidden = (
        "sqlalchemy",
        "app.db",
        "app.models",
        "app.repositories",
        "app.services",
        "app.tools",
        "app.api",
    )
    imported = imported_modules("approvals")
    assert imported
    assert sorted(name for name in imported if name.startswith(forbidden)) == []
