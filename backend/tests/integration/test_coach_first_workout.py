"""A first workout for a user with no plan, through the API (live Gemini pass of
2026-10-16, B2).

A user with no saved plan asks for a workout. The model reads their record,
searches the catalog, proposes, and ends the turn as a WORKOUT_PLAN answer.
Formiq used to reject that decision (no plan read returned data, and the
proposal it had just accepted is kept only once the turn ends) and discard the
proposal. These tests run the API with a scripted model against PostgreSQL (the
test database, never the dev one) and check, from the kept rows and the
response, that:

- the first workout is shown, and is the one kept: same id, binding and
  exercises, PENDING;
- approving it saves one plan, and approving it again saves nothing;
- nothing is kept before the turn ends: a lookup of the proposal awaiting
  approval in the same turn finds none, and still the turn ends well.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorkoutPlan, WorkoutPlanProposal
from tests.coach import call, respond_turn, tool_turn
from tests.integration.test_coach_daily import received
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

MESSAGE = "Build me an upper-body workout for 40 minutes."
REPLY = "Here is a bodyweight workout to review and approve in Formiq."


def planning(ids, *between):
    """The model of the live turn: what a first workout takes (the reads and
    searches, the proposal), then these turns, then a WORKOUT_PLAN answer."""
    return (
        *proposing(ids)[:-1],
        *between,
        respond_turn(REPLY, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
    )


def test_a_new_users_first_workout_is_shown_and_is_the_one_kept(
    client, use_provider, users, ids, test_engine
):
    me, _ = users

    body, provider = ask(client, use_provider, me, *planning(ids), message=MESSAGE)

    # four requests, none wasted on a rejected decision
    assert provider.generate_turn.call_count == 4
    assert body["reply"] == REPLY
    card = body["proposal"]
    (stored,) = kept(test_engine, me)
    assert stored[0] == card["proposal_id"]
    with Session(test_engine) as session:
        row = session.scalars(select(WorkoutPlanProposal)).one()
        assert (row.status, row.binding, row.user_id) == ("PENDING", card["binding"], me)
    # the card is the workout that was kept
    assert [
        (item["exercise_id"], item["section"], item["sets"], item["reps"])
        for item in card["exercises"]
    ] == [
        (item["exercise_id"], item["section"], item["sets"], item.get("reps"))
        for item in sorted(stored[1]["exercises"], key=lambda item: item["exercise_order"])
    ]


def test_approving_the_first_workout_saves_one_plan_once(
    client, use_provider, users, ids, test_engine
):
    me, other = users
    body, _ = ask(client, use_provider, me, *planning(ids), message=MESSAGE)
    card = body["proposal"]

    # not the user it was made for: no such proposal
    assert approve(client, other, card).status_code == 404
    first = approve(client, me, card)
    assert first.status_code == 201
    # a repeated approval saves nothing more: it returns the plan the first one saved
    again = approve(client, me, card)
    assert (again.status_code, again.json()) == (200, first.json())

    with Session(test_engine) as session:
        plans = session.scalars(select(WorkoutPlan).where(WorkoutPlan.user_id == me)).all()
        assert len(plans) == 1
        assert session.scalars(select(WorkoutPlan).where(WorkoutPlan.user_id == other)).all() == []


def test_nothing_is_kept_before_the_turn_ends_and_the_turn_ends_well_all_the_same(
    client, use_provider, users, ids, test_engine
):
    me, _ = users

    # the model looks for the proposal it just made, as it did live
    body, provider = ask(
        client,
        use_provider,
        me,
        *planning(ids, tool_turn(call("get_pending_proposal"))),
        message=MESSAGE,
    )

    lookup = received(provider, 4)["get_pending_proposal"]
    assert lookup["error"]["code"] == "RESOURCE_NOT_FOUND"
    # still decided as an answer, and kept once, when the turn ended
    assert body["reply"] == REPLY
    assert len(kept(test_engine, me)) == 1
    assert kept(test_engine, me)[0][0] == body["proposal"]["proposal_id"]
