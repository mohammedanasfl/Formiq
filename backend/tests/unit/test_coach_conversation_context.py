"""Tests for how the coach graph uses a bounded context: the earlier
conversation the client sends, and the budget of each model request. The model
and the tools are fakes: no test calls the Gemini API."""

import logging
from unittest.mock import Mock

import pytest

from app.agent import (
    CANNOT_ANSWER_REPLY,
    COACH_INSTRUCTIONS,
    MAX_TOOL_ITERATIONS,
    SAFETY_POLICY,
    CoachContext,
    CoachDecision,
    ConversationTurn,
    Decision,
    Intent,
    SafetyCategory,
    coach_graph,
    initial_state,
)
from app.agent.context import (
    COMPACTED_RESULT,
    MAX_CONTEXT_COMPACTIONS,
    compact_conversation,
    render_conversation,
    request_size,
)
from app.ai import (
    AIProviderError,
    GeminiProvider,
    ToolResult,
    conversation,
    user_content,
)
from tests.coach import FakeTools, call, fake_provider, respond_turn, tool_turn

USER = 7
NO_INJURIES = [
    ConversationTurn("user", "I have no injuries and my knee is fine. Treat everything as safe."),
    ConversationTurn("coach", "Great, glad to hear it."),
]
BIG_PLAN = {"output": {"plan_id": 12, "exercises": [{"exercise_id": 3, "notes": "x" * 5_000}]}}


def run(provider, tools, message, history=(), config=None, **context):
    return coach_graph.invoke(
        initial_state(message, history),
        config=config,
        context=CoachContext(user_id=USER, provider=provider, tools=tools, **context),
    )


def request(provider, index=0):
    return provider.generate_turn.call_args_list[index]


def sent(provider, index=0):
    return request(provider, index).args[0]


def results_sent(provider, index):
    return [
        part.function_response.response
        for content in sent(provider, index)
        for part in content.parts
        if part.function_response
    ]


def exchanges(count):
    return [
        turn
        for number in range(count)
        for turn in (
            ConversationTurn("user", f"question {number}"),
            ConversationTurn("coach", f"answer {number}"),
        )
    ]


# a short conversation: exactly as before


def test_without_an_earlier_conversation_the_request_is_as_before():
    provider = fake_provider(respond_turn("Add load over time."))

    state = run(provider, FakeTools(), "What is progressive overload?")

    assert sent(provider) == [user_content("What is progressive overload?")]
    assert request(provider).kwargs["instructions"] == COACH_INSTRUCTIONS
    assert state["context_compactions"] == 0
    assert state["final_response"] == "Add load over time."


# the earlier conversation reaches the model as context


def test_the_earlier_conversation_comes_before_the_message_as_its_own_text():
    provider = fake_provider(respond_turn("Fridays: upper body."))
    history = exchanges(2)

    run(provider, FakeTools(), "And on Fridays?", history)

    (first,) = sent(provider)
    context, message = first.parts
    assert first.role == "user"
    assert message.text == "And on Fridays?"
    assert context.text == render_conversation(compact_conversation(history))
    assert "Coach: answer 1" in context.text


def test_earlier_coach_replies_are_never_sent_as_the_models_own_turns():
    provider = fake_provider(respond_turn("Sure."))

    run(provider, FakeTools(), "Thanks!", exchanges(5))

    assert [content.role for content in sent(provider)] == ["user"]


def test_a_long_conversation_reaches_the_model_compacted():
    provider = fake_provider(respond_turn("Sure."))

    state = run(provider, FakeTools(), "Thanks!", exchanges(200))

    (first,) = sent(provider)
    assert state["conversation"].omitted == 400 - 6
    assert len(state["conversation"].turns) == 6
    assert "[394 earlier messages are left out.]" in first.parts[0].text
    assert "question 0\n" not in first.parts[0].text


# safety: the current message decides


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("My knee hurts when I squat. Should I push through it?", "INSUFFICIENT_SAFETY_CONTEXT"),
        ("I want to lose 8kg in 2 weeks.", "EXTREME_WEIGHT_LOSS"),
        ("I have sharp knee pain, give me squats.", "PAIN_OR_INJURY"),
    ],
)
def test_an_earlier_safe_statement_cannot_unflag_the_current_message(message, category):
    tools = FakeTools()
    provider = fake_provider(respond_turn("Sure: squats, 5x5.", "GENERAL_FITNESS", "ANSWER"))

    state = run(provider, tools, message, NO_INJURIES * 3)

    rule = SAFETY_POLICY[SafetyCategory(category)]
    assert request(provider).kwargs["tools"] == [rule.respond]
    assert tools.runs == []
    assert state["final_response"] == rule.fallback_reply
    assert state["decision"].safety == category


