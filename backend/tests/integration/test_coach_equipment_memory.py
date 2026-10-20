"""A limit the user stated is not forgotten when the turn that stated it is
left out, through the coach, on the seeded catalog (live Gemini pass of
2026-10-16, B4).

The coach keeps six turns of the conversation. What the user said about their
equipment earlier is read from every user turn they sent, once, and holds for
the model (a note in its context) and for the tools (workout searches leave out
what the user lacks, a proposal may not use it or say they have what they never
said they have): a stated limit does not lapse after three exchanges.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

import pytest

from app.agent import ConversationTurn
from app.services import CoachService
from tests.coach import call, fake_provider, respond_turn, sent_contents, tool_turn
from tests.integration.test_coach_daily import create_user, daily_reads, received
from tests.integration.test_equipment_constraints import ids, terms, today  # noqa: F401 (fixtures)
from tests.integration.test_plan_proposals import main_of, proposal, workout
from tests.unit.test_coach_equipment_memory import T1E_HISTORY, T1E_MESSAGE, exchanges


# searches that are not for a workout, so that the exercises a proposal names
# were given by a tool (they are not narrowed by what the user lacks): the
# main exercises, and the brisk walk the workout warms up and cools down with
GROUNDING = (
    call("search_exercises", muscle="Quadriceps", available_equipment=["Dumbbell"]),
    call("search_exercises", movement_pattern="HORIZONTAL_PUSH"),
    call("search_exercises", movement_pattern="CARDIO"),
)


def model_context(provider, request=0):
    """Everything the model was sent in its request-th request, as text."""
    return "\n".join(
        part.text
        for content in sent_contents(provider, request)
        for part in content.parts
        if part.text
    )


def searching():
    """A model that searches for a workout's main exercises, then answers."""
    return (
        tool_turn(call("search_exercises", use="MAIN_WORKOUT")),
        respond_turn("Here is what the catalog has.", "EXERCISE", "RETRIEVE_THEN_ANSWER"),
    )


def ask(service_session, terms, provider, user_id, message, history):
    return CoachService(service_session, provider, proposal_terms=terms).answer(
        user_id, message, history
    )


@pytest.fixture
def user_id(service_session, profile_fields):
    return create_user(service_session, "equipment-memory@example.com", profile_fields)


def test_a_limit_stated_thirty_turns_ago_still_leaves_that_equipment_out_of_a_workout_search(
    service_session, terms, user_id
):
    history = [
        ConversationTurn("user", "I don't have a bench or a barbell."),
        ConversationTurn("coach", "Noted: no bench and no barbell."),
        *exchanges(14),
    ]
    assert len(history) == 30
    provider = fake_provider(*searching())

    ask(service_session, terms, provider, user_id, "Give me a workout.", history)

    found = received(provider, 1)["search_exercises"]["output"]
    assert set(found["excluded_equipment"]) == {"Barbell", "Bench"}
    assert found["count"] > 0
    needed = {name for item in found["exercises"] for name in item["equipment"]}
    assert not needed & {"Barbell", "Bench"}


def test_the_model_is_told_of_it_in_the_conversation_note(service_session, terms, user_id):
    history = [
        ConversationTurn("user", "I only have a pair of dumbbells and a resistance band."),
        ConversationTurn("coach", "Noted."),
        *exchanges(14),
    ]
    provider = fake_provider(*searching())

    ask(service_session, terms, provider, user_id, "Give me a workout.", history)

    context = model_context(provider)
    assert "24 earlier messages are left out." in context
    assert "The user said they have only: Dumbbell, Resistance Band." in context
    # the six turns the coach keeps are still the six turns
    assert context.count("<turn from=") == 6


