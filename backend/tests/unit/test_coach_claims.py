"""What a reply may claim about workouts (app.agent.trust.reply_problem): only
what Formiq's records and the turn back.

A reply may say the coach made, changed or rewrote a workout, or that a new
version is ready to approve, only when the turn made a proposal that Formiq
accepted. With an earlier proposal awaiting approval, it may point to that
one, as it is. The live QA (2026-10-15) saw "I have rewritten your core plan
... approve it directly in Formiq" pass with no proposal made: the rule now
reads what a reply claims from every form of the verbs, not a short list of
the words one reply used. A reply may not say the user did an exercise that
the workout session read in the turn shows no completed set of.

The checks are pure: no model, no tools.
"""

import pytest

from app.agent.trust import (
    CHANGING_VERBS,
    MAKING_VERBS,
    REPLY_CLAIMS_CREATION,
    REPLY_CLAIMS_NEW_PROPOSAL,
    REPLY_CLAIMS_PROPOSAL,
    REPLY_CLAIMS_UNDONE,
    reply_problem,
    verb_forms,
)

INSTRUCTIONS = "You are a fitness coach."


def problem(reply, *, proposed=False, awaiting=False, not_done=()):
    return reply_problem(
        reply,
        INSTRUCTIONS,
        [],
        proposed=proposed,
        awaiting_approval=awaiting,
        not_done=not_done,
    )


# the live QA's reply, and the phrasings the brief names
CLAIMS = [
    "I have rewritten your core plan with new ab exercises. You can approve it directly in Formiq.",
    "I have rewritten your plan.",
    "I regenerated the workout.",
    "Your revised plan is ready.",
    "Approve the new version.",
    # other verbs and forms
    "I've reworked your routine around your knees.",
    "I just redid the session with lighter sets.",
    "I rebuilt your plan to fit 20 minutes.",
    "I've put together a 20-minute session for you.",
    "I came up with a new core workout.",
    "I've swapped the lunges for squats.",
    "I've swapped out the lunges.",
    "We have restructured your program.",
    "I went ahead and simplified the workout.",
    "I've modified it to suit your equipment.",
    "Your updated workout is now ready.",
    "The rewritten version is below.",
    "Here's the updated workout.",
    "Here is a new 20-minute plan.",
    "Your shorter session is ready to go.",
    "Please approve the revised plan when you're ready.",
]


@pytest.mark.parametrize("reply", CLAIMS)
def test_a_claim_of_a_new_or_changed_workout_needs_a_proposal_made_in_the_turn(reply):
    # no proposal at all: it would point the user to nothing
    assert problem(reply) in (REPLY_CLAIMS_CREATION, REPLY_CLAIMS_PROPOSAL)
    # one awaiting approval: the user would approve it believing it changed
    assert problem(reply, awaiting=True) in (REPLY_CLAIMS_CREATION, REPLY_CLAIMS_NEW_PROPOSAL)
    # the turn's own proposal backs it
    assert problem(reply, proposed=True) is None


@pytest.mark.parametrize(
    "reply",
    [
        "Your current plan is Core Crusher, scheduled for Friday.",
        "I can propose a new workout if you like.",
        "Would you like me to make it shorter?",
        "I checked your plan: it has three core exercises.",
        "I made sure the workout fits your 20 minutes.",
        "I've made sure nothing needs equipment.",
        "I chose Bird Dog because it trains your core without equipment.",
        "I included a warm-up to prepare your hips.",
        "I've kept your plan as it is.",
        "Progressive overload means gradually increasing the load over time.",
        "You can change the plan yourself in Formiq.",
        "Your plan was saved as plan 7 when you approved it.",
        "Formiq has no saved plan for you yet.",
    ],
)
def test_explaining_or_offering_is_no_claim(reply):
    assert problem(reply) is None
    assert problem(reply, awaiting=True) is None


