"""A reply states the workout's length as the card shown with it does, through
the API (live Gemini pass of 2026-10-16, B3).

The card's minutes are worked out by Formiq in code, from the exercises it
kept; a reply that gives another length for the workout is rejected, and the
model corrects it in its one retry. These tests run the API with a scripted
model against PostgreSQL (the test database, never the dev one): the minutes of
the real card, the kept proposal, and what the user is finally shown.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

from tests.coach import call, respond_turn, tool_turn
from tests.integration.test_coach_follow_ups import ask
from tests.integration.test_coach_unsupported_updates import kept
from tests.integration.test_plan_proposals import proposing
from tests.integration.test_plan_revisions import (  # noqa: F401 (fixtures)
    clock,
    core_plan,
    ids,
    me,
    plan_id,
    terms,
    today,
    tools,
    use_provider,
    use_terms,
    users,
)

MESSAGE = "Build me a bodyweight workout, I have 45 minutes."


def planning(ids, reply, *then):
    """The model of a first workout: the reads, searches and proposal, then these replies."""
    return (
        *proposing(ids)[:-1],
        *(respond_turn(text, "ADAPTATION", "RETRIEVE_THEN_ANSWER") for text in (reply, *then)),
    )


def real_minutes(client, use_provider, ids, user_id):
    """How long the workout the scripted model proposes takes, as Formiq works it out."""
    body, _ = ask(
        client, use_provider, user_id, *planning(ids, "Here is a workout to review."), message=MESSAGE
    )
    return body["proposal"]["estimated_minutes"]


def test_the_cards_own_minutes_pass_and_cost_no_extra_request(
    client, use_provider, users, ids, test_engine
):
    me, other = users
    minutes = real_minutes(client, use_provider, ids, other)
    reply = f"A bodyweight workout of about {minutes} minutes. Review it and approve it in Formiq."

    body, provider = ask(client, use_provider, me, *planning(ids, reply), message=MESSAGE)

    assert provider.generate_turn.call_count == 4  # as without the check
    assert body["reply"] == reply
    assert body["proposal"]["estimated_minutes"] == minutes
    assert len(kept(test_engine, me)) == 1


def test_a_length_that_is_not_the_cards_is_corrected_before_the_user_sees_it(
    client, use_provider, users, ids, test_engine
):
    me, other = users
    minutes = real_minutes(client, use_provider, ids, other)
    # the user's 45 minutes, given as the workout's length: the live failure
    wrong = "Here is your 45-minute bodyweight workout. Review it and approve it in Formiq."
    right = f"Here is your bodyweight workout, about {minutes} minutes. Review it in Formiq."
    assert minutes != 45

    body, provider = ask(client, use_provider, me, *planning(ids, wrong, right), message=MESSAGE)

    assert provider.generate_turn.call_count == 5  # the one retry
    assert body["reply"] == right and "45" not in body["reply"]
    # the card and the kept proposal are the one workout, shown with a reply that agrees
    (stored,) = kept(test_engine, me)
    assert stored[0] == body["proposal"]["proposal_id"]
    assert body["proposal"]["estimated_minutes"] == minutes


def test_a_follow_up_about_the_length_of_the_proposal_awaiting_approval_is_held_to_its_minutes(
    client, use_provider, users, ids
):
    me, other = users
    minutes = real_minutes(client, use_provider, ids, other)
    first, _ = ask(client, use_provider, me, *planning(ids, "Here it is."), message=MESSAGE)
    assert first["proposal"]["estimated_minutes"] == minutes

    wrong = "The whole workout takes about 45 minutes. You can review and approve it in Formiq."
    right = f"The whole workout takes about {minutes} minutes. You can review and approve it in Formiq."
    body, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_pending_proposal")),
        respond_turn(wrong, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        respond_turn(right, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        message="How long will the whole workout take?",
    )

    assert provider.generate_turn.call_count == 3
    assert body["reply"] == right
    # still the one proposal, unchanged, shown again with the corrected reply
    assert body["proposal"]["proposal_id"] == first["proposal"]["proposal_id"]
    assert body["proposal"]["estimated_minutes"] == minutes
