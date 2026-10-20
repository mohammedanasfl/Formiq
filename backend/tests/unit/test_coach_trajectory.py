"""The trajectory of a coach turn (app.observability.trajectory).

A turn must be explainable, not just successful: which model requests ran and
what they cost, which tools were requested, executed, blocked or failed and
why, whether a retry round was used and rescued the turn, and where the time
went. These tests drive the real graph with a scripted model and scripted
tools, with controlled usage metadata, and read the recorder, the trace's
metadata and the log: counts, order, categories, tokens and durations, and that
none of it holds a word of the conversation.

They prove what Formiq records, not how Gemini behaves.
"""

import dataclasses
import json
import logging
import time

import httpx
import pytest

from app.agent import CoachContext, coach_graph, initial_state
from app.agent.graph import MAX_TOOL_ITERATIONS, PROPOSAL_RETRY_ROUNDS
from app.ai import AIProviderError, ModelTurn
from app.observability import Tracer, TurnRecorder
from app.observability.trajectory import (
    MAX_EVENTS,
    SCHEMA,
    EventType,
    aggregate,
    log_proposal_approved,
    percentile,
)
from tests.coach import call, fake_provider, respond_turn, tool_turn
from tests.observability import FailingBackend, recording
from tests.unit.test_coach_proposal_budget import (
    ACCEPTED,
    MISSING_CORE,
    READS,
    REPLY,
    USER,
    propose,
)
from tests.unit.test_coach_recovery import DECIDE, FIRST_ROUND, NONE_YET, tools_where

MESSAGE = "Can you rewrite this plan with different ab exercises?"


@pytest.fixture(autouse=True)
def trajectory_log(monkeypatch):
    """The trajectory's log is readable: Alembic's fileConfig, run in this process
    by the migration tests, disables the loggers that exist by then."""
    monkeypatch.setattr(logging.getLogger("app.observability.trajectory"), "disabled", False)


def with_usage(turn: ModelTurn, *, model: str | None = None, **usage: int) -> ModelTurn:
    """The turn as Gemini reported it, with these token counts."""
    return dataclasses.replace(turn, usage=usage or None, model=model)


def drive(provider, tools, message=MESSAGE, tracer=None, status="success", **context):
    """One turn through the graph with a recording trace, ended as the coach
    service ends it: the state, the trace and the backend."""
    if tracer is None:
        tracer, backend = recording()
    else:
        backend = tracer.backend
    with tracer.request("coach_request", request_id="req-traj", user_id=USER) as trace:
        state = coach_graph.invoke(
            initial_state(message),
            context=CoachContext(user_id=USER, provider=provider, tools=tools, trace=trace, **context),
        )
        trace.trajectory.finish(status)
    return state, trace, backend


def types_of(trace):
    return [event["type"] for event in trace.trajectory.events]


def events(trace, type):
    return [event for event in trace.trajectory.events if event["type"] == type]


def summary_of(trace):
    return trace.trajectory.summary()


# --- the order of a turn ---