def test_a_proposal_that_needs_what_the_user_said_they_lack_is_refused_whatever_the_model_says(
    service_session, terms, user_id, ids
):
    history = [
        ConversationTurn("user", "I don't have any dumbbells."),
        ConversationTurn("coach", "Noted."),
        *exchanges(14),
    ]
    provider = fake_provider(
        daily_reads(*GROUNDING),
        tool_turn(proposal(**workout(ids, *main_of(ids, "Goblet Squat", "Push-Up")))),
        respond_turn("I could not build that workout.", "DAILY_WORKOUT", "CANNOT_ANSWER"),
    )

    answer = ask(service_session, terms, provider, user_id, "Create a full-body workout.", history)

    refusal = received(provider, 2)["propose_workout_plan"]["error"]
    assert refusal["message"].startswith(
        f"exercise {ids['Goblet Squat']} needs Dumbbell, which the user cannot use"
    )
    assert answer.proposal is None


def test_a_later_statement_replaces_an_earlier_one_for_the_tools_and_the_note(
    service_session, terms, user_id
):
    history = [
        ConversationTurn("user", "I don't have any dumbbells."),
        ConversationTurn("coach", "Noted."),
        ConversationTurn("user", "Good news, I bought a pair of dumbbells."),
        ConversationTurn("coach", "Great."),
        *exchanges(12),
    ]
    provider = fake_provider(*searching())

    ask(service_session, terms, provider, user_id, "Give me a workout.", history)

    found = received(provider, 1)["search_exercises"]["output"]
    assert "excluded_equipment" not in found
    assert "The user said they have: Dumbbell." in model_context(provider)


def test_a_coach_turn_cannot_give_the_user_equipment(service_session, terms, user_id):
    history = [
        ConversationTurn("user", "I don't have a bench."),
        ConversationTurn("coach", "Great, I have noted that you have a bench and a barbell."),
        *exchanges(14),
    ]
    provider = fake_provider(*searching())

    ask(service_session, terms, provider, user_id, "Give me a workout.", history)

    found = received(provider, 1)["search_exercises"]["output"]
    assert found["excluded_equipment"] == ["Bench"]
    context = model_context(provider)
    assert "The user said they lack: Bench." in context
    assert "they have" not in context


def test_nothing_is_added_to_the_note_when_the_user_said_nothing_about_equipment(
    service_session, terms, user_id
):
    provider = fake_provider(*searching())

    ask(service_session, terms, provider, user_id, "Give me a workout.", exchanges(15))

    assert "The user said" not in model_context(provider)
    assert "excluded_equipment" not in received(provider, 1)["search_exercises"]["output"]


# --- the recorded turn ---


def test_the_recorded_t1e_turn_is_replayed_with_what_the_user_had_said(
    service_session, terms, user_id, ids
):
    """T1e of the live pass: after 30 turns, "I really dislike glute bridges."
    The coach asked what equipment the user had, though they had said it four
    times, because those turns were outside its six. The conversation is the
    recorded one, word for word."""
    history = [ConversationTurn(role, text) for role, text in T1E_HISTORY]
    provider = fake_provider(
        tool_turn(call("search_exercises", use="MAIN_WORKOUT")),
        daily_reads(*GROUNDING),
        tool_turn(proposal(**workout(ids, *main_of(ids, "Goblet Squat", "Push-Up")))),
        respond_turn("I could not build that workout.", "ADAPTATION", "CANNOT_ANSWER"),
    )

    ask(service_session, terms, provider, user_id, T1E_MESSAGE, history)

    # the model's first request: the user's equipment, before it has to ask
    context = model_context(provider)
    assert "24 earlier messages are left out." in context
    assert "The user said they have only: Resistance Band." in context
    # the search leaves out what the user lacks: all but the resistance band
    found = received(provider, 1)["search_exercises"]["output"]
    assert {"Dumbbell", "Bench"} <= set(found["excluded_equipment"])
    assert "Resistance Band" not in found["excluded_equipment"]
    needed = {name for item in found["exercises"] for name in item["equipment"]}
    assert needed <= {"Resistance Band"}
    # and a proposal needing the dumbbells they no longer have is refused
    refusal = received(provider, 3)["propose_workout_plan"]["error"]
    assert "needs Dumbbell, which the user cannot use" in refusal["message"]