@pytest.mark.parametrize(
    "reply",
    [
        "The proposal awaiting your approval swaps crunches for Bird Dog and shortens the rest.",
        "Your proposal is still waiting: review and approve it in Formiq.",
        "It includes Bird Dog, Dead Bug and Plank, about 25 minutes in all.",
    ],
)
def test_the_proposal_awaiting_approval_may_be_described_as_it_is(reply):
    assert problem(reply, awaiting=True) is None


@pytest.mark.parametrize(
    ("verb", "forms"),
    [
        ("rewrite", ("rewrote", "rewritten")),
        ("regenerate", ("regenerated",)),
        ("redo", ("redid", "redone")),
        ("swap", ("swapped",)),
        ("simplify", ("simplified",)),
        ("put together", ("put together",)),
        ("swap out", ("swapped out",)),
        ("tweak", ("tweaked",)),
    ],
)
def test_every_form_of_a_verb_is_read(verb, forms):
    assert verb_forms(verb) == forms


def test_each_verb_is_caught_in_every_form():
    for verb in (*MAKING_VERBS, *CHANGING_VERBS):
        for form in verb_forms(verb):
            reply = f"I've {form} a new workout for you."
            assert problem(reply) == REPLY_CLAIMS_CREATION, reply
            assert problem(reply, proposed=True) is None, reply
            # the user's own workout is changed only by their approval, so
            # saying so is false even with a proposal (REPLY_CLAIMS_CHANGE)
            assert problem(f"I've {form} your workout.") is not None


# --- what the user did, from their workout session ---


@pytest.mark.parametrize(
    "reply",
    [
        "Bird Dog: completed.",
        "You completed the Bird Dog too.",
        "You did Bird Dog and Push-Up.",
        "bird dog — done!",
    ],
)
def test_a_reply_may_not_say_an_exercise_with_no_completed_set_was_done(reply):
    assert problem(reply, not_done=["Bird Dog"]) == REPLY_CLAIMS_UNDONE
    # an exercise the session shows done may be
    assert problem(reply, not_done=["Plank"]) is None


@pytest.mark.parametrize(
    "reply",
    [
        "Bird Dog: not completed (no sets logged).",
        "You didn't log any sets of Bird Dog.",
        "Bird Dog was planned, but no sets were completed.",
        "Push-Up: 3 sets completed. Bird Dog: skipped.",
    ],
)
def test_saying_it_was_not_done_is_fine(reply):
    assert problem(reply, not_done=["Bird Dog"]) is None


def test_the_session_read_in_the_turn_says_what_was_done():
    from app.agent import CoachContext, coach_graph, initial_state
    from tests.coach import FakeTools, call, fake_provider, respond_turn, tool_turn
    from tests.unit.test_coach_injection import results_sent

    session = {
        "output": {
            "session_id": 4,
            "status": "COMPLETED",
            "exercises": [
                {"exercise_id": 1, "exercise_name": "Push-Up", "sets": [{"completed": True}],
                 "completed_sets": 1},
                {"exercise_id": 2, "exercise_name": "Bird Dog", "sets": [], "completed_sets": 0},
            ],
        }
    }  # fmt: skip
    provider = fake_provider(
        tool_turn(call("get_latest_workout_session")),
        respond_turn(
            "Push-Up: completed. Bird Dog: completed.", "WORKOUT_HISTORY", "RETRIEVE_THEN_ANSWER"
        ),
        respond_turn(
            "You did your push-ups; Bird Dog has no sets logged.",
            "WORKOUT_HISTORY",
            "RETRIEVE_THEN_ANSWER",
        ),
    )

    state = coach_graph.invoke(
        initial_state("What did I do in my last workout?"),
        context=CoachContext(user_id=7, provider=provider, tools=FakeTools(lambda item: session)),
    )

    (rejected,) = results_sent(provider, 2)[-1:]
    assert rejected["error"]["message"] == REPLY_CLAIMS_UNDONE
    assert state["final_response"] == "You did your push-ups; Bird Dog has no sets logged."
