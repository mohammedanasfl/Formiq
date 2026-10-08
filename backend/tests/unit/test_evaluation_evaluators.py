"""Tests of the evaluation framework itself: the evaluators, the invariants, the
limits they pin and the regression summary, on hand-made results. They run no
agent: whether the coach passes is the agent evaluation's question
(tests/integration/test_agent_evaluation.py)."""

from dataclasses import replace

import pytest

from app.agent import (
    MAX_GRAPH_STEPS,
    MAX_REQUESTED_TOOL_CALLS_PER_TURN,
    MAX_TOOL_ITERATIONS,
)
from app.agent.context import (
    CONTEXT_KEEP_RECENT_TURNS,
    CONTEXT_MAX_CHARS,
    CONTEXT_MAX_CONVERSATION_CHARS,
    CONTEXT_MAX_TURN_CHARS,
    MAX_CONTEXT_COMPACTIONS,
    MAX_TOOL_RESULT_CHARS,
)
from app.agent.policy import MAX_REPLY_LENGTH
from app.evaluation import EXPECTED_LIMITS, evaluate_case, format_report, summarize
from app.evaluation.evaluators import (
    check_no_leaks,
    check_outcome_recorded,
    check_resource_limits,
    check_safety_path_reads_nothing,
    check_trusted_identity,
    evaluate_compaction,
    evaluate_decision,
    evaluate_final_status,
    evaluate_forbidden_tools,
    evaluate_intent,
    evaluate_model_requests,
    evaluate_refused_calls,
    evaluate_rejections,
    evaluate_required_tools,
    evaluate_safety,
    evaluate_termination,
    evaluate_tool_call_count,
    evaluate_tool_order,
)
from app.evaluation.models import (
    Bounds,
    CaseResult,
    EvalCase,
    EvaluatorResult,
    ExecutionResult,
    Overrides,
    ToolRecord,
    ValidationRecord,
    exactly,
)
from app.schemas.coach import MAX_HISTORY_TEXT_LENGTH, MAX_HISTORY_TURNS
from app.tools.limits import (
    MAX_EXECUTED_TOOL_CALLS_PER_TURN,
    MAX_EXERCISES,
    MAX_SEARCH_RESULTS,
    MAX_SETS,
    MAX_TEXT_LENGTH,
)

USER = 7
PROFILE = ToolRecord("get_user_profile", True, data_status="AVAILABLE")
PLAN = ToolRecord("get_workout_plan", True, data_status="AVAILABLE")


def case(**expectations) -> EvalCase:
    return EvalCase(case_id="c", description="d", message="m", **expectations)


def run(**overrides) -> ExecutionResult:
    """A clean run: a profile question answered from the profile."""
    base = ExecutionResult(
        status="success",
        termination="decision_accepted",
        intent="PROFILE",
        decision="RETRIEVE_THEN_ANSWER",
        safety_category="SAFE",
        safety_path=None,
        tools=(PROFILE,),
        rounds=((1, 1),),
        model_requests=2,
        provider_attempts=2,
        iterations=1,
        compactions=0,
        compacted_results=0,
        decision_validations=(ValidationRecord(True),),
        reply_validations=(ValidationRecord(True),),
        tool_user_ids=(USER,),
        trusted_user_id=USER,
        error=None,
        error_leaks_cause=False,
        reply_chars=12,
        reply_is_fixed_safe_reply=False,
        reply_repeats_instructions=False,
        trace_complete=True,
    )
    return replace(base, **overrides)


def check(evaluator, expectation: EvalCase, result: ExecutionResult) -> EvaluatorResult:
    verdict = evaluator(expectation, result)
    assert verdict is not None
    return verdict


# --- each evaluator: not applicable, passing, failing with its reason ---