def test_a_successful_proposal_is_an_ordered_trajectory_with_its_costs():
    tools = tools_where(None, ACCEPTED)
    provider = fake_provider(
        with_usage(FIRST_ROUND, model="gemini-test-001", input_tokens=1000, output_tokens=50, total_tokens=1050),
        with_usage(tool_turn(*(call(n) for n in READS[1:])), input_tokens=1200, output_tokens=40, total_tokens=1240),
        with_usage(tool_turn(propose(10, 11, 12)), input_tokens=1500, output_tokens=120, total_tokens=1620),
        with_usage(DECIDE, input_tokens=1700, output_tokens=60, total_tokens=1760),
    )

    state, trace, _ = drive(provider, tools)

    assert state["final_response"] == REPLY
    seq = [event["seq"] for event in trace.trajectory.events]
    assert seq == list(range(1, len(seq) + 1))
    assert [event["t_ms"] for event in trace.trajectory.events] == sorted(
        event["t_ms"] for event in trace.trajectory.events
    )
    kinds = types_of(trace)
    assert kinds[0] == EventType.TURN_STARTED and kinds[-1] == EventType.TURN_COMPLETED
    assert kinds.count(EventType.MODEL_REQUEST_STARTED) == kinds.count(EventType.MODEL_REQUEST_COMPLETED) == 4
    # each tool call is requested, then ran: the proposal's request is the third
    summary = summary_of(trace)
    assert summary["model_requests"] == 4
    assert summary["tool_calls"]["requested"] == summary["tool_calls"]["executed"] == 5
    assert summary["tool_calls"]["blocked"] == summary["tool_calls"]["failed"] == 0
    assert summary["tool_calls"]["per_round"] == [2, 2, 1, 0]
    assert summary["tool_calls"]["by_tool"]["propose_workout_plan"] == {
        "requested": 1, "executed": 1, "blocked": 0, "failed": 0,
    }
    assert summary["proposal"]["accepted_in_request"] == 3
    # what the successful proposal cost: the requests up to and including its own
    assert summary["tokens"]["through_proposal_total"] == 1050 + 1240 + 1620
    assert summary["tokens"]["total"] == 1050 + 1240 + 1620 + 1760
    assert summary["schema"] == SCHEMA and summary["turn_id"] == "req-traj"


def test_a_blocked_call_is_not_an_executed_call():
    # a duplicate search (blocked by Formiq) and a write (blocked by Formiq)
    tools = tools_where(None)
    provider = fake_provider(
        tool_turn(call("search_exercises", muscle="Core")),
        tool_turn(call("search_exercises", muscle="Core"), call("modify_workout_plan", plan_id=1)),
        respond_turn("Core exercises exist.", "EXERCISE", "RETRIEVE_THEN_ANSWER"),
    )

    _, trace, _ = drive(provider, tools)

    summary = summary_of(trace)
    assert summary["tool_calls"]["requested"] == 3
    assert summary["tool_calls"]["executed"] == 1  # only the first search ran
    assert summary["tool_calls"]["blocked"] == 2
    assert summary["tool_calls"]["duplicates_blocked"] == 1
    assert summary["tool_calls"]["repeated_lookups"] == 1
    blocked = events(trace, EventType.TOOL_CALL_BLOCKED)
    assert [(e["tool"], e["category"]) for e in blocked] == [
        ("search_exercises", "duplicate_call"),
        ("modify_workout_plan", "write_not_authorized"),
    ]
    assert [n for batch in tools.runs for n in batch].count("search_exercises") == 1
    # the requested/executed/blocked events are independent: requested for all three
    assert len(events(trace, EventType.TOOL_CALL_REQUESTED)) == 3
    assert len(events(trace, EventType.TOOL_CALL_EXECUTED)) == 1


def test_a_call_refused_for_the_per_turn_limit_is_blocked_not_executed():
    limited = {"error": {"code": "TOOL_LIMIT_REACHED", "message": "only 8 tool calls are run"}}
    tools = tools_where({"get_workout_session": limited})
    provider = fake_provider(
        tool_turn(call("get_user_profile"), call("get_workout_session", session_id=5)),
        respond_turn("I could not read the session.", "WORKOUT_HISTORY", "CANNOT_ANSWER"),
    )

    _, trace, _ = drive(provider, tools, "Show session 5.")

    calls = summary_of(trace)["tool_calls"]
    assert (calls["requested"], calls["executed"], calls["blocked"], calls["failed"]) == (2, 1, 1, 0)
    assert summary_of(trace)["budget"] == {
        "exhausted": True, "reason": "tool_limit", "rounds_used": 2, "model_requests": 2,
    }


