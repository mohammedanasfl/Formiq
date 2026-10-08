"""The agent production contract (docs/agent-production-contract.md) against
the code: what it says the limits, thresholds and categories are, they are;
every module and test it cites as enforcement exists; and the few
cross-cutting rules no other test pinned hold.

The document repeats values, it does not define them: each is defined once,
in the module the document names, and a change on either side alone fails
here.
"""

import ast
import importlib
import re
import typing
from enum import StrEnum
from pathlib import Path

import pytest

import app
from app.agent import (
    RESPOND,
    SAFETY_POLICY,
    CoachState,
    Decision,
    Intent,
    SafetyCategory,
)
from app.agent.graph import (
    DECISION_REJECTED,
    ID_NOT_GROUNDED,
    UNKNOWN_TOOL,
    WRITE_NOT_AUTHORIZED,
)
from app.agent.policy import Respond
from app.ai import ModelTurn, ToolCall
from app.approvals import (
    READ_ACTIONS,
    ApprovalState,
    AuthorizationFailure,
    WriteAction,
)
from app.evaluation import EXPECTED_LIMITS, HARD
from app.observability import Failure
from app.observability.tracing import SUCCESS_STATUSES, WARNING_STATUSES
from app.schemas.coach import CoachMessageText
from app.tools import ToolErrorCode

APP = Path(app.__file__).parent
BACKEND = APP.parent
CONTRACT = BACKEND.parent / "docs" / "agent-production-contract.md"

# a table row: | `NAME` | value | `app.module` | ...
_ROW = re.compile(
    r"^\| `([A-Z][A-Z0-9_]*)` \| ([0-9][0-9_,.]*) \| `(app(?:\.\w+)+)` \|", re.MULTILINE
)
_TEST_REFERENCE = re.compile(r"`(tests/[\w/]+\.py)::(test_\w+)`")
_PATH_REFERENCE = re.compile(r"`(app/[\w/]+\.py)`")


@pytest.fixture(scope="module")
def contract() -> str:
    return CONTRACT.read_text()


def documented(contract: str) -> set[str]:
    """Everything the contract names in code formatting."""
    return set(re.findall(r"`([^`\n]+)`", contract))


def number(text: str) -> float:
    return float(text.replace(",", "").replace("_", ""))


def imported_modules(package: str) -> set[str]:
    names = set()
    for path in (APP / package).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
    return names


# --- the document against the code ---


def test_the_documented_limits_are_the_production_limits(contract):
    rows = _ROW.findall(contract)
    assert rows, "the contract's limit tables were not found"
    for name, value, module in rows:
        actual = getattr(importlib.import_module(module), name)
        assert number(value) == actual, (
            f"{module}.{name} is {actual}, the contract says {value}"
        )
    names = {name for name, _, _ in rows}
    # every limit the evaluation pins, every safety guardrail and the trace bounds
    required = {
        *EXPECTED_LIMITS,
        "MAX_WEEKLY_LOSS_KG",
        "MIN_DAILY_CALORIES",
        "MAX_FAST_HOURS",
    }
    assert required <= names, f"undocumented: {sorted(required - names)}"
    assert {
        ("MAX_VALUE_CHARS", "app.observability.tracing"),
        ("MAX_LIST_ITEMS", "app.observability.tracing"),
    } <= {(name, module) for name, _, module in rows}


def test_the_documented_message_limit_is_the_apis():
    (constraints,) = [
        m for m in typing.get_args(CoachMessageText)[1:] if hasattr(m, "max_length")
    ]
    assert constraints.max_length == 4000


def test_the_message_limit_is_documented(contract):
    assert "The current message is at most 4000 characters" in contract


def test_every_failure_category_is_documented(contract):
    names = documented(contract)
    assert {*Failure} <= names, f"undocumented: {sorted(set(Failure) - names)}"
    assert SUCCESS_STATUSES | WARNING_STATUSES <= names


@pytest.mark.parametrize(
    "category",
    [
        Intent,
        Decision,
        SafetyCategory,
        ApprovalState,
        AuthorizationFailure,
        WriteAction,
        ToolErrorCode,
    ],
    ids=lambda category: category.__name__,
)
def test_every_category_is_documented(contract, category: type[StrEnum]):
    # by its name as the code spells it, or by its value as a trace records it
    names = documented(contract)
    missing = [member for member in category if not {member.name, member.value} & names]
    assert missing == []


def test_every_read_and_every_graph_error_code_is_documented(contract):
    names = documented(contract)
    assert READ_ACTIONS <= names
    assert {
        ID_NOT_GROUNDED,
        WRITE_NOT_AUTHORIZED,
        DECISION_REJECTED,
        UNKNOWN_TOOL,
    } <= names


def test_the_documented_hard_evaluators_are_the_hard_set(contract):
    start = contract.index("The `HARD` evaluators must")
    end = contract.index("\n- **", start)
    listed = set(re.findall(r"^  - `(\w+)`$", contract[start:end], re.MULTILINE))
    assert listed == HARD


def test_every_cited_test_exists(contract):
    references = _TEST_REFERENCE.findall(contract)
    assert len(references) > 50
    missing = []
    for file, name in references:
        path = BACKEND / file
        defined = (
            {
                node.name
                for node in ast.parse(path.read_text()).body
                if isinstance(node, ast.FunctionDef)
            }
            if path.exists()
            else set()
        )
        if name not in defined:
            missing.append(f"{file}::{name}")
    assert missing == []


def test_every_cited_module_exists(contract):
    paths = set(_PATH_REFERENCE.findall(contract))
    assert paths
    assert [path for path in sorted(paths) if not (BACKEND / path).exists()] == []


# --- the cross-cutting rules ---


def test_the_model_controls_only_its_calls_and_its_respond_arguments():
    # what a model returns: calls by name with arguments, and nothing that
    # reaches identity, safety, limits or authorization
    assert {field for field in ModelTurn.__dataclass_fields__} == {
        "content",
        "text",
        "tool_calls",
        "usage",
    }
    assert {field for field in ToolCall.__dataclass_fields__} == {
        "name",
        "arguments",
        "id",
    }
    # its decision is an intent, a decision and a reply, from fixed enums
    for declaration in (
        RESPOND,
        *(policy.respond for policy in SAFETY_POLICY.values()),
    ):
        assert set(declaration.parameters["properties"]) == {
            "intent",
            "decision",
            "reply",
        }
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
        "app.evaluation",
        "sqlalchemy",
    )
    imported = imported_modules("observability")
    assert imported
    assert sorted(name for name in imported if name.startswith(forbidden)) == []


def test_no_production_code_reads_a_trace_back():
    # a trace is written to, never read: no decision can depend on it
    readers = []
    for path in APP.rglob("*.py"):
        if {"observability", "evaluation"} & set(path.relative_to(APP).parts):
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
        "app.evaluation",
    )
    imported = imported_modules("approvals")
    assert imported
    assert sorted(name for name in imported if name.startswith(forbidden)) == []