@pytest.mark.parametrize(
    ("evaluator", "expectation", "good", "bad", "reason"),
    [
        (evaluate_intent, case(expected_intent="PROFILE"), run(), run(intent="GENERAL_FITNESS"), "intent differs"),
        (evaluate_decision, case(expected_decision="RETRIEVE_THEN_ANSWER"), run(), run(decision="ANSWER"), "decision differs"),
        (
            evaluate_required_tools,
            case(required_tools=("get_user_profile",)),
            run(),
            run(tools=(replace(PROFILE, data_status="MISSING"),)),
            "no data from: get_user_profile",
        ),
        (
            evaluate_forbidden_tools,
            case(forbidden_tools=("get_workout_plan",)),
            run(),
            run(tools=(PROFILE, PLAN)),
            "forbidden tools ran: get_workout_plan",
        ),
        (
            evaluate_tool_order,
            case(expected_tool_order=("get_user_profile", "get_workout_plan")),
            run(tools=(PROFILE, PLAN)),
            run(tools=(PLAN, PROFILE)),
            "different order",
        ),
        (evaluate_tool_call_count, case(executed_tool_calls=exactly(1)), run(), run(tools=(PROFILE, PLAN)), "out of bounds"),
        (evaluate_model_requests, case(model_requests=Bounds(1, 2)), run(), run(model_requests=3), "out of bounds"),
        (evaluate_final_status, case(expected_status="success"), run(), run(status="cannot_answer"), "different status"),
        (evaluate_termination, case(expected_termination="decision_accepted"), run(), run(termination="retry_limit_reached"), "different reason"),
        (
            evaluate_refused_calls,
            case(expected_refused_calls=(("get_workout_plan", "ID_NOT_GROUNDED"),)),
            run(tools=(ToolRecord("get_workout_plan", False, "id_not_grounded", "ID_NOT_GROUNDED"),)),
            run(tools=(PLAN,)),
            "not refused as expected",
        ),
        (
            evaluate_rejections,
            case(decision_rejections=exactly(1)),
            run(decision_validations=(ValidationRecord(False, "decision_policy"), ValidationRecord(True))),
            run(),
            "out of bounds",
        ),
        (
            evaluate_compaction,
            case(expect_compacted_evidence_excluded=True),
            run(decision_validations=(ValidationRecord(False, "decision_policy", 1), ValidationRecord(True))),
            run(decision_validations=(ValidationRecord(True, None, 1),)),
            "compacted evidence was not rejected",
        ),
        (evaluate_compaction, case(compactions=exactly(0)), run(), run(compactions=2), "compaction count"),
    ],
    ids=lambda value: getattr(value, "__name__", None),
)
def test_an_evaluator_passes_the_expected_and_fails_the_rest(evaluator, expectation, good, bad, reason):
    assert evaluator(case(), good) is None
    passing = check(evaluator, expectation, good)
    assert passing.passed and passing.reason == ""
    failing = check(evaluator, expectation, bad)
    assert not failing.passed
    assert reason in failing.reason
    assert failing.expected is not None and failing.actual is not None


SAFE_REDIRECT = run(
    intent="SAFETY_SENSITIVE",
    decision="SAFE_REDIRECT",
    safety_category="PAIN_OR_INJURY",
    safety_path="fixed_safe_response",
    status="safety_redirect",
    tools=(),
    rounds=(),
    tool_user_ids=(),
)


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (replace(SAFE_REDIRECT, safety_category="SAFE"), "classified the request differently"),
        (replace(SAFE_REDIRECT, safety_path="model"), "safety path differs"),
        (replace(SAFE_REDIRECT, decision="ANSWER"), "reached normal answer path (ANSWER)"),
        (replace(SAFE_REDIRECT, tools=(PROFILE,)), "read Formiq data"),
    ],
)
def test_the_safety_evaluator_names_what_went_wrong(bad, reason):
    expectation = case(expected_safety_category="PAIN_OR_INJURY", expected_safety_path="fixed_safe_response")

    assert check(evaluate_safety, expectation, SAFE_REDIRECT).passed
    failing = check(evaluate_safety, expectation, bad)
    assert not failing.passed and reason in failing.reason


# --- the invariants, on every case ---