@pytest.mark.parametrize(
    ("code", "category"),
    [
        ("TOOL_ERROR", "tool_error"),
        ("INVALID_INPUT", "tool_validation_error"),
        ("RESOURCE_NOT_FOUND", "ownership_failure"),
    ],
)
def test_a_tool_that_ran_and_failed_is_a_failed_execution_with_its_category(code, category):
    tools = tools_where({"get_workout_plan": {"error": {"code": code, "message": "details"}}})
    provider = fake_provider(
        tool_turn(call("get_workout_plan", plan_id=12)),
        respond_turn("I could not read plan 12.", "WORKOUT_PLAN", "CANNOT_ANSWER"),
    )

    _, trace, _ = drive(provider, tools, "What is in plan 12?")

    (failed,) = events(trace, EventType.TOOL_EXECUTION_FAILED)
    assert (failed["tool"], failed["category"], failed["outcome"]) == ("get_workout_plan", category, "error")
    calls = summary_of(trace)["tool_calls"]
    assert (calls["executed"], calls["failed"], calls["blocked"]) == (1, 1, 0)
    assert calls["success_rate"] == 0.0 and calls["success_rate_denominator"] == "executed"


def test_a_read_of_the_users_own_record_that_finds_none_is_an_answer_not_a_failure():
    # a new user: no plan, no workout yet. The tools did their job.
    tools = tools_where(
        {"get_current_workout_plan": NONE_YET, "get_latest_workout_session": NONE_YET}
    )
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS)),
        respond_turn("Your goal is muscle gain.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
    )

    _, trace, _ = drive(provider, tools, "What is my goal?")

    calls = summary_of(trace)["tool_calls"]
    assert (calls["executed"], calls["failed"], calls["empty"]) == (3, 0, 2)
    assert calls["success_rate"] == 1.0
    assert summary_of(trace)["failure_reasons"] == []
    assert {e["outcome"] for e in events(trace, EventType.TOOL_CALL_EXECUTED)} == {"ok", "empty"}
    # a lookup of one resource by id that finds none is not the user's own empty record
    # (see test_a_tool_that_ran_and_failed_...: RESOURCE_NOT_FOUND on get_workout_plan fails)


def test_a_normal_answer_without_a_proposal_records_no_proposal():
    provider = fake_provider(respond_turn("Progressive overload means gradually adding load."))

    _, trace, _ = drive(provider, tools_where(None), "What is progressive overload?")

    summary = summary_of(trace)
    assert summary["model_requests"] == 1 and summary["tool_calls"]["requested"] == 0
    assert summary["proposal"]["outcome"] == "not_attempted" and summary["proposal"]["attempts"] == 0
    assert summary["request_completed"] is True
    assert summary["failure_reasons"] == []


# --- why a proposal was refused, and whether the call could try again ---


def test_a_repeat_after_the_evidence_changed_is_told_from_an_unchanged_one():
    tools = tools_where(None, ACCEPTED)
    provider = fake_provider(
        tool_turn(*(call(n) for n in READS)),
        tool_turn(propose(10, 11, 12)),  # ids nobody gave yet
        tool_turn(call("search_exercises", muscle="Core")),  # which gives them
        tool_turn(propose(10, 11, 12)),  # the same proposal, with new evidence
        DECIDE,
    )

    _, trace, _ = drive(provider, tools)

    proposals = [c for c in trace.trajectory.calls if c["proposal"]]
    assert [(c["repeat"], c["executed"], c["category"]) for c in proposals] == [
        ("none", False, "id_not_grounded"),
        ("evidence_changed", True, None),
    ]
    summary = summary_of(trace)
    assert summary["tool_calls"]["retries_after_changed_evidence"] == 1
    assert summary["proposal"]["rejections"] == 1
    assert "id_not_grounded" in summary["failure_reasons"]


