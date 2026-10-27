"""An accepted proposal is not lost to the model's wording, through the API (live
Gemini QA of 2026-10-17: 3 of 30 accepted proposals).

Formiq accepted the proposal, the model then worded its reply as a change ("I've
updated your workout ...") in every round, the reply check refused each one, and
the turn ended at its limit with the generic reply and no card. These tests run
the API with a scripted model against PostgreSQL (the test database, never the
dev one) and check, from the response and the kept rows, that:

- the accepted proposal is shown with Formiq's own reply, worked out from its
  card, and the card is the proposal that was kept: the same id, binding and
  workout, PENDING, with nothing saved;
- approving it saves exactly that card once, and approving it again saves
  nothing; a revision replaces its plan only on approval;
- proposals Formiq refused show no card and keep nothing, and the turn stays
  within its bound.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.graph import (
    CARD_REPLY_REVISION,
    MAX_TOOL_ITERATIONS,
    PROPOSAL_NOT_MADE_REPLY,
    PROPOSAL_RETRY_ROUNDS,
    card_reply,
)
from app.models import WorkoutPlan, WorkoutPlanProposal
from tests.coach import call, respond_turn, tool_turn
from tests.integration.test_coach_daily import received
from tests.integration.test_coach_follow_ups import ask
from tests.integration.test_coach_trajectory import (  # noqa: F401 (fixtures)
    summaries,
    traced,
    trajectory_log,
)
from tests.integration.test_coach_unsupported_updates import kept
from tests.integration.test_plan_proposals import approve, bodyweight, proposal, proposing
from tests.integration.test_plan_revisions import (  # noqa: F401 (fixtures)
    CORE_PLAN,
    REWRITE,
    clock,
    core_plan,
    ids,
    me,
    plan_id,
    rewriting,
    stored_plans,
    terms,
    today,
    tools,
    use_provider,
    use_terms,
    users,
)

MESSAGE = "Build me an upper-body workout for 40 minutes."
# the live loss: a change, said of a proposal that saves nothing
CLAIM = "I've updated your workout and swapped in a new push-up variation."
MOST_REQUESTS = MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 1


def claiming(turns, intent="WORKOUT_PLAN", count=5):
    """The model of the live loss: these turns, then the same change claim in every round."""
    return (
        *turns,
        *(respond_turn(CLAIM, intent, "RETRIEVE_THEN_ANSWER") for _ in range(count)),
    )


def workout_of(card):
    return [
        (item["exercise_id"], item["section"], item["sets"], item["reps"], item["duration_seconds"])
        for item in card["exercises"]
    ]


def test_an_accepted_proposal_whose_reply_is_refused_is_shown_and_is_the_one_kept(
    client, use_provider, users, ids, test_engine
):
    me, _ = users

    body, provider = ask(
        client, use_provider, me, *claiming(proposing(ids)[:-1]), message=MESSAGE
    )

    # the claim was refused in every round and never reached the user; no request was added
    assert provider.generate_turn.call_count == MOST_REQUESTS - 1
    card = body["proposal"]
    assert card is not None
    assert body["reply"] == card_reply(card)
    assert "updated" not in body["reply"] and "swapped" not in body["reply"]
    assert f"about {card['estimated_minutes']} minutes in all" in body["reply"]
    assert body["reply"].count("main exercise") == 1
    # the card is the proposal that was kept: PENDING, with its binding and its workout
    (stored,) = kept(test_engine, me)
    assert stored[0] == card["proposal_id"]
    with Session(test_engine) as session:
        row = session.scalars(select(WorkoutPlanProposal)).one()
        assert (row.status, row.binding, row.user_id) == ("PENDING", card["binding"], me)
        assert row.expires_at > row.created_at
        # nothing was saved: only the user's approval does
        assert session.scalars(select(WorkoutPlan).where(WorkoutPlan.user_id == me)).all() == []
    assert [
        (item["exercise_id"], item["section"], item["sets"], item.get("reps"))
        for item in sorted(stored[1]["exercises"], key=lambda item: item["exercise_order"])
    ] == [(item[0], item[1], item[2], item[3]) for item in workout_of(card)]
    assert stored[1]["name"] == card["name"]


def test_the_shown_card_is_approved_once_and_saves_exactly_that_workout(
    client, use_provider, users, ids, test_engine
):
    me, other = users
    body, _ = ask(client, use_provider, me, *claiming(proposing(ids)[:-1]), message=MESSAGE)
    card = body["proposal"]

    # not the user it was made for: no such proposal
    assert approve(client, other, card).status_code == 404
    # a binding other than the one shown is no approval
    assert approve(client, me, card, binding="0" * len(card["binding"])).status_code in (400, 409, 422)
    first = approve(client, me, card)
    again = approve(client, me, card)

    assert first.status_code == 201
    # a repeated approval saves nothing more: it returns the plan the first one saved
    assert again.status_code == 200
    assert again.json() == first.json()
    saved = first.json()
    assert (saved["name"], saved["status"]) == (card["name"], "PLANNED")
    assert [
        (item["exercise_id"], item["section"], item["sets"], item["reps"], item["duration_seconds"])
        for item in saved["exercises"]
    ] == workout_of(card)
    with Session(test_engine) as session:
        plans = session.scalars(select(WorkoutPlan).where(WorkoutPlan.user_id == me)).all()
        assert [plan.id for plan in plans] == [saved["id"]]
        assert session.scalars(select(WorkoutPlan).where(WorkoutPlan.user_id == other)).all() == []
        assert session.scalars(select(WorkoutPlanProposal)).one().status == "APPROVED"


def test_a_revision_whose_reply_is_refused_is_shown_and_replaces_its_plan_only_on_approval(
    client, use_provider, me, plan_id, ids, test_engine
):
    original = client.get(f"/users/{me}/workout-plans/{plan_id}").json()

    body, provider = ask(
        client,
        use_provider,
        me,
        *claiming(rewriting(ids, plan_id, *CORE_PLAN)[:-1], intent="DAILY_WORKOUT"),
        message=REWRITE,
    )

    card = body["proposal"]
    assert provider.generate_turn.call_count <= MOST_REQUESTS
    assert body["reply"] == card_reply(card)
    # a revision says the saved workout stays unless the user approves, and never its name
    assert CARD_REPLY_REVISION.strip() in body["reply"]
    assert card["revision"]["replaces_plan_id"] == plan_id
    assert "Core & Abs Focus" not in body["reply"]
    # shown, not saved: the plan it would replace is as it was
    (stored,) = kept(test_engine, me)
    assert (stored[0], stored[1]["replaces_plan_id"]) == (card["proposal_id"], plan_id)
    assert stored_plans(test_engine, me) == [(plan_id, "PLANNED")]
    assert client.get(f"/users/{me}/workout-plans/{plan_id}").json() == original

    response = approve(client, me, card)

    assert response.status_code == 201
    saved = response.json()
    assert stored_plans(test_engine, me) == [(plan_id, "CANCELLED"), (saved["id"], "PLANNED")]
    # again: the plan that approval saved, and no second plan
    again = approve(client, me, card)
    assert (again.status_code, again.json()) == (200, saved)
    assert stored_plans(test_engine, me) == [(plan_id, "CANCELLED"), (saved["id"], "PLANNED")]


def test_proposals_formiq_refused_show_no_card_and_keep_nothing(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    thin = bodyweight(ids)
    # the main workout of one exercise, then of two: neither is a complete full-body session
    refused = (
        tool_turn(
            proposal(
                **{**thin, "exercises": thin["exercises"][:1]},
                max_minutes=30,
                unavailable_equipment=["Dumbbell"],
            )
        ),
        tool_turn(
            proposal(
                **{**thin, "exercises": thin["exercises"][:2]},
                max_minutes=30,
                unavailable_equipment=["Dumbbell"],
            )
        ),
    )

    body, provider = ask(
        client, use_provider, me, *claiming((*proposing(ids)[:2], *refused), count=8), message=MESSAGE
    )

    # Formiq refused each proposal, so none was accepted, and nothing is shown or kept
    assert received(provider, 3)["propose_workout_plan"]["error"]["code"] == "INVALID_INPUT"
    assert received(provider, 4)["propose_workout_plan"]["error"]["code"] == "INVALID_INPUT"
    assert body["reply"] == PROPOSAL_NOT_MADE_REPLY
    assert body.get("proposal") is None
    assert kept(test_engine, me) == []
    with Session(test_engine) as session:
        assert session.scalars(select(WorkoutPlan).where(WorkoutPlan.user_id == me)).all() == []
    # the turn stays within its bound
    assert provider.generate_turn.call_count <= MOST_REQUESTS


def test_the_telemetry_records_the_turn_as_ended_at_its_limit_with_its_proposal_created(
    client, use_provider, users, ids, test_engine, traced, caplog
):
    caplog.set_level(logging.INFO)
    me, _ = users

    body, _ = ask(client, use_provider, me, *claiming(proposing(ids)[:-1]), message=MESSAGE)

    # the QA can count these turns: the rounds ran out, replies were refused, and the proposal
    # shown is the one kept (Formiq's own state, not the model's word)
    (summary,) = summaries(caplog)
    assert summary["termination"] == "retry_limit_reached"
    assert summary["status"] == "success"
    assert summary["budget"]["exhausted"] is True
    assert summary["validation"]["reply_rejections"] >= 1
    assert summary["proposal"]["outcome"] == "created"
    assert summary["proposal"]["proposal_ref"] == body["proposal"]["proposal_id"][:8]