@pytest.mark.parametrize(
    ("invariant", "bad", "reason"),
    [
        (check_trusted_identity, run(tool_user_ids=(USER, 999)), "other users: [999]"),
        (check_safety_path_reads_nothing, replace(SAFE_REDIRECT, tools=(PROFILE,)), "ran data tools"),
        (check_safety_path_reads_nothing, replace(SAFE_REDIRECT, decision="RETRIEVE_THEN_ANSWER"), "ended with RETRIEVE_THEN_ANSWER"),
        (check_safety_path_reads_nothing, replace(SAFE_REDIRECT, status="success"), "status success"),
        (check_resource_limits, run(model_requests=7, provider_attempts=7), "7 model requests > 6"),
        (check_resource_limits, run(provider_attempts=3), "a retry"),
        (check_resource_limits, run(rounds=((6, 6),)), "6 tool calls executed in one round"),
        (check_resource_limits, run(rounds=((21, 5),)), "21 tool calls requested"),
        (check_resource_limits, run(compactions=7), "7 compactions"),
        (
            check_resource_limits,
            run(decision_validations=(ValidationRecord(False),) * 7, model_requests=6, provider_attempts=6),
            "7 rejections retried",
        ),
        (check_no_leaks, run(error="provider_error", error_leaks_cause=True), "carries its cause"),
        (check_no_leaks, run(reply_repeats_instructions=True), "repeats Formiq's instructions"),
        (check_outcome_recorded, run(trace_complete=False), "no complete outcome"),
        (check_outcome_recorded, run(status=None), "no complete outcome"),
        (check_outcome_recorded, run(error="provider_timeout", status="success"), "recorded as success"),
        (check_outcome_recorded, run(status="provider_error"), "answered request was recorded as provider_error"),
    ],
)
def test_an_invariant_fails_a_run_that_breaks_it(invariant, bad, reason):
    assert invariant(case(), run()).passed
    failing = invariant(case(), bad)
    assert not failing.passed
    assert reason in failing.reason


def test_the_limits_follow_a_cases_overrides():
    raised = case(overrides=Overrides(tool_iterations=50))

    assert check_resource_limits(raised, run(model_requests=9, provider_attempts=9)).passed
    assert not check_resource_limits(case(), run(model_requests=9, provider_attempts=9)).passed


def test_a_failed_request_with_its_status_is_recorded_honestly():
    failed = run(status="provider_timeout", error="provider_timeout", tools=(), tool_user_ids=())

    assert check_outcome_recorded(case(), failed).passed


def test_every_case_is_judged_by_the_invariants():
    result = evaluate_case(case(), run())

    assert [r.name for r in result.results] == [
        "trusted_identity", "safety_path", "resource_limits", "no_leaks", "outcome_recorded",
    ]  # fmt: skip
    assert result.passed


# --- the pinned limits ---


def test_the_pinned_limits_are_the_production_limits():
    # a limit raised in the code fails here, and every case's resource check
    # keeps holding the old one until this pin is changed on purpose
    assert EXPECTED_LIMITS == {
        "MAX_TOOL_ITERATIONS": MAX_TOOL_ITERATIONS,
        "MAX_REQUESTED_TOOL_CALLS_PER_TURN": MAX_REQUESTED_TOOL_CALLS_PER_TURN,
        "MAX_EXECUTED_TOOL_CALLS_PER_TURN": MAX_EXECUTED_TOOL_CALLS_PER_TURN,
        "MAX_GRAPH_STEPS": MAX_GRAPH_STEPS,
        "MAX_CONTEXT_COMPACTIONS": MAX_CONTEXT_COMPACTIONS,
        "CONTEXT_MAX_CHARS": CONTEXT_MAX_CHARS,
        "CONTEXT_KEEP_RECENT_TURNS": CONTEXT_KEEP_RECENT_TURNS,
        "CONTEXT_MAX_TURN_CHARS": CONTEXT_MAX_TURN_CHARS,
        "CONTEXT_MAX_CONVERSATION_CHARS": CONTEXT_MAX_CONVERSATION_CHARS,
        "MAX_TOOL_RESULT_CHARS": MAX_TOOL_RESULT_CHARS,
        "MAX_HISTORY_TURNS": MAX_HISTORY_TURNS,
        "MAX_HISTORY_TEXT_LENGTH": MAX_HISTORY_TEXT_LENGTH,
        "MAX_REPLY_LENGTH": MAX_REPLY_LENGTH,
        "MAX_SEARCH_RESULTS": MAX_SEARCH_RESULTS,
        "MAX_EXERCISES": MAX_EXERCISES,
        "MAX_SETS": MAX_SETS,
        "MAX_TEXT_LENGTH": MAX_TEXT_LENGTH,
    }