def test_the_same_refusal_with_nothing_changed_is_an_unchanged_repeat():
    tools = tools_where(None, ACCEPTED)
    provider = fake_provider(
        tool_turn(*(call(n) for n in READS)),
        tool_turn(propose(77, 78)),
        tool_turn(propose(77, 78)),
        respond_turn("I could not.", "ADAPTATION", "CANNOT_ANSWER"),
    )

    _, trace, _ = drive(provider, tools)

    assert [c["repeat"] for c in trace.trajectory.calls if c["proposal"]] == ["none", "unchanged"]
    assert summary_of(trace)["tool_calls"]["retries_after_changed_evidence"] == 0


def test_a_missing_prerequisite_is_recorded_and_the_reads_formiq_loaded_are_its_own():
    tools = tools_where(None, ACCEPTED)
    provider = fake_provider(
        FIRST_ROUND, tool_turn(propose(10, 11, 12)), tool_turn(propose(10, 11, 12)), DECIDE
    )

    _, trace, _ = drive(provider, tools)

    summary = summary_of(trace)
    assert summary["proposal"]["missing_prerequisites"] == 1
    calls = summary["tool_calls"]
    # the model requested 4 calls (profile, search, two proposals); Formiq read two more
    assert calls["requested"] == 4 and calls["formiq_loaded"] == 2
    assert calls["executed"] == 5 and calls["blocked"] == 1  # the first proposal was blocked
    loaded = [e for e in events(trace, EventType.TOOL_CALL_EXECUTED) if e["origin"] == "formiq"]
    assert [e["tool"] for e in loaded] == ["get_current_workout_plan", "get_latest_workout_session"]
    (rejected,) = events(trace, EventType.PROPOSAL_VALIDATION_REJECTED)
    assert rejected["category"] == "missing_prerequisite"
    assert all(e["type"] != EventType.TOOL_CALL_REQUESTED or e["origin"] == "model" for e in trace.trajectory.events)


def test_an_ungrounded_equipment_identifier_is_blocked_before_any_tool_runs():
    tools = tools_where(None)
    provider = fake_provider(
        tool_turn(call("search_exercises", equipment_id=3, use="MAIN_WORKOUT")),
        respond_turn("Which equipment do you mean?", "EXERCISE", "ASK_CLARIFICATION"),
    )

    _, trace, _ = drive(provider, tools, "Find kettlebell exercises.")

    (blocked,) = events(trace, EventType.TOOL_CALL_BLOCKED)
    assert (blocked["tool"], blocked["category"]) == ("search_exercises", "id_not_grounded")
    assert tools.runs == []


