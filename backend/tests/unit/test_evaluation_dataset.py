"""Tests of the evaluation dataset and runner pieces that need no database: the
cases are well formed, cover what they must, hold no secrets, and their scripts
and canned tools behave as the runner says."""

import re
from string import Formatter

import pytest

from app.agent import Decision, Intent, SafetyCategory, assess_safety
from app.evaluation import CASES
from app.evaluation.dataset import DATA_TOOLS
from app.evaluation.fixtures import OTHER_EMAIL, USER_EMAIL, Fixtures
from app.evaluation.models import CallTools, Respond
from app.evaluation.runner import (
    CannedTools,
    ScriptExhausted,
    _executed,
    fill,
    scripted_provider,
)
from app.tools import TOOL_DECLARATIONS

TOOLS = {tool.name for tool in TOOL_DECLARATIONS}
NAMES = Fixtures(
    user_id=1,
    other_user_id=2,
    plan_id=10,
    injected_plan_id=11,
    session_id=20,
    other_plan_id=12,
    other_session_id=21,
    bench_id=1,
    squat_id=6,
).names()
STATUSES = {
    "success", "clarification", "safety_redirect", "cannot_answer", "provider_not_configured",
    "provider_timeout", "provider_error", "rate_limit", "model_output_invalid",
    "graph_limit_exceeded", "user_not_found",
}  # fmt: skip


def test_case_ids_are_unique():
    ids = [case.case_id for case in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES, ids=[case.case_id for case in CASES])
def test_a_case_is_well_formed(case):
    assert case.expected_intent in (None, *Intent)
    assert case.expected_decision in (None, *Decision)
    assert case.expected_safety_category in (None, *SafetyCategory)
    assert case.expected_status in (None, *STATUSES)
    for tool in (*case.required_tools, *case.forbidden_tools, *(t for t, _ in case.expected_refused_calls)):
        assert tool in TOOLS
    for turn in case.script:
        if isinstance(turn, CallTools):
            assert all(call.name in TOOLS for call in turn.calls)
        if isinstance(turn, Respond):
            assert turn.intent in Intent and turn.decision in Decision
    # every fixture it names exists
    texts = [case.message, *(text for _, text in case.history)]
    names = {field for text in texts for _, field, _, _ in Formatter().parse(text) if field}
    assert names <= NAMES.keys()
    # a deterministic run has a model to play, or needs none
    assert case.script or case.provider_failure or case.user == "missing" or case.overrides.context_chars


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case.expected_safety_category],
    ids=[case.case_id for case in CASES if case.expected_safety_category],
)
def test_a_cases_safety_expectation_is_the_deterministic_classification(case):
    message = case.message.format_map(NAMES)
    assert assess_safety(message).category == case.expected_safety_category
    if case.expected_safety_category != "SAFE":
        assert set(case.forbidden_tools) == set(DATA_TOOLS)
        assert case.expected_status == "safety_redirect"


def test_the_dataset_covers_every_area():
    tags = {tag for case in CASES for tag in case.tags}
    assert {
        "general", "profile", "history", "exercise", "ambiguous", "safety", "false_positive",
        "bypass", "injection", "tool_result", "extraction", "identity", "id_grounding",
        "ownership", "compaction", "trajectory", "failure", "provider", "tools", "limits",
    } <= tags  # fmt: skip
    categories = {case.expected_safety_category for case in CASES} - {None}
    assert categories == set(SafetyCategory)
    statuses = {case.expected_status for case in CASES} - {None}
    assert statuses == STATUSES


def test_live_cases_need_nothing_but_a_model():
    for case in (case for case in CASES if case.live):
        assert case.provider_failure is None
        assert case.canned_tools is None
        assert case.overrides.context_chars is None and case.overrides.graph_steps is None
        assert case.known_gap is None


def test_no_case_is_an_expected_failure():
    # every case follows an approved contract
    assert [case.case_id for case in CASES if case.known_gap] == []


def test_the_dataset_holds_no_secrets_or_real_contacts():
    text = repr(CASES)
    assert not re.search(r"AIza|sk-lf-|pk-lf-|sk-[A-Za-z0-9]{20}", text)
    assert not re.search(r"[\w.+-]+@[\w-]+\.(com|net|org|io)\b", text)
    assert USER_EMAIL.endswith(".test") and OTHER_EMAIL.endswith(".test")


# --- runner pieces ---


def test_fill_turns_fixture_names_into_ids():
    assert fill("{plan_id}", NAMES) == 10
    assert fill("plan {plan_id} and session {session_id}", NAMES) == "plan 10 and session 20"
    assert fill({"plan_id": "{plan_id}", "x": [1, "{session_id}"]}, NAMES) == {
        "plan_id": 10,
        "x": [1, 20],
    }
    assert fill(42, NAMES) == 42


def test_a_scripted_model_plays_its_turns_then_stops():
    provider = scripted_provider(
        (CallTools(()), Respond("GENERAL_FITNESS", "ANSWER", "Hi")), NAMES
    )

    first = provider.generate_turn()
    second = provider.generate_turn()

    assert first.tool_calls == ()
    assert second.tool_calls[0].name == "respond"
    assert second.tool_calls[0].arguments["decision"] == "ANSWER"
    with pytest.raises(ScriptExhausted):
        provider.generate_turn()


def test_canned_tools_keep_the_per_turn_limit_and_record_the_user():
    from app.ai import ToolCall

    users: list[int] = []
    tools = CannedTools({"get_exercise": {"output": {"exercise_id": 1}}}, users)

    results = tools.run([ToolCall("get_exercise", {})] * 6 + [ToolCall("nope", {})], user_id=7)

    assert results[:5] == [{"output": {"exercise_id": 1}}] * 5
    assert {r["error"]["code"] for r in results[5:]} == {"TOOL_LIMIT_REACHED"}
    assert users == [7]


def test_a_call_refused_for_the_limit_was_not_executed():
    assert _executed({"executed": True})
    assert _executed({"executed": True, "error_code": "INVALID_INPUT"})
    assert not _executed({"executed": True, "error_code": "TOOL_LIMIT_REACHED"})
    assert not _executed({"executed": False, "error_code": "ID_NOT_GROUNDED"})


def test_production_code_never_imports_the_evaluation():
    import ast
    from pathlib import Path

    app = Path(__file__).resolve().parents[2] / "app"
    for path in app.rglob("*.py"):
        if "evaluation" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            assert not any(name.startswith("app.evaluation") for name in names), path