# --- the regression summary ---


def verdict(name: str, passed: bool) -> EvaluatorResult:
    return EvaluatorResult(name, passed, "expected", "actual", "" if passed else "why")


def test_the_summary_counts_cases_and_evaluators_and_names_each_failure():
    results = [
        CaseResult("a", (verdict("intent", True), verdict("safety", True))),
        CaseResult("b", (verdict("intent", True), verdict("safety", False))),
        CaseResult("gap", (verdict("refused_calls", False),), known_gap="documented"),
    ]

    summary = summarize(results)

    assert (summary.total_cases, summary.passed, summary.failed) == (3, 2, 1)
    assert summary.pass_rate == pytest.approx(2 / 3)
    assert summary.evaluator_summary == {"intent": (2, 0), "refused_calls": (0, 1), "safety": (1, 1)}
    ((failure),) = summary.failures
    assert (failure.case_id, failure.evaluator, failure.reason) == ("b", "safety", "why")
    assert summary.known_gaps == ("gap",)
    report = format_report(summary)
    assert "FAIL\ncase: b\nevaluator: safety\nexpected: expected\nactual: actual\nreason: why" in report


def test_a_known_gap_that_passes_is_reported_as_fixed():
    summary = summarize([CaseResult("gap", (verdict("refused_calls", True),), known_gap="documented")])

    assert summary.fixed_gaps == ("gap",)
    assert summary.failed == 1
    assert "known gaps that now pass" in format_report(summary)


def test_a_live_run_drops_only_what_depends_on_the_model():
    from app.evaluation import live_expectations

    scripted = case(
        expected_intent="PROFILE",
        expected_decision="RETRIEVE_THEN_ANSWER",
        expected_safety_category="SAFE",
        expected_safety_path="model",
        expected_status="success",
        forbidden_tools=("get_exercise",),
        required_tools=("get_user_profile",),
        expected_refused_calls=(("get_workout_plan", "ID_NOT_GROUNDED"),),
        decision_rejections=exactly(1),
        reply_rejections=exactly(0),
        model_requests=exactly(2),
        executed_tool_calls=exactly(1),
    )

    live = live_expectations(scripted)

    assert (live.expected_safety_path, live.expected_refused_calls) == (None, ())
    assert (live.decision_rejections, live.reply_rejections) == (None, None)
    assert (live.model_requests, live.executed_tool_calls) == (None, None)
    # what Formiq decides in code, and what the model must get right, stay
    assert live.expected_safety_category == "SAFE"
    assert live.forbidden_tools == ("get_exercise",)
    assert live.expected_status == "success"
    assert live.required_tools == ("get_user_profile",)
    assert live.expected_decision == "RETRIEVE_THEN_ANSWER"


def test_a_live_safety_case_accepts_any_safe_decision():
    from app.evaluation import live_expectations

    flagged = case(
        expected_safety_category="INSUFFICIENT_SAFETY_CONTEXT",
        expected_decision="ASK_CLARIFICATION",
        expected_status="safety_redirect",
    )
    redirected = run(
        intent="SAFETY_SENSITIVE",
        decision="SAFE_REDIRECT",
        safety_category="INSUFFICIENT_SAFETY_CONTEXT",
        safety_path="model",
        status="safety_redirect",
        tools=(),
        tool_user_ids=(),
    )

    assert not evaluate_case(flagged, redirected).passed
    assert evaluate_case(live_expectations(flagged), redirected).passed
    # an answer is still a failure, live or not
    answered = replace(redirected, decision="ANSWER")
    assert not evaluate_case(live_expectations(flagged), answered).passed
