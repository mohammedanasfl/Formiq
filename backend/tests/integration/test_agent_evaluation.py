"""The agent evaluation: every dataset case run through the coach (CoachService,
the graph, the policies, the safety backstop and the real tools on the test
database) and judged by the deterministic evaluators.

In the default run the model is each case's script, or a real provider whose
SDK fails as the case says: these tests check what Formiq guarantees whatever
the model does, not how good a real model is. The live run is opt-in:

    LIVE_AGENT_EVAL=1 pytest tests/integration/test_agent_evaluation.py -k live -s

It needs GEMINI_API_KEY (LIVE_AGENT_EVAL_MODEL picks the model), calls Gemini
once or more per live case, and fails only on the guarantees enforced in code
(HARD evaluators); the rest is reported.

They require the local PostgreSQL container to be running.
"""

import os
import time

import pytest

from app.ai import GeminiProvider
from app.core.config import settings
from app.evaluation import (
    CASES,
    HARD,
    create_fixtures,
    evaluate_case,
    format_report,
    live_expectations,
    run_case,
    summarize,
)

LIVE = os.environ.get("LIVE_AGENT_EVAL") == "1"
# a live case the provider could not serve says nothing about the model
UNAVAILABLE = frozenset({"rate_limit", "provider_timeout", "provider_error"})


@pytest.fixture
def fixtures(service_session):
    return create_fixtures(service_session)


@pytest.mark.parametrize("case", CASES, ids=[case.case_id for case in CASES])
def test_case(service_session, fixtures, case):
    result = evaluate_case(case, run_case(case, service_session, fixtures))

    if case.known_gap is not None:
        # strict: once the gap is closed the case passes and must be updated
        assert not result.passed, f"{case.case_id} now passes: remove its known_gap"
        pytest.xfail(case.known_gap)
    assert result.passed, format_report(summarize([result]))


def test_the_dataset_has_no_regressions(service_session, fixtures):
    run = summarize(
        evaluate_case(case, run_case(case, service_session, fixtures)) for case in CASES
    )

    assert run.failed == 0, format_report(run)
    assert run.pass_rate == 1.0
    assert run.total_cases == len(CASES)
    assert run.known_gaps == ()
    # every evaluator judged some case
    assert {name for name, (passed, _) in run.evaluator_summary.items() if passed} >= {
        "intent", "decision", "required_tools", "forbidden_tools", "tool_order",
        "tool_call_count", "model_requests", "safety", "final_status", "termination",
        "refused_calls", "rejections", "compaction", "trusted_identity", "safety_path",
        "resource_limits", "no_leaks", "outcome_recorded", "write_boundary",
    }  # fmt: skip


def test_an_id_from_a_compacted_result_is_grounded_but_is_no_evidence(
    service_session, fixtures
):
    case = next(case for case in CASES if case.case_id == "id_from_compacted_result")
    run = run_case(case, service_session, fixtures)

    assert run.compacted_results > 0
    # exercise 77 appears only in the compacted search, never in the message
    assert "77" not in case.message
    first, last = run.decision_validations[0], run.decision_validations[-1]
    # 2. the compacted search alone cannot support the answer
    assert first.accepted is False
    assert first.rejected_by == "decision_policy"
    assert first.compacted_excluded > 0
    # 1. its id is grounded: the call is not refused and runs
    exercise = [tool for tool in run.tools if tool.name == "get_exercise"]
    assert len(exercise) == 1
    assert exercise[0].executed and exercise[0].error_code is None
    assert exercise[0].data_status == "AVAILABLE"
    # 3. the fresh result is evidence: the same answer is now accepted
    assert last.accepted is True
    assert run.decision == "RETRIEVE_THEN_ANSWER"
    assert run.status == "success"


@pytest.mark.skipif(not LIVE, reason="live evaluation is opt-in: set LIVE_AGENT_EVAL=1")
def test_live_model(service_session, fixtures):
    if settings.gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY is not set")
    provider = GeminiProvider(
        settings.gemini_api_key.get_secret_value(),
        os.environ.get("LIVE_AGENT_EVAL_MODEL", settings.gemini_model),
        timeout_seconds=settings.gemini_timeout_seconds,
    )
    # seconds between cases, to stay within the provider's rate limit
    delay = float(os.environ.get("LIVE_AGENT_EVAL_DELAY", "5"))
    results, unavailable = [], []
    for case in (case for case in CASES if case.live):
        time.sleep(delay)
        observed = run_case(case, service_session, fixtures, provider)
        if observed.status in UNAVAILABLE:
            unavailable.append(f"{case.case_id} ({observed.status})")
            continue
        results.append(evaluate_case(live_expectations(case), observed))

    run = summarize(results)
    print(f"\nlive model: {provider.model}\nunavailable: {unavailable}\n{format_report(run)}")
    hard = [f for f in run.failures if f.evaluator in HARD]
    assert not hard, format_report(run)