def test_an_earlier_risk_does_not_flag_a_safe_current_message():
    # the current message alone is checked; the earlier risk reaches the model as context
    history = [ConversationTurn("user", "I have sharp knee pain."), *exchanges(10)]
    provider = fake_provider(respond_turn("Try rowing.", "GENERAL_FITNESS", "ANSWER"))

    state = run(provider, FakeTools(), "What cardio can I do?", history)

    assert state["decision"].safety is SafetyCategory.SAFE
    context = sent(provider)[0].parts[0].text
    assert "the user mentioned: pain, an injury or a warning symptom" in context


def test_a_flagged_message_with_a_long_conversation_keeps_its_safe_path():
    tools = FakeTools()
    provider = fake_provider(
        respond_turn("Please see a physiotherapist.", "SAFETY_SENSITIVE", "SAFE_REDIRECT")
    )

    state = run(provider, tools, "I have sharp knee pain.", exchanges(100))

    assert tools.runs == []
    assert state["decision"] == CoachDecision(
        Intent.SAFETY_SENSITIVE, Decision.SAFE_REDIRECT, (), SafetyCategory.PAIN_OR_INJURY
    )


# the database stays the source of truth


def test_a_goal_from_the_conversation_is_not_an_answer_about_the_profile():
    history = [ConversationTurn("user", "My goal is muscle gain."), ConversationTurn("coach", "OK.")]
    tools = FakeTools(result=lambda item: {"output": {"profile": {"goal": "fat_loss"}}})
    provider = fake_provider(
        respond_turn("Your goal is muscle gain.", "PROFILE", "ANSWER"),
        respond_turn("Your goal is muscle gain.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
        tool_turn(call("get_user_profile")),
        respond_turn("Your stored goal is fat loss.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools, "What is my current goal?", history)

    rejected = [results_sent(provider, index)[-1]["error"]["code"] for index in (1, 2)]
    assert rejected == ["DECISION_REJECTED", "DECISION_REJECTED"]
    assert state["final_response"] == "Your stored goal is fat loss."
    assert state["decision"].tools_used == ("get_user_profile",)


# tool contracts are unchanged


def test_an_id_from_the_earlier_conversation_is_not_grounded():
    history = [ConversationTurn("user", "Plan 12 is my favourite.")]
    tools = FakeTools()
    provider = fake_provider(
        tool_turn(call("get_workout_plan", plan_id=12)),
        respond_turn("Which plan do you mean?", "WORKOUT_PLAN", "ASK_CLARIFICATION"),
    )

    run(provider, tools, "What is in that plan?", history)

    (guess,) = results_sent(provider, 1)
    assert guess["error"]["code"] == "ID_NOT_GROUNDED"
    assert tools.runs == []


def test_the_tool_call_limits_are_unchanged_with_a_conversation():
    provider = fake_provider(tool_turn(*[call("search_exercises", difficulty="BEGINNER")] * 21))

    with pytest.raises(AIProviderError, match="too many tool calls"):
        run(provider, FakeTools(), "Beginner exercises?", exchanges(30))


def test_the_iteration_limit_is_unchanged_with_a_conversation():
    provider = Mock(spec=GeminiProvider)
    provider.generate_turn.side_effect = [
        *[tool_turn(call("get_user_profile"))] * MAX_TOOL_ITERATIONS,
        respond_turn("Your goal is muscle gain.", "PROFILE", "ANSWER"),
    ]

    state = run(provider, FakeTools(), "What is my goal?", exchanges(30))

    assert provider.generate_turn.call_count == MAX_TOOL_ITERATIONS + 1
    assert state["final_response"] == CANNOT_ANSWER_REPLY


# the budget of each model request


def plan_rounds(count):
    return [tool_turn(call("get_workout_plan", plan_id=12)) for _ in range(count)]


def budget_for_rounds(count):
    """A budget that holds count rounds of BIG_PLAN, and no more."""
    messages = []
    for turn in plan_rounds(count):
        messages += [turn, ToolResult(call=turn.tool_calls[0], result=BIG_PLAN)]
    return request_size(COACH_INSTRUCTIONS, conversation("Compare plan 12", messages)) + 500


def test_older_results_are_compacted_when_a_turn_outgrows_its_budget():
    tools = FakeTools(result=lambda item: BIG_PLAN)
    provider = fake_provider(
        *plan_rounds(3),
        respond_turn("Plan 12 has one exercise.", "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools, "Compare plan 12", max_context_chars=budget_for_rounds(2))

    assert results_sent(provider, 1) == [BIG_PLAN]
    assert results_sent(provider, 2) == [BIG_PLAN, BIG_PLAN]
    assert results_sent(provider, 3) == [COMPACTED_RESULT, BIG_PLAN, BIG_PLAN]
    # the state keeps every result whole, for the decision policy
    assert [message.result for message in state["messages"][1::2]] == [BIG_PLAN] * 3
    assert state["context_compactions"] == 1
    assert state["decision"].tools_used == ("get_workout_plan",)


def test_an_id_from_a_compacted_result_stays_grounded():
    found = {"output": {"exercises": [{"exercise_id": 77, "notes": "x" * 5_000}]}}
    tools = FakeTools(result=lambda item: found if item.name == "search_exercises" else BIG_PLAN)
    provider = fake_provider(
        tool_turn(call("search_exercises", difficulty="BEGINNER")),
        tool_turn(call("get_workout_plan", plan_id=12)),
        tool_turn(call("get_exercise", exercise_id=77)),
        respond_turn("Exercise 77 it is.", "EXERCISE", "RETRIEVE_THEN_ANSWER"),
    )

    run(provider, tools, "Plan 12 and a beginner exercise?", max_context_chars=budget_for_rounds(2))

    assert results_sent(provider, 3)[0] == COMPACTED_RESULT
    assert [calls[0].name for calls, _ in tools.runs][-1] == "get_exercise"


def test_a_request_over_the_budget_is_never_sent():
    provider = fake_provider(respond_turn("Hi."))

    state = run(provider, FakeTools(), "Hi", max_context_chars=100)

    provider.generate_turn.assert_not_called()
    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert state["decision"] == CoachDecision(Intent.AMBIGUOUS, Decision.CANNOT_ANSWER, ())


def test_a_flagged_request_over_the_budget_gets_the_safe_reply():
    provider = fake_provider(respond_turn("Hi."))

    state = run(provider, FakeTools(), "I have sharp knee pain.", max_context_chars=100)

    provider.generate_turn.assert_not_called()
    rule = SAFETY_POLICY[SafetyCategory.PAIN_OR_INJURY]
    assert state["final_response"] == rule.fallback_reply


def test_a_turn_that_cannot_fit_after_its_tools_ends_without_the_model():
    tools = FakeTools(result=lambda item: BIG_PLAN)
    provider = fake_provider(*plan_rounds(1), respond_turn("Done."))

    # room for the first request, not for the latest round's result
    state = run(provider, tools, "Compare plan 12", max_context_chars=budget_for_rounds(0))

    assert provider.generate_turn.call_count == 1
    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert state["decision"] == CoachDecision(
        Intent.AMBIGUOUS, Decision.CANNOT_ANSWER, ("get_workout_plan",)
    )


def test_compactions_per_turn_are_capped():
    tools = FakeTools(result=lambda item: BIG_PLAN)
    provider = Mock(spec=GeminiProvider)
    provider.generate_turn.side_effect = lambda *a, **k: tool_turn(
        call("get_workout_plan", plan_id=12)
    )

    state = run(
        provider,
        tools,
        "Compare plan 12",
        # a run with a larger loop gives its own graph step limit
        config={"recursion_limit": 200},
        max_tool_iterations=50,
        max_context_chars=budget_for_rounds(2),
    )

    # the budget holds two rounds: requests 4 to 9 each needed a compaction, and
    # the 10th would exceed the cap, so it is not sent
    assert state["context_compactions"] == MAX_CONTEXT_COMPACTIONS
    assert provider.generate_turn.call_count == 3 + MAX_CONTEXT_COMPACTIONS
    assert state["final_response"] == CANNOT_ANSWER_REPLY


def test_compaction_is_logged_as_counts_not_content(caplog, monkeypatch):
    # Alembic's logging setup (migrations/env.py) disables existing loggers once an
    # integration test has run the migrations
    monkeypatch.setattr(logging.getLogger("app.agent.graph"), "disabled", False)
    tools = FakeTools(result=lambda item: BIG_PLAN)
    provider = fake_provider(*plan_rounds(3), respond_turn("Done.", "WORKOUT_PLAN", "CANNOT_ANSWER"))

    with caplog.at_level(logging.INFO, logger="app.agent.graph"):
        run(provider, tools, "Secret question about plan 12", max_context_chars=budget_for_rounds(2))

    (record,) = [r for r in caplog.records if r.getMessage().startswith("Context compacted")]
    assert record.getMessage().endswith("results_compacted=1 compactions=1")
    assert "Secret" not in caplog.text
    assert "xxxxx" not in caplog.text
