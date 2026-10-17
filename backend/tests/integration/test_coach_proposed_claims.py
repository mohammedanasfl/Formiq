"""A reply that says the coach proposed a new workout, beside the proposal that
was already waiting (live Gemini QA of 2026-10-17, after the B2 to B5 fixes).

With a proposal awaiting approval, a turn that makes no proposal shows the user
that same proposal again with the reply. In the live turn the coach tried to
propose twice, Formiq refused both, and the reply said "I have proposed an
updated full-body workout that adds the One-Arm Dumbbell Row": the user would
have read it beside the old card, which has no such exercise. These tests run the
API with a scripted model against PostgreSQL (the test database, never the dev
one) and check, from the kept proposals' own rows and the response:

- the claim never reaches the response, and the card is the proposal as it was
  kept, with nothing new kept and approval still saving exactly that card, once;
- a proposal Formiq did accept in the turn backs the same words: the reply is
  shown at once, and the card is that new proposal, the one kept.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorkoutPlan
from tests.coach import call, respond_turn, tool_turn
from tests.integration.test_coach_follow_ups import ask
from tests.integration.test_coach_unsupported_updates import kept
from tests.integration.test_plan_proposals import approve, proposing
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
from tests.unit.test_coach_proposed_claims import HONEST, LIVE_MESSAGE, LIVE_REPLY
from tests.unit.test_coach_proposal_budget import propose


def refused_twice(*replies):
    """The live turn: the model reads the proposal awaiting approval, tries to propose
    twice (exercises it never searched for: Formiq refuses them), and answers with each
    reply in turn."""
    return (
        tool_turn(call("get_pending_proposal")),
        tool_turn(propose(990001, 990002)),
        tool_turn(propose(990001, 990003)),
        *(respond_turn(reply, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER") for reply in replies),
    )


def test_a_proposal_claimed_after_refused_proposals_never_reaches_the_user_beside_the_old_card(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    first, _ = ask(client, use_provider, me, *proposing(ids), message="What should I do today?")
    shown = first["proposal"]
    before = kept(test_engine, me)

    body, provider = ask(
        client, use_provider, me, *refused_twice(LIVE_REPLY, HONEST), message=LIVE_MESSAGE
    )

    # the read, two refused proposals, the claim, the answer
    assert provider.generate_turn.call_count == 5
    assert body["reply"] == HONEST
    assert "Dumbbell Row" not in body["reply"] and "updated" not in body["reply"]
    # the card is the proposal as it was kept: same id, same binding, same workout
    card = body["proposal"]
    assert (card["proposal_id"], card["binding"]) == (shown["proposal_id"], shown["binding"])
    assert card["exercises"] == shown["exercises"]
    assert card["estimated_minutes"] == shown["estimated_minutes"]
    # and nothing was proposed or kept for it
    assert kept(test_engine, me) == before

    # approval still saves exactly that card, once
    assert approve(client, me, card).status_code == 201
    assert approve(client, me, card).status_code == 409
    with Session(test_engine) as session:
        assert len(session.scalars(select(WorkoutPlan).where(WorkoutPlan.user_id == me)).all()) == 1


def test_the_variant_of_the_claim_is_refused_for_a_question_too(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    first, _ = ask(client, use_provider, me, *proposing(ids), message="What should I do today?")
    shown = first["proposal"]

    body, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_pending_proposal")),
        respond_turn(
            "I have proposed a new workout that adds the One-Arm Dumbbell Row. You can review "
            "and approve it in Formiq.",
            "WORKOUT_PLAN",
            "RETRIEVE_THEN_ANSWER",
        ),
        respond_turn(HONEST, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        message="Why did you choose these?",
    )

    assert provider.generate_turn.call_count == 3  # the read, the refused claim, the answer
    assert body["reply"] == HONEST
    assert body["proposal"]["proposal_id"] == shown["proposal_id"]
    assert len(kept(test_engine, me)) == 1


def test_a_proposal_the_turn_made_backs_the_claim_and_is_the_card_shown_and_kept(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    first, _ = ask(client, use_provider, me, *proposing(ids), message="What should I do today?")

    # the same words, after a proposal Formiq accepted in this turn (another workout: 4 sets)
    body, provider = ask(
        client,
        use_provider,
        me,
        *proposing(ids, push_up_sets=4)[:-1],
        respond_turn(LIVE_REPLY, "DAILY_WORKOUT", "RETRIEVE_THEN_ANSWER"),
        message="Make me a different full-body workout.",
    )

    assert provider.generate_turn.call_count == 4  # no retry: the claim is true
    assert body["reply"] == LIVE_REPLY
    card = body["proposal"]
    assert card["proposal_id"] != first["proposal"]["proposal_id"]
    # the card is the proposal that was kept for approval: the user has the old one and this one
    stored = dict(kept(test_engine, me))
    assert set(stored) == {first["proposal"]["proposal_id"], card["proposal_id"]}
    assert [item["exercise_id"] for item in card["exercises"]] == [
        item["exercise_id"]
        for item in sorted(
            stored[card["proposal_id"]]["exercises"], key=lambda item: item["exercise_order"]
        )
    ]
