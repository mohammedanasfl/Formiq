"""Tests for how the coach graph applies the decision policy to a turn. The model
is a fake that plays both good and bad behavior (answering from memory, guessing
ids, ignoring errors); the tools are fakes. No test calls the Gemini API."""

from unittest.mock import Mock

import pytest
from google.genai import types
from langgraph.errors import GraphRecursionError

from app.agent import (
    CANNOT_ANSWER_REPLY,
    MAX_GRAPH_STEPS,
    MAX_TOOL_ITERATIONS,
    CoachContext,
    CoachDecision,
    Decision,
    Intent,
    coach_graph,
    initial_state,
)
from app.ai import GeminiProvider, ModelTurn, ToolCall, ToolResult
from tests.coach import (
    FakeTools,
    call,
    fake_provider,
    respond_turn,
    sent_contents,
    tool_responses,
    tool_turn,
)

USER = 7

SESSION_45 = {
    "output": {
        "session_id": 45,
        "workout_plan_id": 12,
        "status": "COMPLETED",
        "exercises": [{"exercise_id": 3, "sets": [{"set_number": 1, "reps": 8}]}],
        "truncated": False,
    }
}
PLAN_12 = {"output": {"plan_id": 12, "exercises": [{"exercise_id": 3, "reps": 10}]}}
PROFILE = {"output": {"user_id": USER, "profile": {"goal": "muscle_gain"}}}
NOT_FOUND = {"error": {"code": "RESOURCE_NOT_FOUND", "message": "the user has no session 45"}}


def tools_returning(**results):
    """Tools that answer each tool by name, with an empty output for any other."""
    return FakeTools(result=lambda item: results.get(item.name, {"output": {}}))


def run(provider, tools, message, **context):
    return coach_graph.invoke(
        initial_state(message),
        context=CoachContext(user_id=USER, provider=provider, tools=tools, **context),
    )


def last_results(provider, request):
    """What the model was given, in its request-th request, for its last turn's calls."""
    return [response.response for response in tool_responses(sent_contents(provider, request)[-1])]


def rejected(result):
    return result["error"]["code"] == "DECISION_REJECTED"


# 1, 8: general knowledge needs no lookup


def test_a_general_question_is_answered_without_formiq_data():
    tools = FakeTools()
    provider = fake_provider(
        respond_turn("Add load, reps or sets over time.", "GENERAL_FITNESS", "ANSWER")
    )

    state = run(provider, tools, "What is progressive overload?")

    assert state["final_response"] == "Add load, reps or sets over time."
    assert state["decision"] == CoachDecision(Intent.GENERAL_FITNESS, Decision.ANSWER, ())
    assert tools.runs == []
    assert provider.generate_turn.call_count == 1


# 2, 9: stored data must be retrieved, not answered from memory


