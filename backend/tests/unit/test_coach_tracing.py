"""Tests for the coach graph's trace: which observations a turn records, in what
order and under which parent, with what metadata, and that the trace holds no
content and changes nothing. The model and tools are fakes, and the trace goes
to an in-memory backend: no test calls Gemini or Langfuse."""

import logging
from unittest.mock import Mock

import httpx
import pytest
from google.genai import types

from app.agent import (
    CANNOT_ANSWER_REPLY,
    SAFETY_POLICY,
    CoachContext,
    ConversationTurn,
    SafetyCategory,
    coach_graph,
    initial_state,
)
from app.agent import graph as coach_graph_module
from app.ai import AIProviderError, GeminiProvider, ModelTurn
from app.observability import Tracer
from tests.coach import (
    FakeTools,
    call,
    fake_provider,
    respond_turn,
    text_turn,
    tool_turn,
)
from tests.observability import FailingBackend, recording
from tests.unit.test_coach_conversation_context import budget_for_rounds

USER = 7
PROFILE = {"output": {"user_id": USER, "profile": {"goal": "muscle_gain"}}}
PLAN = {"output": {"plan_id": 12, "exercises": [{"exercise_id": 3}], "truncated": False}}


def tools_returning(**results):
    return FakeTools(result=lambda item: results.get(item.name, {"output": {}}))


def traced(provider, tools, message, history=(), tracer=None, **context):
    """The turn's final state and what its trace recorded."""
    if tracer is None:
        tracer, backend = recording()
    else:
        backend = tracer.backend
    with tracer.request("coach_request", request_id="req-1", user_id=USER) as trace:
        state = coach_graph.invoke(
            initial_state(message, history),
            context=CoachContext(user_id=USER, provider=provider, tools=tools, trace=trace, **context),
        )
    return state, backend, trace


def untraced(provider, tools, message, history=(), **context):
    return coach_graph.invoke(
        initial_state(message, history),
        context=CoachContext(user_id=USER, provider=provider, tools=tools, **context),
    )


