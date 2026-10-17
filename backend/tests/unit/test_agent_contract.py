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
from datetime import timedelta
from pathlib import Path

import pytest

import app
from app.agent import RESPOND, SAFETY_POLICY, CoachState
from app.agent.policy import Respond
from app.ai import ModelTurn, ToolCall
from app.approvals import PROPOSAL_ACTIONS, READ_ACTIONS, WriteAction
from app.tools import TOOL_DECLARATIONS

APP = Path(app.__file__).parent

# Formiq's limits and safety thresholds, as of Phase 4, with the tool budget
# of the live QA fix pass (2026-10-15): one round beyond the limit only to
# correct a refused proposal, and 8 calls run per round (the reads and searches
# a workout needs, together), so a request holds one round of 8 results.
PINNED = {
    "app.agent.graph": {
        "MAX_TOOL_ITERATIONS": 5,
        "PROPOSAL_RETRY_ROUNDS": 1,
        "MAX_REQUESTED_TOOL_CALLS_PER_TURN": 20,
        "MAX_GRAPH_STEPS": 15,
    },
    "app.tools.limits": {
        "MAX_EXECUTED_TOOL_CALLS_PER_TURN": 8,
        "MAX_SEARCH_RESULTS": 10,
        "MAX_OTHER_USE_MATCHES": 3,
        "MAX_EXERCISES": 30,
        "MAX_SETS": 15,
        "MAX_TEXT_LENGTH": 500,
        "MAX_LISTED_PLANS": 20,
        "MAX_SUGGESTIONS": 3,
    },
    "app.agent.context": {
        "MAX_CONTEXT_COMPACTIONS": 7,
        "CONTEXT_MAX_CHARS": 500_000,
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
    # a proposed plan waits this long for the user's approval
    "app.api.dependencies": {"PROPOSAL_TTL": timedelta(minutes=30)},
}

# The only operations a model's call may run: Formiq's reads, and its one
# proposal, which saves nothing. Pinned, so a write slipping into them fails here.
PROPOSALS = {"propose_workout_plan": WriteAction.CREATE_WORKOUT_PLAN}
READS = frozenset(
    {
        "get_user_profile",
        "get_workout_plan",
        "list_workout_plans",
        "get_workout_session",
        "get_current_workout_plan",
        "get_latest_workout_session",
        "get_pending_proposal",
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


def test_the_model_can_reach_only_formiqs_reads_and_its_proposal():
    assert {declaration.name for declaration in TOOL_DECLARATIONS} == READS | set(PROPOSALS)
    assert READ_ACTIONS == READS
    assert PROPOSAL_ACTIONS == PROPOSALS


def test_the_model_controls_only_its_calls_and_its_respond_arguments():
    # what a model returns: calls by name with arguments, and nothing that
    # reaches identity, safety, limits or authorization
    # usage and model are what the provider reported (token counts, the model that
    # answered), for observability only: neither is the model's output
    assert set(ModelTurn.__dataclass_fields__) == {"content", "text", "tool_calls", "usage", "model"}
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