def test_a_retry_round_that_rescues_the_turn_is_counted_with_its_outcome():
    tools = tools_where(None, MISSING_CORE, ACCEPTED)
    provider = fake_provider(
        tool_turn(*(call(n) for n in READS)),
        tool_turn(call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(call("search_exercises", use="WARM_UP")),
        tool_turn(call("search_exercises", use="COOL_DOWN")),
        tool_turn(propose(10, 11)),  # the fifth round: refused, and correctable
        tool_turn(propose(10, 11, 12)),  # the retry round
        DECIDE,
    )

    _, trace, _ = drive(provider, tools)

    summary = summary_of(trace)
    assert summary["retry_round"] == {"entered": True, "outcome": "recovered", "recovered": True}
    assert summary["model_requests"] == MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 1
    started = events(trace, EventType.RETRY_ROUND_STARTED)
    done = events(trace, EventType.RETRY_ROUND_COMPLETED)
    assert (len(started), len(done), done[0]["outcome"]) == (1, 1, "recovered")
    (rejected,) = events(trace, EventType.PROPOSAL_VALIDATION_REJECTED)
    assert rejected["category"] == "proposal_rejected_correctable"
    assert summary["proposal"]["attempts"] == 2 and summary["proposal"]["rejections"] == 1


def test_a_retry_round_that_fails_again_is_recorded_as_failed_and_the_budget_as_spent():
    tools = tools_where(None, MISSING_CORE, MISSING_CORE)
    provider = fake_provider(
        tool_turn(*(call(n) for n in READS)),
        tool_turn(call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(call("search_exercises", use="WARM_UP")),
        tool_turn(call("search_exercises", use="COOL_DOWN")),
        tool_turn(propose(10, 11)),
        tool_turn(propose(10, 12)),  # the retry round, refused again
        respond_turn("I could not build it.", "ADAPTATION", "CANNOT_ANSWER"),
    )

    _, trace, _ = drive(provider, tools, status="cannot_answer")

    summary = summary_of(trace)
    assert summary["retry_round"] == {"entered": True, "outcome": "rejected_again", "recovered": False}
    assert summary["request_completed"] is False
    assert summary["proposal"]["rejections"] == 2


def test_a_turn_that_runs_out_of_rounds_says_so():
    tools = tools_where(None)
    provider = fake_provider(
        *(tool_turn(call("search_exercises", muscle=f"Muscle {n}")) for n in range(MAX_TOOL_ITERATIONS)),
        respond_turn("Here is the final proposal below.", "EXERCISE", "RETRIEVE_THEN_ANSWER"),
    )

    _, trace, _ = drive(provider, tools, "Find core exercises.", status="cannot_answer")

    budget = summary_of(trace)["budget"]
    assert budget["exhausted"] is True and budget["reason"] == "retry_limit_reached"
    assert trace.trajectory.termination == "retry_limit_reached"


# --- a provider failure ---


@pytest.mark.parametrize(
    ("cause", "category"),
    [(httpx.ReadTimeout("slow"), "provider_timeout"), (RuntimeError("down"), "provider_error")],
)
def test_a_provider_error_is_an_event_with_its_category_and_the_error_goes_on(cause, category):
    try:
        raise AIProviderError("the model request failed") from cause
    except AIProviderError as error:
        failure = error
    provider = fake_provider(tool_turn(call("get_user_profile")), failure)
    tracer, _ = recording()

    with pytest.raises(AIProviderError):
        with tracer.request("coach_request", request_id="req-err", user_id=USER) as trace:
            coach_graph.invoke(
                initial_state("Hello"),
                context=CoachContext(user_id=USER, provider=provider, tools=tools_where(None), trace=trace),
            )

    (event,) = [e for e in trace.trajectory.events if e["type"] == EventType.PROVIDER_ERROR]
    assert (event["category"], event["request"], event["outcome"]) == (category, 2, "error")
    assert category in trace.trajectory.failures
    assert trace.trajectory.requests[1]["status"] == "failed"


# --- tokens ---


def test_tokens_are_what_the_provider_reported_for_each_request_and_never_double_counted():
    provider = fake_provider(
        with_usage(
            tool_turn(call("get_user_profile")), model="gemini-test-001",
            input_tokens=800, cached_input_tokens=300, output_tokens=20, reasoning_tokens=100,
            total_tokens=920,
        ),
        with_usage(
            respond_turn("Your goal is muscle gain.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
            model="gemini-test-001", input_tokens=900, output_tokens=30, total_tokens=930,
        ),
    )

    _, trace, _ = drive(provider, tools_where(None), "What is my goal?")

    tokens = summary_of(trace)["tokens"]
    assert tokens["input"] == 1700 and tokens["output"] == 50
    assert tokens["cached_input"] == 300 and tokens["reasoning"] == 100
    # Gemini's own totals, added: not input + output, which would miss the thinking
    assert tokens["total"] == 920 + 930
    assert (tokens["source"], tokens["requests_reporting"], tokens["requests_total"]) == ("provider_reported", 2, 2)
    assert tokens["estimated"] is False
    per_request = summary_of(trace)["tokens_per_request"]
    assert [r["total_tokens"] for r in per_request] == [920, 930]
    assert [r["model_reported"] for r in per_request] == ["gemini-test-001"] * 2
    assert summary_of(trace)["models_reported"] == ["gemini-test-001"]


def test_a_response_without_usage_is_unavailable_not_zero_and_never_estimated():
    provider = fake_provider(respond_turn("Hello."))

    _, trace, _ = drive(provider, tools_where(None), "Hi")

    summary = summary_of(trace)
    assert summary["tokens"]["source"] == "unavailable"
    assert summary["tokens"]["input"] is None and summary["tokens"]["total"] is None
    assert summary["tokens_per_request"][0]["available"] is False
    assert summary["models_reported"] == []


def test_a_turn_where_only_some_requests_reported_says_partial():
    provider = fake_provider(
        with_usage(tool_turn(call("get_user_profile")), input_tokens=500, total_tokens=520),
        respond_turn("Your goal is muscle gain.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
    )

    _, trace, _ = drive(provider, tools_where(None), "What is my goal?")

    tokens = summary_of(trace)["tokens"]
    assert (tokens["source"], tokens["requests_reporting"], tokens["requests_total"]) == ("partial", 1, 2)
    assert tokens["total"] == 520  # of the request that reported it only


# --- time ---


class SlowTools:
    """Tools that take measurable time and say how long each call took."""

    declarations = tools_where(None).declarations

    def run(self, calls, *, user_id):
        self.last_durations_ms = []
        for _ in calls:
            time.sleep(0.02)
            self.last_durations_ms.append(20.0)
        return [{"output": {"tool": item.name}} for item in calls]


def test_the_turn_requests_tools_and_validation_are_timed_apart_from_each_other():
    provider = fake_provider(
        tool_turn(call("get_user_profile"), call("get_current_workout_plan")),
        respond_turn("Your goal is muscle gain.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
    )

    _, trace, _ = drive(provider, SlowTools(), "What is my goal?")

    latency = summary_of(trace)["latency_ms"]
    assert len(latency["model_requests"]) == 2 and all(isinstance(ms, int) for ms in latency["model_requests"])
    assert latency["tool_calls"] == [20, 20]  # each call's own time, as the tools measured it
    assert latency["tool_total"] >= 40  # the run, measured around it, not inferred
    assert latency["turn"] >= latency["tool_total"] + latency["model_total"]
    assert latency["slowest_request"] in (1, 2)
    assert latency["decision_reply_validation"] >= 0
    assert (latency["provider_retries"], latency["provider_backoff"]) == (0, 0)


# --- the model name ---


def test_the_summary_names_the_configured_model_and_the_one_gemini_reported():
    class Provider:
        model = "gemini-env-override"

        def __init__(self, turns):
            self.turns = iter(turns)

        def generate_turn(self, *args, **kwargs):
            return next(self.turns)

    provider = Provider(
        [with_usage(respond_turn("Hello."), model="gemini-env-override-002", total_tokens=10)]
    )

    _, trace, _ = drive(provider, tools_where(None), "Hi")

    summary = summary_of(trace)
    assert summary["model"] == "gemini-env-override"
    assert summary["models_reported"] == ["gemini-env-override-002"]


def test_the_model_a_running_process_uses_is_the_environments_not_the_env_files(
    monkeypatch, tmp_path
):
    # backend/.env says one model; the process's environment (as the playground is
    # started) says another, and wins: the summary must name the one in use
    from app.api import dependencies
    from app.core.config import Settings

    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "DATABASE_URL=postgresql+psycopg://unused:unused@localhost/unused\n"
        "GEMINI_MODEL=model-from-the-env-file\n"
    )
    monkeypatch.setenv("GEMINI_MODEL", "model-from-the-environment")
    monkeypatch.setattr(dependencies, "settings", Settings(_env_file=dotenv))

    provider = dependencies.get_ai_provider()
    provider.generate_turn = lambda *args, **kwargs: with_usage(
        respond_turn("Hello."), model="model-from-the-environment-001", total_tokens=5
    )

    _, trace, _ = drive(provider, tools_where(None), "Hi")

    assert summary_of(trace)["model"] == "model-from-the-environment"
    assert summary_of(trace)["models_reported"] == ["model-from-the-environment-001"]


# --- what a trace may hold, and tracing off ---

CANARIES = ("CANARY-MESSAGE-7f3a", "CANARY-REPLY-91bc", "CANARY-DATA-5d2e", "CANARY-ARG-c8e1")


def test_the_trajectory_holds_no_content_in_its_summary_metadata_trace_or_log(caplog):
    caplog.set_level(logging.INFO)
    tools = tools_where({"get_user_profile": {"output": {"user_id": USER, "profile": {"goal": CANARIES[2]}}}})
    provider = fake_provider(
        tool_turn(call("get_user_profile"), call("search_exercises", muscle=CANARIES[3])),
        respond_turn(f"Your goal is {CANARIES[2]}. {CANARIES[1]}", "PROFILE", "RETRIEVE_THEN_ANSWER"),
    )

    _, trace, backend = drive(provider, tools, f"What is my goal? {CANARIES[0]}")
    trace.trajectory.log_summary()
    trace.finish("success", **trace.trajectory.metadata())

    everything = json.dumps(
        [summary_of(trace), trace.trajectory.metadata(), backend.everything(), caplog.text],
        default=repr,
    )
    for canary in CANARIES:
        assert canary not in everything
    assert "coach_turn_summary" in caplog.text
    assert backend.root.metadata["trajectory"][0].endswith("start")


def test_with_tracing_off_the_summary_still_exists_and_nothing_is_sent():
    tracer = Tracer()  # no backend: tracing off
    provider = fake_provider(respond_turn("Hello."))

    _, trace, _ = drive(provider, tools_where(None), "Hi", tracer=tracer)

    assert tracer.enabled is False
    assert summary_of(trace)["model_requests"] == 1
    assert trace.trajectory.metadata()["tool_calls_requested"] == 0


def test_a_failing_tracing_backend_changes_nothing_about_the_turn():
    tools = tools_where(None, ACCEPTED)
    provider = fake_provider(
        FIRST_ROUND, tool_turn(propose(10, 11, 12)), tool_turn(propose(10, 11, 12)), DECIDE
    )
    tracer = Tracer(FailingBackend())

    state, trace, _ = drive(provider, tools, tracer=tracer)

    assert state["final_response"] == REPLY
    assert summary_of(trace)["tool_calls"]["requested"] == 4  # the recorder is not the backend


def test_a_failing_recorder_never_fails_the_turn(monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("SECRET-RECORDER-DETAIL")

    monkeypatch.setattr(TurnRecorder, "_elapsed_ms", broken)
    provider = fake_provider(respond_turn("Hello there."))

    state, trace, _ = drive(provider, tools_where(None), "Hi")

    assert state["final_response"] == "Hello there."
    assert "RuntimeError" in caplog.text and "SECRET-RECORDER-DETAIL" not in caplog.text


# --- many turns ---


def test_the_recorder_keeps_a_bounded_number_of_events():
    recorder = TurnRecorder("bounded")

    for _ in range(MAX_EVENTS + 25):
        recorder.event(EventType.TOOL_CALL_REQUESTED, tool="search_exercises")

    assert len(recorder.events) == MAX_EVENTS
    assert recorder.dropped_events == 25 + 1  # the turn_started event took one place
    metadata = recorder.metadata()
    assert metadata["trajectory_events"] == MAX_EVENTS + 25 + 1  # all counted, the first kept
    assert len(metadata["trajectory"]) <= 64


def test_percentiles_are_nearest_rank_and_rates_name_their_denominator():
    assert percentile([], 90) is None
    assert percentile([10], 90) == 10
    assert percentile(range(1, 11), 90) == 9  # the smallest value with 90% at or below it
    assert percentile(range(1, 11), 50) == 5

    def turn(ms, outcome, attempts, retry=None, total=None, through=None, model="gemini-a"):
        return {
            "model": model, "models_reported": [], "request_completed": True,
            "model_requests": 3, "failure_reasons": [],
            "latency_ms": {"turn": ms, "model_requests": [ms // 2], "tool_calls": [5]},
            "tool_calls": {"requested": 4, "executed": 4, "blocked": 0, "failed": 0, "duplicates_blocked": 0},
            "proposal": {"outcome": outcome, "attempts": attempts, "rejections": 0},
            "validation": {"decision_rejections": 0, "reply_rejections": 0},
            "retry_round": {"entered": retry is not None, "outcome": retry, "recovered": retry == "recovered"},
            "tokens": {"input": total, "output": 10, "total": total, "source": "provider_reported" if total else "unavailable", "through_proposal_total": through},
        }

    result = aggregate(
        [
            turn(1000, "created", 1, total=2000, through=1500),
            turn(3000, "not_created", 1, retry="rejected_again"),
            turn(2000, "created", 2, retry="recovered", total=4000, through=3000),
            turn(500, "not_attempted", 0),
        ]
    )

    assert result["turns"] == 4
    assert result["latency_ms"]["turn"] == {"n": 4, "median": 1500.0, "p90": 3000, "max": 3000}
    # a rate of the turns that asked for a proposal: 2 of 3, not 2 of 4
    assert result["proposal_success"] == {
        "n": 2, "of": 3, "rate": 0.6667, "denominator": "turns that asked for a proposal",
    }
    assert result["retry_round_success"]["of"] == 2 and result["retry_round_success"]["n"] == 1
    assert result["tokens"]["turns_reporting"] == 2 and result["tokens"]["estimated"] is False
    assert result["tokens"]["total_per_created_proposal"]["median"] == 3000
    assert result["tokens"]["total_through_proposal"]["median"] == 2250


def test_aggregating_turns_of_different_models_lists_them_so_they_are_not_compared():
    base = {
        "models_reported": [], "request_completed": True, "model_requests": 1, "failure_reasons": [],
        "latency_ms": {"turn": 1, "model_requests": [1], "tool_calls": []},
        "tool_calls": {"requested": 0, "executed": 0, "blocked": 0, "failed": 0, "duplicates_blocked": 0},
        "proposal": {"outcome": "not_attempted", "attempts": 0, "rejections": 0},
        "validation": {"decision_rejections": 0, "reply_rejections": 0},
        "retry_round": {"entered": False, "outcome": None, "recovered": None},
        "tokens": {"input": None, "output": None, "total": None, "source": "unavailable", "through_proposal_total": None},
    }

    result = aggregate([{**base, "model": "gemini-a"}, {**base, "model": "gemini-b"}])

    assert result["models"] == ["gemini-a", "gemini-b"]


def test_an_approval_is_a_structured_event_that_holds_no_user_data(caplog):
    caplog.set_level(logging.INFO)

    log_proposal_approved(proposal_ref="0123456789abcdef0123456789abcdef", plan_id=42)

    (line,) = [r.message for r in caplog.records if r.message.startswith("coach_event")]
    event = json.loads(line.removeprefix("coach_event "))
    assert event["type"] == "proposal_approved" and event["proposal_ref"] == "01234567"
    assert event["plan_saved"] is True and "plan_id" not in event and "user" not in line


def test_a_failure_classifying_repeats_never_fails_the_turn(monkeypatch, caplog):
    from app.agent import graph

    def broken(*args, **kwargs):
        raise RuntimeError("SECRET-CLASSIFIER-DETAIL")

    monkeypatch.setattr(graph, "repeat_kind", broken)
    monkeypatch.setattr(logging.getLogger("app.agent.graph"), "disabled", False)
    provider = fake_provider(
        tool_turn(call("get_user_profile")),
        respond_turn("Your goal is muscle gain.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
    )

    state, trace, _ = drive(provider, tools_where(None), "What is my goal?")

    assert state["final_response"] == "Your goal is muscle gain."
    assert [c["repeat"] for c in trace.trajectory.calls] == ["none"]
    assert "RuntimeError" in caplog.text and "SECRET-CLASSIFIER-DETAIL" not in caplog.text
