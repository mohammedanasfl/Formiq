"""The coach's discovery reads: "my current plan" and "my last workout" reach
get_current_workout_plan and get_latest_workout_session, for the trusted user,
and an answer about them still needs their data from this turn.

The model and the tools are fakes: no test calls Gemini or the database.
"""

import pytest

from app.agent import CoachContext, coach_graph, initial_state
from app.tools import TOOL_DECLARATIONS
from tests.coach import FakeTools, call, fake_provider, respond_turn, tool_turn
from tests.unit.test_coach_injection import results_sent

USER = 7
CASES = {
    "current_plan": (
        "What is my current workout plan?",
        "get_current_workout_plan",
        "WORKOUT_PLAN",
    ),
    "last_workout": (
        "What exercises did I do in my last workout?",
        "get_latest_workout_session",
        "WORKOUT_HISTORY",
    ),
}


class DiscoveryTools(FakeTools):
    declarations = TOOL_DECLARATIONS


def run(provider, tools, message):
    return coach_graph.invoke(
        initial_state(message),
        context=CoachContext(user_id=USER, provider=provider, tools=tools),
    )


@pytest.mark.parametrize("case", CASES)
def test_the_question_is_answered_from_the_discovery_tool_without_an_id(case):
    message, tool, intent = CASES[case]
    tools = DiscoveryTools(result=lambda item: {"output": {"name": "Upper Body A"}})
    provider = fake_provider(
        tool_turn(call(tool)),
        respond_turn("It is Upper Body A.", intent, "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools, message)

    # read for the trusted user, with no id from anyone
    assert [([c.name for c in calls], user) for calls, user in tools.runs] == [
        ([tool], USER)
    ]
    assert tools.runs[0][0][0].arguments == {}
    assert state["decision"].decision == "RETRIEVE_THEN_ANSWER"
    assert state["decision"].tools_used == (tool,)
    assert state["final_response"] == "It is Upper Body A."


@pytest.mark.parametrize("case", CASES)
def test_an_answer_without_this_turns_data_is_still_rejected(case):
    message, _, intent = CASES[case]
    provider = fake_provider(
        respond_turn("Your plan is Upper Body A.", intent, "RETRIEVE_THEN_ANSWER"),
        respond_turn("I need to check that first.", intent, "CANNOT_ANSWER"),
    )

    state = run(provider, DiscoveryTools(), message)

    (rejection,) = results_sent(provider, 1)
    assert rejection["error"]["code"] == "DECISION_REJECTED"
    assert state["decision"].decision == "CANNOT_ANSWER"


@pytest.mark.parametrize("case", CASES)
def test_nothing_found_is_no_evidence(case):
    message, tool, intent = CASES[case]
    tools = DiscoveryTools(
        result=lambda item: {
            "error": {"code": "RESOURCE_NOT_FOUND", "message": "none yet"}
        }
    )
    provider = fake_provider(
        tool_turn(call(tool)),
        respond_turn("It is Upper Body A.", intent, "RETRIEVE_THEN_ANSWER"),
        respond_turn("You don't have one yet.", intent, "CANNOT_ANSWER"),
    )

    state = run(provider, tools, message)

    assert results_sent(provider, 2)[0]["error"]["code"] == "DECISION_REJECTED"
    assert state["final_response"] == "You don't have one yet."
