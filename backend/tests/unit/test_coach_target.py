"""The saved plan a coach request names (CoachContext.target_plan_id): what the
model is told of it, the id it makes usable, and what it never changes. The
model and the tools are fakes: no test calls the Gemini API or reads the
database. tests/integration/test_coach_target.py has the whole request."""

import inspect

from app.agent import (
    COACH_INSTRUCTIONS,
    SAFETY_POLICY,
    CoachContext,
    SafetyCategory,
    coach_graph,
    initial_state,
)
from app.agent.graph import (
    PendingProposal,
    coach_instructions,
    known_ids_of,
    pending_note,
    safety_instructions,
    target_note,
)
from app.agent.policy import known_ids
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
PLAN = 41
ANSWER = "Start with three sets of eight."


def context(**fields):
    return CoachContext(user_id=USER, provider=fake_provider(), tools=FakeTools(), **fields)


def run(provider, tools, message="Make it a little harder", **fields):
    return coach_graph.invoke(
        initial_state(message),
        context=CoachContext(user_id=USER, provider=provider, tools=tools, **fields),
    )


def result_of(provider, request, index=0):
    """The result the model got for its index-th call of the previous round."""
    return tool_responses(sent_contents(provider, request)[-1])[index].response


# --- what the model is told ---


def test_a_request_with_no_plan_and_no_proposal_waiting_gives_the_instructions_unchanged():
    assert coach_instructions(context()) == COACH_INSTRUCTIONS


def test_a_proposal_waiting_is_told_as_it_always_was():
    waiting = PendingProposal(expires_in_minutes=12, revises_plan_id=PLAN)

    assert coach_instructions(context(pending_proposal=waiting)) == (
        f"{COACH_INSTRUCTIONS}\n\n{pending_note(waiting)}"
    )


def test_the_plan_the_request_names_is_told_by_its_number_only():
    told = coach_instructions(context(target_plan_id=PLAN))

    assert told == f"{COACH_INSTRUCTIONS}\n\n{target_note(PLAN)}"
    assert f"workout plan {PLAN}" in told
    assert f"revises_plan_id {PLAN}" in told
    assert "get_workout_plan (plan_id 41)" in told
    # written from the number alone: no name or text of the user's or a plan's can be in it
    assert {name: item.annotation for name, item in inspect.signature(target_note).parameters.items()} == {
        "plan_id": int
    }


def test_the_plan_and_the_proposal_waiting_are_both_told_the_plan_first():
    waiting = PendingProposal(expires_in_minutes=12)

    told = coach_instructions(context(target_plan_id=PLAN, pending_proposal=waiting))

    assert told == f"{COACH_INSTRUCTIONS}\n\n{target_note(PLAN)}\n\n{pending_note(waiting)}"


def test_the_model_gets_the_note_with_its_first_request():
    provider = fake_provider(respond_turn(ANSWER))

    run(provider, FakeTools(), target_plan_id=PLAN)

    assert provider.generate_turn.call_args_list[0].kwargs["instructions"] == (
        f"{COACH_INSTRUCTIONS}\n\n{target_note(PLAN)}"
    )


def test_a_flagged_request_is_told_nothing_of_the_plan_and_reads_nothing():
    category = SafetyCategory.PAIN_OR_INJURY
    tools = FakeTools()
    provider = fake_provider(
        tool_turn(call("get_workout_plan", plan_id=PLAN)),
        respond_turn("Please see a physiotherapist.", "SAFETY_SENSITIVE", "SAFE_REDIRECT"),
    )

    run(provider, tools, message="I have sharp knee pain, change this workout", target_plan_id=PLAN)

    sent = provider.generate_turn.call_args_list[0].kwargs
    assert sent["instructions"] == safety_instructions(SAFETY_POLICY[category])
    assert target_note(PLAN) not in sent["instructions"]
    assert tools.runs == []


# --- the id it makes usable ---


def test_the_plan_the_request_names_is_an_id_the_turn_may_use():
    assert known_ids_of(context(target_plan_id=PLAN), "make it harder", []) == {PLAN}
    assert known_ids_of(context(), "make it harder", []) == set()
    # the numbers the user wrote and the ids tools returned are kept
    assert known_ids_of(context(target_plan_id=PLAN), "do 12 reps", []) == {PLAN, 12}
    assert known_ids("do 12 reps", []) == {12}


def test_the_model_may_read_the_plan_the_request_names_without_the_user_naming_it():
    tools = FakeTools()
    provider = fake_provider(
        tool_turn(call("get_workout_plan", plan_id=PLAN)),
        respond_turn(ANSWER),
    )

    run(provider, tools, target_plan_id=PLAN)

    assert [item.name for calls, _ in tools.runs for item in calls] == ["get_workout_plan"]


def test_without_a_plan_the_same_read_is_an_id_nobody_gave():
    tools = FakeTools()
    provider = fake_provider(
        tool_turn(call("get_workout_plan", plan_id=PLAN)),
        respond_turn(ANSWER),
    )

    run(provider, tools)

    assert tools.runs == []
    assert result_of(provider, 1)["error"]["code"] == "ID_NOT_GROUNDED"


def test_the_plan_the_request_names_makes_no_other_id_usable():
    tools = FakeTools()
    provider = fake_provider(
        tool_turn(call("get_workout_plan", plan_id=PLAN + 1)),
        respond_turn(ANSWER),
    )

    run(provider, tools, target_plan_id=PLAN)

    assert tools.runs == []
    assert result_of(provider, 1)["error"]["code"] == "ID_NOT_GROUNDED"