def profile_and_plan_turns():
    return (
        tool_turn(call("get_user_profile"), call("get_workout_plan", plan_id=12)),
        respond_turn("Plan 12 fits your goal.", "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
    )


# the trajectory


def test_a_turn_is_traced_as_its_trajectory_in_order():
    state, backend, _ = traced(
        fake_provider(*profile_and_plan_turns()),
        tools_returning(get_user_profile=PROFILE, get_workout_plan=PLAN),
        "Does plan 12 fit my goal?",
    )

    assert state["final_response"] == "Plan 12 fits your goal."
    assert backend.tree() == (
        "coach_request",
        (
            ("safety_check", ()),
            ("model_turn", (("context_fit", ()), ("gemini", ()))),
            ("tool_calls", (("get_user_profile", ()), ("get_workout_plan", ()))),
            ("model_turn", (("context_fit", ()), ("gemini", ()))),
            ("decision_validation", ()),
            ("reply_validation", ()),
        ),
    )
    assert all(node.ended for node in backend.nodes)
    kinds = {node.name: node.kind for node in backend.nodes}
    assert kinds == {
        "coach_request": "trace",
        "safety_check": "guardrail",
        "model_turn": "chain",
        "context_fit": "span",
        "gemini": "generation",
        "tool_calls": "span",
        "get_user_profile": "tool",
        "get_workout_plan": "tool",
        "decision_validation": "guardrail",
        "reply_validation": "guardrail",
    }


def test_each_model_request_is_a_generation_with_its_iteration():
    provider = fake_provider(*profile_and_plan_turns())
    provider.model = "gemini-test"

    _, backend, trace = traced(
        provider,
        tools_returning(get_user_profile=PROFILE, get_workout_plan=PLAN),
        "Does plan 12 fit my goal?",
    )

    first, second = backend.named("gemini")
    assert [first.metadata["iteration"], second.metadata["iteration"]] == [0, 1]
    assert first.model == second.model == "gemini-test"
    assert first.metadata["requested_tool_calls"] == 2
    assert second.metadata["called_respond"] is True
    assert second.metadata["tool_results_sent"] == 2
    assert first.metadata["usage_available"] is False
    assert trace.counts["model_requests"] == 2


def test_token_usage_is_recorded_only_as_the_provider_reported_it():
    reported = {"input_tokens": 120, "output_tokens": 9, "total_tokens": 129}
    answer = respond_turn("Rest a day.")
    turn = ModelTurn(content=answer.content, tool_calls=answer.tool_calls, usage=reported)

    _, backend, _ = traced(fake_provider(turn), FakeTools(), "Rest?")

    (generation,) = backend.named("gemini")
    assert generation.usage == reported
    assert generation.metadata["usage_available"] is True


def test_each_tool_call_is_a_tool_observation_under_its_batch():
    _, backend, trace = traced(
        fake_provider(*profile_and_plan_turns()),
        tools_returning(get_user_profile=PROFILE, get_workout_plan=PLAN),
        "Does plan 12 fit my goal?",
    )

    (batch,) = backend.named("tool_calls")
    profile, plan = backend.children(batch)
    assert (profile.name, plan.name) == ("get_user_profile", "get_workout_plan")
    assert plan.metadata == {
        "iteration": 0,
        "argument_names": ["plan_id"],
        "id_arguments": 1,
        "user_scoped": True,
        "user_id_argument": False,
        "executed": True,
        "data_status": "AVAILABLE",
        "output_chars": plan.metadata["output_chars"],
        "truncated": False,
        "result_count": 1,
    }
    assert profile.level is None and plan.level is None
    assert trace.counts["tool_calls_requested"] == trace.counts["tool_calls_executed"] == 2


def test_a_call_that_never_ran_is_traced_with_why():
    _, backend, trace = traced(
        fake_provider(
            tool_turn(call("get_workout_session", session_id=999)),
            respond_turn("Which session?", "AMBIGUOUS", "ASK_CLARIFICATION"),
        ),
        FakeTools(),
        "How did my session go?",
    )

    (session,) = backend.named("get_workout_session")
    assert session.metadata["executed"] is False
    assert (session.level, session.status_message) == ("ERROR", "id_not_grounded")
    assert session.metadata["error_code"] == "ID_NOT_GROUNDED"
    assert trace.counts["tool_id_not_grounded"] == 1
    assert trace.counts["tool_calls_executed"] == 0


@pytest.mark.parametrize(
    ("code", "category"),
    [
        ("TOOL_ERROR", "tool_error"),
        ("INVALID_INPUT", "tool_validation_error"),
        ("RESOURCE_NOT_FOUND", "ownership_failure"),
        ("TOOL_LIMIT_REACHED", "tool_limit_reached"),
    ],
)
def test_a_tool_failure_is_traced_by_category(code, category):
    failing = FakeTools(result=lambda item: {"error": {"code": code, "message": "details"}})

    _, backend, trace = traced(
        fake_provider(
            tool_turn(call("get_workout_plan", plan_id=12)),
            respond_turn("I could not read plan 12.", "WORKOUT_PLAN", "CANNOT_ANSWER"),
        ),
        failing,
        "What is in plan 12?",
    )

    (plan,) = backend.named("get_workout_plan")
    assert (plan.level, plan.status_message) == ("ERROR", category)
    assert plan.metadata["executed"] is True
    assert trace.counts[f"tool_{category}"] == 1


# safety


def test_the_safety_check_is_traced_before_anything_else():
    _, backend, _ = traced(fake_provider(respond_turn("Add load.")), FakeTools(), "Overload?")

    first = backend.children(backend.root)[0]
    assert first.name == "safety_check"
    assert first.metadata == {
        "safety_flagged": False,
        "safety_category": "SAFE",
        "safety_rule": None,
        "model_call_allowed": True,
        "tool_calls_allowed": True,
        "allowed_decisions": [],
    }


def test_a_flagged_request_is_traced_as_the_safety_path_with_the_fixed_reply():
    state, backend, _ = traced(
        fake_provider(respond_turn("Push through it.", "GENERAL_FITNESS", "ANSWER")),
        FakeTools(),
        "I have sharp knee pain. Leg workout?",
    )

    assert state["final_response"] == SAFETY_POLICY[SafetyCategory.PAIN_OR_INJURY].fallback_reply
    (check,) = backend.named("safety_check")
    assert check.metadata["safety_flagged"] is True
    assert check.metadata["safety_category"] == "PAIN_OR_INJURY"
    assert check.metadata["safety_rule"] == "severe_pain"
    assert check.metadata["tool_calls_allowed"] is False
    assert check.metadata["allowed_decisions"] == ["SAFE_REDIRECT"]
    assert backend.named("tool_calls") == []
    root = backend.root.metadata
    assert root["termination"] == "safety_fallback"
    assert root["safety_path"] == "fixed_safe_response"
    assert root["safety_fallback_reason"] == "decision_rejected"
    (validation,) = backend.named("decision_validation")
    assert validation.metadata["rejected_by"] == "safety_policy"


def test_a_flagged_request_answered_by_the_model_is_traced_as_the_models_redirect():
    _, backend, _ = traced(
        fake_provider(
            respond_turn("Please see a physiotherapist.", "SAFETY_SENSITIVE", "SAFE_REDIRECT")
        ),
        FakeTools(),
        "I have sharp knee pain.",
    )

    assert backend.root.metadata["safety_path"] == "model"
    assert backend.root.metadata["termination"] == "decision_accepted"


# context compaction and evidence


BIG_PLAN = {"output": {"plan_id": 12, "exercises": [{"exercise_id": 3, "notes": "x" * 5_000}]}}
BIG_SEARCH = {"output": {"exercises": [{"exercise_id": 5, "notes": "x" * 5_000}], "count": 1}}


def test_compaction_is_traced_and_a_compacted_result_stays_out_of_the_evidence():
    tools = FakeTools(
        result=lambda item: BIG_PLAN if item.name == "get_workout_plan" else BIG_SEARCH
    )
    provider = fake_provider(
        tool_turn(call("get_workout_plan", plan_id=12)),
        tool_turn(call("search_exercises", difficulty="BEGINNER")),
        tool_turn(call("search_exercises", difficulty="BEGINNER")),
        respond_turn("Plan 12 has one exercise.", "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        tool_turn(call("get_workout_plan", plan_id=12)),
        respond_turn("Plan 12 has one exercise.", "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
    )

    state, backend, trace = traced(
        provider, tools, "What is in plan 12?", max_context_chars=budget_for_rounds(2)
    )

    assert state["final_response"] == "Plan 12 has one exercise."
    fits = backend.named("context_fit")
    assert [fit.metadata["compaction_occurred"] for fit in fits] == [
        False, False, False, True, True, True,
    ]  # fmt: skip
    fourth = fits[3].metadata
    assert fourth["compacted_tool_results"] == 1
    assert fourth["chars_after"] < fourth["chars_before"]
    assert fourth["context_budget"] == budget_for_rounds(2)
    assert fourth["context_fit_success"] is True
    rejected, accepted = backend.named("decision_validation")
    assert rejected.metadata["compacted_results_excluded"] == 1
    assert rejected.metadata["rejected_by"] == "decision_policy"
    assert rejected.status_message == "decision_rejected"
    assert accepted.metadata["accepted"] is True
    assert trace.counts["compacted_tool_results"] >= 3
    assert trace.counts["decision_rejections"] == 1


def test_a_context_over_its_budget_is_traced_as_the_turns_end():
    state, backend, _ = traced(
        fake_provider(respond_turn("Hi.")), FakeTools(), "Hi", max_context_chars=100
    )

    assert state["final_response"] == CANNOT_ANSWER_REPLY
    (step,) = backend.named("model_turn")
    assert (step.level, step.status_message) == ("ERROR", "context_budget_exceeded")
    assert backend.named("gemini") == []
    assert backend.root.metadata["termination"] == "context_budget_exceeded"


# decisions and replies


def test_the_validated_decision_is_traced_without_the_reply():
    _, backend, _ = traced(
        fake_provider(respond_turn("Add load or reps over time.")), FakeTools(), "Overload?"
    )

    (validation,) = backend.named("decision_validation")
    assert validation.metadata["intent"] == "GENERAL_FITNESS"
    assert validation.metadata["decision"] == "ANSWER"
    assert validation.metadata["accepted"] is True
    (reply,) = backend.named("reply_validation")
    assert reply.metadata == {"iteration": 0, "reply_chars": 27, "accepted": True}
    assert "Add load" not in backend.everything()


def test_a_rejected_reply_is_traced_by_kind():
    _, backend, trace = traced(
        fake_provider(
            respond_turn("I've updated your goal to fat loss."),
            respond_turn("I can only read your data."),
        ),
        FakeTools(),
        "Change my goal.",
    )

    rejected, accepted = backend.named("reply_validation")
    assert (rejected.level, rejected.status_message) == ("WARNING", "reply_rejected")
    assert rejected.metadata["reason"] == "change_claim"
    assert accepted.metadata["accepted"] is True
    assert trace.counts["reply_rejections"] == 1


def test_the_retry_limit_is_traced_as_the_turns_end():
    provider = Mock(spec=GeminiProvider)
    provider.generate_turn.side_effect = lambda *a, **k: respond_turn(
        "Your goal is fat loss.", "PROFILE", "ANSWER"
    )

    state, backend, trace = traced(provider, FakeTools(), "What is my goal?")

    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert backend.root.metadata["termination"] == "retry_limit_reached"
    assert trace.counts["decision_rejections"] == trace.counts["model_requests"] == 6


# failures


def timed_out():
    try:
        raise httpx.ReadTimeout("timed out")
    except httpx.ReadTimeout as cause:
        try:
            raise AIProviderError("the gemini request failed") from cause
        except AIProviderError as error:
            return error


def test_a_provider_failure_is_traced_on_its_generation_and_still_raised():
    failure = timed_out()
    provider = fake_provider()
    provider.generate_turn.side_effect = failure
    tracer, backend = recording()

    with pytest.raises(AIProviderError) as raised:
        traced(provider, FakeTools(), "Overload?", tracer=tracer)

    assert raised.value is failure
    (generation,) = backend.named("gemini")
    assert (generation.level, generation.status_message) == ("ERROR", "provider_timeout")
    (step,) = backend.named("model_turn")
    assert step.status_message == "provider_timeout"
    assert "timed out" not in backend.everything()


def test_invalid_model_output_is_traced_as_such():
    tracer, backend = recording()

    with pytest.raises(AIProviderError):
        traced(fake_provider(text_turn("Just text.")), FakeTools(), "Hi", tracer=tracer)

    (generation,) = backend.named("gemini")
    assert generation.status_message == "model_output_invalid"


def test_a_provider_failure_on_a_flagged_request_is_traced_with_the_fixed_reply():
    provider = fake_provider()
    provider.generate_turn.side_effect = timed_out()

    state, backend, _ = traced(provider, FakeTools(), "I have sharp knee pain.")

    assert state["final_response"] == SAFETY_POLICY[SafetyCategory.PAIN_OR_INJURY].fallback_reply
    (generation,) = backend.named("gemini")
    assert generation.status_message == "provider_timeout"
    assert backend.root.metadata["safety_path"] == "fixed_safe_response"
    assert backend.root.metadata["safety_fallback_reason"] == "no_model_turn"


# privacy: canaries never reach the trace


SYSTEM = "SECRET_SYSTEM_PROMPT_CANARY"
REASONING = "CHAIN_OF_THOUGHT_CANARY"
PROFILE_CANARY = "USER_PROFILE_PRIVATE_CANARY"
HISTORY_CANARY = "WORKOUT_HISTORY_PRIVATE_CANARY"
MESSAGE = "USER_MESSAGE_CANARY"
API_KEY = "API_KEY_CANARY"


def test_no_content_reaches_the_trace(monkeypatch):
    monkeypatch.setattr(
        coach_graph_module, "COACH_INSTRUCTIONS", f"{coach_graph_module.COACH_INSTRUCTIONS} {SYSTEM}"
    )
    thinking = respond_turn("Plan 12 suits you.", "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER")
    thought = ModelTurn(
        content=types.Content(
            role="model", parts=[types.Part(text=REASONING, thought=True), *thinking.content.parts]
        ),
        text=REASONING,
        tool_calls=thinking.tool_calls,
    )
    tools = tools_returning(
        get_user_profile={"output": {"profile": {"goal": PROFILE_CANARY, "weight_kg": 80}}},
        get_workout_session={"output": {"session_id": 45, "notes": HISTORY_CANARY}},
        get_workout_plan={"output": {"plan_id": 12, "name": HISTORY_CANARY}},
    )
    provider = fake_provider(
        tool_turn(
            call("get_user_profile"),
            call("get_workout_session", session_id=45),
            call("get_workout_plan", plan_id=12, note=MESSAGE),
        ),
        thought,
    )
    provider.model = "gemini-test"
    history = [ConversationTurn("user", f"{MESSAGE} earlier"), ConversationTurn("coach", REASONING)]

    state, backend, _ = traced(
        provider, tools, f"{MESSAGE}: compare plan 12 with session 45", history
    )

    assert state["final_response"] == "Plan 12 suits you."
    sent = backend.everything()
    for canary in (SYSTEM, REASONING, PROFILE_CANARY, HISTORY_CANARY, MESSAGE, API_KEY):
        assert canary not in sent
    assert "Plan 12 suits you" not in sent
    # not even the data's field names: only shapes, counts and codes
    for field_name in ('"weight_kg"', '"profile"', '"notes"', '"goal"'):
        assert field_name not in sent


def test_tool_arguments_are_recorded_by_name_never_by_value():
    _, backend, _ = traced(
        fake_provider(
            tool_turn(call("get_workout_plan", plan_id=987654, user_id=123456)),
            respond_turn("Plan.", "WORKOUT_PLAN", "CANNOT_ANSWER"),
        ),
        FakeTools(),
        "Plan 987654?",
    )

    (plan,) = backend.named("get_workout_plan")
    assert plan.metadata["argument_names"] == ["plan_id", "user_id"]
    assert plan.metadata["user_id_argument"] is True
    assert "987654" not in backend.everything()
    assert "123456" not in backend.everything()


# observability cannot change the request


@pytest.mark.parametrize("error", [RuntimeError, TimeoutError, ConnectionError])
@pytest.mark.parametrize(
    ("message", "turns"),
    [
        ("Does plan 12 fit my goal?", profile_and_plan_turns()),
        ("I have sharp knee pain.", (respond_turn("Push through.", "GENERAL_FITNESS", "ANSWER"),)),
        (
            "What is my goal?",
            (respond_turn("Fat loss.", "PROFILE", "ANSWER"),) * 6,
        ),
    ],
    ids=["tools", "safety", "retry limit"],
)
def test_a_failing_backend_changes_nothing(message, turns, error, caplog, monkeypatch):
    # Alembic's logging setup disables existing loggers once the migrations ran
    monkeypatch.setattr(logging.getLogger("app.observability.tracing"), "disabled", False)
    tools = tools_returning(get_user_profile=PROFILE, get_workout_plan=PLAN)
    expected = untraced(fake_provider(*turns), tools, message)
    backend = FailingBackend(error)

    with caplog.at_level(logging.WARNING, logger="app.observability.tracing"):
        state, _, _ = traced(fake_provider(*turns), tools, message, tracer=Tracer(backend))

    assert state == expected
    assert backend.calls > 0
    # the failure is logged by its type only, never its message
    assert f"Tracing start failed ({error.__name__}); the request goes on" in caplog.text
    assert API_KEY not in caplog.text


def test_a_failing_backend_does_not_hide_a_provider_failure():
    failure = timed_out()
    provider = fake_provider()
    provider.generate_turn.side_effect = failure

    with pytest.raises(AIProviderError) as raised:
        traced(provider, FakeTools(), "Overload?", tracer=Tracer(FailingBackend()))

    assert raised.value is failure


def test_untraced_runs_are_unchanged():
    turns = profile_and_plan_turns()
    tools = tools_returning(get_user_profile=PROFILE, get_workout_plan=PLAN)

    assert untraced(fake_provider(*turns), tools, "Does plan 12 fit my goal?") == traced(
        fake_provider(*turns), tools, "Does plan 12 fit my goal?"
    )[0]


# only safe metadata, whatever a caller passes


def test_only_flat_short_primitive_metadata_is_recorded():
    from app.observability import safe_metadata
    from app.observability.tracing import MAX_LIST_ITEMS, MAX_VALUE_CHARS

    recorded = safe_metadata(
        {
            "count": 3,
            "ratio": 0.5,
            "ok": True,
            "none": None,
            "name": "x" * 500,
            "names": ["a"] * 100,
            "data": {"profile": {"goal": PROFILE_CANARY}},
            "rows": [{"notes": HISTORY_CANARY}],
            "object": Mock(),
            7: "not a key",
        }
    )

    assert recorded == {
        "count": 3,
        "ratio": 0.5,
        "ok": True,
        "none": None,
        "name": "x" * MAX_VALUE_CHARS,
        "names": ["a"] * MAX_LIST_ITEMS,
    }


def test_an_observation_records_only_safe_metadata():
    tracer, backend = recording()

    with (
        tracer.request("coach_request", request_id="r", user_id=1, data={"x": PROFILE_CANARY}) as trace,
        trace.child("step", output={"notes": HISTORY_CANARY}) as step,
    ):
        step.update(profile={"goal": PROFILE_CANARY}, rows=[{"a": 1}], size=4)
        step.fail("tool_error", detail={"message": API_KEY})

    assert backend.named("step")[0].metadata == {"size": 4, "outcome": "tool_error"}
    for canary in (PROFILE_CANARY, HISTORY_CANARY, API_KEY):
        assert canary not in backend.everything()


def test_langfuses_mask_applies_the_same_rule():
    from app.observability.langfuse_backend import mask

    assert mask(data={"size": 4, "profile": {"goal": PROFILE_CANARY}}) == {"size": 4}
    assert mask(data=f"{MESSAGE} as input") is None
    assert mask(data=[{"notes": HISTORY_CANARY}]) is None
