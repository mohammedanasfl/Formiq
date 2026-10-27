"""The proposal the user is shown is the one the reply is about (live Gemini
pass of 2026-10-16, scenario B, turn B5).

With a proposal awaiting approval, a turn that makes no proposal shows the user
that same proposal again with the reply (CoachService: `pending_shown`). A reply
that says the workout was updated in such a turn would be read beside an
unchanged card, and the user could approve it believing it had changed. These
tests run the API with a scripted model against PostgreSQL (the test database,
never the dev one) and check, from the kept proposal's own rows and the response:

- the false claim never reaches the response, and the card is the proposal as it
  was kept: the same id, binding and workout, with nothing new kept for it;
- approving that card still works once, and only once;
- a proposal the turn made is the card shown, and is the one kept.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorkoutPlan, WorkoutPlanProposal
from tests.coach import call, respond_turn, tool_turn
from tests.integration.test_coach_follow_ups import ask
from tests.integration.test_plan_proposals import approve, proposing
from tests.integration.test_plan_revisions import (  # noqa: F401 (fixtures)
    CORE_PLAN,
    REWRITE,
    clock,
    core_plan,
    ids,
    me,
    plan_id,
    rewriting,
    terms,
    today,
    tools,
    use_provider,
    use_terms,
    users,
)
from tests.unit.test_coach_unsupported_updates import (
    HONEST,
    LIVE_MESSAGE,
    LIVE_REPLY,
    LIVE_VARIANT,
)


def kept(test_engine, user_id):
    """The user's kept proposals: id, and the workout as it was kept."""
    with Session(test_engine) as session:
        return [
            (row.proposal_id, row.parameters)
            for row in session.scalars(
                select(WorkoutPlanProposal)
                .where(WorkoutPlanProposal.user_id == user_id)
                .order_by(WorkoutPlanProposal.created_at)
            )
        ]


def claiming(*claims, message=LIVE_MESSAGE):
    """A model that reads the proposal awaiting approval and makes none, then
    says each claim in turn, and last the honest answer."""
    return (
        tool_turn(call("get_pending_proposal")),
        *(respond_turn(claim, "ADAPTATION", "RETRIEVE_THEN_ANSWER") for claim in claims),
        respond_turn(HONEST, "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
    )


def test_a_false_update_claim_never_reaches_the_user_beside_the_unchanged_card(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    first, _ = ask(client, use_provider, me, *proposing(ids), message="What should I do today?")
    shown = first["proposal"]
    before = kept(test_engine, me)

    # the live turn's reply, and the same claim worded so only the turn's facts refuse it
    body, provider = ask(
        client, use_provider, me, *claiming(LIVE_REPLY, LIVE_VARIANT), message=LIVE_MESSAGE
    )

    assert provider.generate_turn.call_count == 4  # the read, two refused claims, the honest answer
    assert body["reply"] == HONEST
    assert "updated" not in body["reply"] and "lunges" not in body["reply"]
    # the card is the proposal as it was kept: same id, same binding, same workout
    card = body["proposal"]
    assert (card["proposal_id"], card["binding"]) == (shown["proposal_id"], shown["binding"])
    assert card["exercises"] == shown["exercises"]
    assert card["estimated_minutes"] == shown["estimated_minutes"]
    # and nothing was made or changed for it
    assert kept(test_engine, me) == before

    # approval still saves exactly that card, once
    first = approve(client, me, card)
    assert first.status_code == 201
    again = approve(client, me, card)
    assert (again.status_code, again.json()) == (200, first.json())
    with Session(test_engine) as session:
        assert len(session.scalars(select(WorkoutPlan).where(WorkoutPlan.user_id == me)).all()) == 1


def test_the_same_claim_is_refused_for_a_question_too_and_the_card_stays_the_proposal(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    first, _ = ask(client, use_provider, me, *proposing(ids), message="What should I do today?")
    shown = first["proposal"]

    body, _ = ask(
        client, use_provider, me, *claiming(LIVE_VARIANT), message="Why did you choose these?"
    )

    assert body["reply"] == HONEST
    assert body["proposal"]["proposal_id"] == shown["proposal_id"]
    assert len(kept(test_engine, me)) == 1


def test_an_accurate_explanation_of_the_pending_proposal_is_shown_with_its_card_at_once(
    client, use_provider, users, ids
):
    me, _ = users
    first, _ = ask(client, use_provider, me, *proposing(ids), message="What should I do today?")
    shown = first["proposal"]
    names = ", ".join(
        item["exercise_name"] for item in shown["exercises"] if item["section"] == "MAIN_WORKOUT"
    )
    reply = (
        f"The main work is {names}, about {shown['estimated_minutes']} minutes in all. You can "
        "review and approve it in Formiq."
    )

    body, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_pending_proposal")),
        respond_turn(reply, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        message="What is in the proposal?",
    )

    assert provider.generate_turn.call_count == 2  # no retry for a truthful explanation
    assert body["reply"] == reply
    assert body["proposal"]["proposal_id"] == shown["proposal_id"]


def test_a_proposal_the_turn_made_is_the_card_shown_and_the_one_kept(
    client, use_provider, me, plan_id, ids, test_engine
):
    turns = (
        *rewriting(ids, plan_id, *CORE_PLAN)[:-1],
        respond_turn(
            "Here is another version of your core workout. Approving it in Formiq replaces "
            "today's plan.",
            "DAILY_WORKOUT",
            "RETRIEVE_THEN_ANSWER",
        ),
    )

    body, _ = ask(client, use_provider, me, *turns, message=REWRITE)

    card = body["proposal"]
    (stored,) = kept(test_engine, me)
    assert card["proposal_id"] == stored[0]
    assert card["revision"]["replaces_plan_id"] == plan_id
    # the card's workout is the workout that was kept for approval
    assert [item["exercise_id"] for item in card["exercises"]] == [
        item["exercise_id"] for item in sorted(
            stored[1]["exercises"], key=lambda item: item["exercise_order"]
        )
    ]


def test_what_a_revision_records_as_changed_may_be_said_and_nothing_else(
    client, use_provider, me, plan_id, ids, test_engine
):
    first, _ = ask(
        client, use_provider, me, *rewriting(ids, plan_id, *CORE_PLAN), message=REWRITE
    )
    shown = first["proposal"]
    # Formiq recorded it: the Brisk Walk added to the warm-up and the cool-down
    backed = "I added a Brisk Walk to the warm-up and to the cool-down, as you asked."

    body, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_pending_proposal")),
        respond_turn(backed, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        message="What changed from my current plan?",
    )
    assert provider.generate_turn.call_count == 2
    assert body["reply"] == backed

    # a change it does not record is refused, whoever the question came from
    body, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_pending_proposal")),
        respond_turn(LIVE_VARIANT, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        respond_turn(HONEST, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        message="What changed from my current plan?",
    )
    assert provider.generate_turn.call_count == 3
    assert body["reply"] == HONEST
    assert body["proposal"]["proposal_id"] == shown["proposal_id"]
    assert len(kept(test_engine, me)) == 1