def test_a_profile_answer_from_memory_is_rejected_until_the_profile_is_read():
    tools = tools_returning(get_user_profile=PROFILE)
    provider = fake_provider(
        respond_turn("Your goal is fat loss.", "PROFILE", "ANSWER"),
        respond_turn("Your goal is fat loss.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
        tool_turn(call("get_user_profile")),
        respond_turn("Your goal is muscle gain.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools, "What is my current goal?")

    # neither guess reached the user; the answer came after the profile was read
    assert state["final_response"] == "Your goal is muscle gain."
    assert state["decision"] == CoachDecision(
        Intent.PROFILE, Decision.RETRIEVE_THEN_ANSWER, ("get_user_profile",)
    )
    (memory,) = last_results(provider, 1)
    (claimed,) = last_results(provider, 2)
    assert "ANSWER is not a decision for a PROFILE request" in memory["error"]["message"]
    assert "none was returned" in claimed["error"]["message"]
    assert [name for calls, _ in tools.runs for name in (c.name for c in calls)] == [
        "get_user_profile"
    ]


def test_a_decision_without_the_needed_data_never_reaches_the_user():
    provider = Mock(spec=GeminiProvider)
    provider.generate_turn.side_effect = lambda *args, **kwargs: respond_turn(
        "You squatted 140 kg.", "WORKOUT_HISTORY", "RETRIEVE_THEN_ANSWER"
    )

    state = run(provider, FakeTools(), "What did I squat?", max_tool_iterations=2)

    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert state["decision"] == CoachDecision(
        Intent.WORKOUT_HISTORY, Decision.CANNOT_ANSWER, ()
    )
    assert provider.generate_turn.call_count == 3  # the limit, then the last chance


# 3: workout history needs the session


def test_history_needs_the_session_not_other_data():
    tools = tools_returning(get_user_profile=PROFILE, get_workout_session=SESSION_45)
    provider = fake_provider(
        tool_turn(call("get_user_profile")),
        respond_turn("You did 8 reps.", "WORKOUT_HISTORY", "RETRIEVE_THEN_ANSWER"),
        tool_turn(call("get_workout_session", session_id=45)),
        respond_turn("You did 8 reps.", "WORKOUT_HISTORY", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools, "How many reps did I do in session 45?")

    (premature,) = last_results(provider, 2)
    assert "get_workout_session returned" in premature["error"]["message"]
    assert state["decision"].tools_used == ("get_user_profile", "get_workout_session")


# 4: several tools before a comparison


def test_a_comparison_uses_the_session_and_its_plan_before_answering():
    tools = tools_returning(get_workout_session=SESSION_45, get_workout_plan=PLAN_12)
    provider = fake_provider(
        tool_turn(call("get_workout_session", session_id=45)),
        # plan 12 comes from the session's data, not from the user
        tool_turn(call("get_workout_plan", plan_id=12)),
        respond_turn("You did 8 of 10 reps.", "WORKOUT_HISTORY", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools, "Did I hit my prescribed reps in session 45?")

    assert [calls[0].name for calls, _ in tools.runs] == ["get_workout_session", "get_workout_plan"]
    assert state["decision"] == CoachDecision(
        Intent.WORKOUT_HISTORY,
        Decision.RETRIEVE_THEN_ANSWER,
        ("get_workout_session", "get_workout_plan"),
    )


def test_a_decision_made_alongside_tool_calls_is_rejected():
    # the model cannot decide before it has seen the data it asked for
    tools = tools_returning(get_workout_session=SESSION_45)
    provider = fake_provider(
        tool_turn(
            call("get_workout_session", session_id=45),
            call(
                "respond",
                intent="WORKOUT_HISTORY",
                decision="RETRIEVE_THEN_ANSWER",
                reply="You hit every rep.",
            ),
        ),
        respond_turn("You did 8 reps.", "WORKOUT_HISTORY", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools, "Did I hit my reps in session 45?")

    session, early_decision = last_results(provider, 1)
    assert session == SESSION_45
    assert rejected(early_decision)
    assert "call respond alone" in early_decision["error"]["message"]
    assert state["final_response"] == "You did 8 reps."


# 5, 10: missing or unusable data is not filled in


@pytest.mark.parametrize(
    "result",
    [
        NOT_FOUND,
        {"error": {"code": "TOOL_ERROR", "message": "the data could not be read"}},
        {},
        {"output": "Session 45: 5 x 5 at 100 kg"},
    ],
    ids=["not found", "tool error", "empty result", "malformed output"],
)
def test_without_usable_data_the_model_must_not_answer_from_it(result):
    tools = tools_returning(get_workout_session=result)
    provider = fake_provider(
        tool_turn(call("get_workout_session", session_id=45)),
        respond_turn("You did 5 x 5.", "WORKOUT_HISTORY", "RETRIEVE_THEN_ANSWER"),
        respond_turn("I could not load session 45.", "WORKOUT_HISTORY", "CANNOT_ANSWER"),
    )

    state = run(provider, tools, "What did I do in session 45?")

    (fabricated,) = last_results(provider, 2)
    assert rejected(fabricated)
    assert state["final_response"] == "I could not load session 45."
    assert state["decision"] == CoachDecision(
        Intent.WORKOUT_HISTORY, Decision.CANNOT_ANSWER, ()
    )


def test_incomplete_data_can_be_answered_from():
    truncated = {"output": {**SESSION_45["output"], "truncated": True}}
    provider = fake_provider(
        tool_turn(call("get_workout_session", session_id=45)),
        respond_turn("Here are the first 30 exercises.", "WORKOUT_HISTORY", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools_returning(get_workout_session=truncated), "Session 45?")

    assert state["decision"].decision is Decision.RETRIEVE_THEN_ANSWER


# 6: ambiguity


def test_an_ambiguous_request_is_clarified_not_guessed():
    provider = fake_provider(
        respond_turn("Added 5 kg to everything.", "AMBIGUOUS", "ANSWER"),
        respond_turn(
            "Harder how: more weight, more reps or less rest?", "AMBIGUOUS", "ASK_CLARIFICATION"
        ),
    )

    state = run(provider, FakeTools(), "Make it harder.")

    assert rejected(last_results(provider, 1)[0])
    assert state["final_response"] == "Harder how: more weight, more reps or less rest?"
    assert state["decision"].decision is Decision.ASK_CLARIFICATION


# 7: safety


@pytest.mark.parametrize("decision", ["ANSWER", "RETRIEVE_THEN_ANSWER", "ASK_CLARIFICATION"])
def test_a_safety_sensitive_request_is_only_redirected(decision):
    provider = fake_provider(
        respond_turn("Push through it.", "SAFETY_SENSITIVE", decision),
        respond_turn("Please see a physiotherapist.", "SAFETY_SENSITIVE", "SAFE_REDIRECT"),
    )

    # a risk only the model recognizes: the safety backstop finds no obvious signal,
    # so the decision policy alone keeps the request to a redirect
    state = run(provider, FakeTools(), "Can I do box jumps on my bad knee?")

    assert rejected(last_results(provider, 1)[0])
    assert state["final_response"] == "Please see a physiotherapist."
    assert state["decision"] == CoachDecision(
        Intent.SAFETY_SENSITIVE, Decision.SAFE_REDIRECT, ()
    )


# 8: no guessed ids


def test_a_guessed_equipment_id_is_rejected_before_any_tool_runs():
    # the model cannot know which id "dumbbells" has; it guessed 3 (Kettlebell) live
    tools = tools_returning()
    provider = fake_provider(
        tool_turn(call("search_exercises", equipment_id=3, movement_pattern="HORIZONTAL_PUSH")),
        tool_turn(call("search_exercises", movement_pattern="HORIZONTAL_PUSH")),
        respond_turn("Try a push-up.", "EXERCISE", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools, "I only have dumbbells. Give me a chest exercise.")

    (guess,) = last_results(provider, 1)
    assert guess["error"]["code"] == "ID_NOT_GROUNDED"
    assert "equipment_id=3" in guess["error"]["message"]
    # only the search without a guessed id ran
    assert [[(c.name, c.arguments) for c in calls] for calls, _ in tools.runs] == [
        [("search_exercises", {"movement_pattern": "HORIZONTAL_PUSH"})]
    ]
    assert state["decision"].tools_used == ("search_exercises",)


def test_ids_returned_by_a_tool_may_be_used():
    tools = tools_returning(search_exercises={"output": {"exercises": [{"exercise_id": 7}]}})
    provider = fake_provider(
        tool_turn(call("search_exercises", difficulty="BEGINNER")),
        tool_turn(call("get_exercise", exercise_id=7)),
        respond_turn("Try exercise 7.", "EXERCISE", "RETRIEVE_THEN_ANSWER"),
    )

    run(provider, tools, "A beginner exercise?")

    assert [calls[0].name for calls, _ in tools.runs] == ["search_exercises", "get_exercise"]


def test_an_id_is_known_only_after_the_tool_returned_it():
    # an id from the same turn's calls is still a guess when the call is made
    tools = tools_returning(search_exercises={"output": {"exercises": [{"exercise_id": 7}]}})
    provider = fake_provider(
        tool_turn(
            call("search_exercises", difficulty="BEGINNER"), call("get_exercise", exercise_id=7)
        ),
        respond_turn("Try a beginner exercise.", "EXERCISE", "RETRIEVE_THEN_ANSWER"),
    )

    run(provider, tools, "A beginner exercise?")

    search, guess = last_results(provider, 1)
    assert "output" in search
    assert guess["error"]["code"] == "ID_NOT_GROUNDED"


# 11: bounded, controlled failure


def test_a_model_that_never_reaches_an_acceptable_decision_is_stopped():
    provider = Mock(spec=GeminiProvider)
    provider.generate_turn.side_effect = lambda *args, **kwargs: respond_turn(
        "Your goal is fat loss.", "PROFILE", "ANSWER"
    )

    state = run(provider, FakeTools(), "What is my goal?", max_tool_iterations=3)

    assert provider.generate_turn.call_count == 4
    assert state["iteration_count"] == 4
    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert state["decision"] == CoachDecision(Intent.PROFILE, Decision.CANNOT_ANSWER, ())
    # past the limit the model was only allowed to decide
    assert provider.generate_turn.call_args.kwargs["required_tool_names"] == ["respond"]


def test_two_decisions_at_the_limit_end_the_turn_instead_of_looping():
    provider = fake_provider(
        tool_turn(call("get_user_profile")),
        tool_turn(
            call("respond", intent="PROFILE", decision="RETRIEVE_THEN_ANSWER", reply="A"),
            call("respond", intent="PROFILE", decision="RETRIEVE_THEN_ANSWER", reply="B"),
        ),
    )

    state = run(provider, tools_returning(get_user_profile=PROFILE), "Goal?", max_tool_iterations=1)

    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert provider.generate_turn.call_count == 2


@pytest.mark.parametrize(
    "arguments",
    [
        {"intent": "MOOD", "decision": "ANSWER", "reply": "Hi"},
        {"intent": "GENERAL_FITNESS", "decision": "ANSWER", "reply": "Hi", "reasoning": "x"},
    ],
    ids=["unknown intent", "reasoning field"],
)
def test_an_invalid_decision_is_sent_back_to_the_model(arguments):
    provider = fake_provider(
        tool_turn(ToolCall("respond", arguments, "r1")),
        respond_turn("Hi there."),
    )

    state = run(provider, FakeTools(), "Hi")

    (invalid,) = last_results(provider, 1)
    assert invalid["error"]["message"].startswith("invalid respond call: ")
    assert state["final_response"] == "Hi there."


def test_an_invalid_last_decision_ends_with_cannot_answer():
    provider = fake_provider(tool_turn(ToolCall("respond", {"reply": "Hi"}, "r1")))

    state = run(provider, FakeTools(), "Hi", max_tool_iterations=0)

    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert state["decision"] == CoachDecision(Intent.AMBIGUOUS, Decision.CANNOT_ANSWER, ())


# 14: deterministic


def test_the_same_turn_gives_the_same_decision():
    def scenario():
        provider = fake_provider(
            tool_turn(ToolCall("get_workout_session", {"session_id": 45}, "s")),
            ModelTurn(
                content=types.Content(role="model", parts=[types.Part(text="respond")]),
                tool_calls=(
                    ToolCall(
                        "respond",
                        {"intent": "WORKOUT_HISTORY", "decision": "CANNOT_ANSWER", "reply": "No."},
                        "r",
                    ),
                ),
            ),
        )
        state = run(provider, tools_returning(get_workout_session=NOT_FOUND), "Session 45?")
        return state, [request.args for request in provider.generate_turn.call_args_list]

    assert scenario() == scenario()


# no reasoning is exposed or kept


def test_only_the_reply_reaches_the_user_never_the_models_thoughts():
    thinking = ModelTurn(
        content=types.Content(
            role="model",
            parts=[
                types.Part(text="The user probably wants fat loss.", thought=True),
                types.Part(
                    function_call=types.FunctionCall(
                        id="r",
                        name="respond",
                        args={"intent": "GENERAL_FITNESS", "decision": "ANSWER", "reply": "Hi!"},
                    )
                ),
            ],
        ),
        text="The user probably wants fat loss.",
        tool_calls=(
            ToolCall(
                "respond",
                {"intent": "GENERAL_FITNESS", "decision": "ANSWER", "reply": "Hi!"},
                "r",
            ),
        ),
    )

    state = run(fake_provider(thinking), FakeTools(), "Hello")

    assert state["final_response"] == "Hi!"
    assert "fat loss" not in repr(state["decision"])
    assert set(state) == {
        "user_message",
        "messages",
        "iteration_count",
        "final_response",
        "decision",
    }


def test_the_decisions_results_reach_the_model_as_data():
    provider = fake_provider(
        respond_turn("Muscle gain.", "PROFILE", "ANSWER"),
        respond_turn("Let me check.", "PROFILE", "CANNOT_ANSWER"),
    )

    state = run(provider, FakeTools(), "My goal?")

    # the rejection is the respond call's result, not a user message
    second_request = sent_contents(provider, 1)
    assert [content.role for content in second_request] == ["user", "model", "user"]
    assert [part.text for part in second_request[2].parts] == [None]
    assert isinstance(state["messages"][1], ToolResult)


# the graph's own step limit, behind the loop's


def test_the_longest_legal_turn_fits_the_graphs_step_limit():
    assert MAX_GRAPH_STEPS == 2 * (MAX_TOOL_ITERATIONS + 1) + 1
    provider = Mock(spec=GeminiProvider)
    provider.generate_turn.side_effect = lambda *args, **kwargs: respond_turn(
        "Your goal is fat loss.", "PROFILE", "ANSWER"
    )

    # the default limit: every round rejected, then the forced decision
    state = run(provider, FakeTools(), "What is my goal?")

    assert provider.generate_turn.call_count == MAX_TOOL_ITERATIONS + 1
    assert state["final_response"] == CANNOT_ANSWER_REPLY


def test_a_loop_beyond_the_step_limit_is_stopped_by_the_graph():
    provider = Mock(spec=GeminiProvider)
    provider.generate_turn.side_effect = lambda *args, **kwargs: respond_turn(
        "Your goal is fat loss.", "PROFILE", "ANSWER"
    )

    # a context allowing more rounds than the compiled graph's steps
    with pytest.raises(GraphRecursionError):
        run(provider, FakeTools(), "What is my goal?", max_tool_iterations=50)

    # at most one model request beyond the longest legal turn
    assert provider.generate_turn.call_count == MAX_TOOL_ITERATIONS + 2
