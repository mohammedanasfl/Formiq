"""One rule for "a proposal awaiting the user's approval" (Phase 2.3).

The Phase 2.2 live pass found two definitions: `GET /coach/proposals/pending` listed only
what `approve()` would accept, while the coach read whatever was PENDING and unexpired, so
it could show a proposal for a plan that had changed (approving it was then a 409), and a
request about plan A was answered with the proposal for plan B. Now there is one rule
(`PlanProposalService.approvable`) and both use it:

- the user's proposals the approval would not refuse for the proposal itself: pending,
  unexpired, as stored (its binding still matches), its text safe, its exercises active,
  and, for a revision, a plan still PLANNED and as proposed;
- a request that names a plan (`workout_plan_id`) is about that plan: the coach reads and
  shows again only a proposal that revises it, never another plan's or a new workout, and
  is told of no other. A newer version of the plan's workout is one that revises it.

The final guard is the approval's own 409, which none of this touches. The model is
scripted: no test calls Gemini. They require the local PostgreSQL container to be running.
"""

from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api.dependencies import PROPOSAL_TTL
from app.models import Exercise, WorkoutPlan, WorkoutPlanProposal
from tests.integration.test_coach_daily import TODAY, received
from tests.integration.test_coach_follow_ups import instructions_of, none_waiting, reading_it
from tests.integration.test_coach_target import ask, revising, stored_proposals
from tests.integration.test_plan_proposals import approve
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
from tests.integration.test_proposal_lifecycle import listed, propose, reject

NOTE = "get_pending_proposal before saying"


def plan_on(test_engine, user_id, ids, offset, name):
    with Session(test_engine) as session:
        plan = core_plan(session, user_id, ids)
        plan.name = name
        plan.scheduled_date = TODAY + timedelta(days=offset)
        session.commit()
        return plan.id


@pytest.fixture
def later_id(me, ids, test_engine, plan_id):
    """Another PLANNED plan of the user's, three days after today's (plan_id)."""
    return plan_on(test_engine, me, ids, 3, "Saturday Core")


def revise(client, use_provider, user_id, ids, plan, sets):
    """A revision of the plan, proposed in a request that names it: what is shown."""
    response, _ = ask(
        client, use_provider, user_id, *revising(ids, plan, sets=sets), workout_plan_id=plan
    )
    assert response.status_code == 200, response.json()
    return response.json()["proposal"]


def read(client, use_provider, user_id, found, **body):
    """What the coach finds when it reads the proposal awaiting approval, and the
    instructions it was given: (the tool's answer, the response body, the instructions)."""
    # what is true when the request is about one plan and the read finds nothing for it: none for this
    # workout (another plan's proposal may wait, and "no workout of yours is waiting" would be false)
    turns = reading_it() if found else none_waiting("No proposal is waiting for approval for this workout.")
    response, provider = ask(client, use_provider, user_id, *turns, message="Show it again", **body)
    assert response.status_code == 200, response.json()
    return received(provider, 1)["get_pending_proposal"], response.json(), instructions_of(provider)


def nothing_found(answer, body, instructions):
    assert answer["error"]["code"] == "RESOURCE_NOT_FOUND", answer
    assert NOTE not in instructions
    assert "proposal" not in body


# --- the coach reads what GET /coach/proposals/pending lists ---


def reject_it(client, me, test_engine, shown, plan_id, clock):
    assert reject(client, me, shown).status_code == 204


def expire_it(client, me, test_engine, shown, plan_id, clock):
    clock.now += PROPOSAL_TTL


def rename_the_plan(client, me, test_engine, shown, plan_id, clock):
    patched = client.patch(f"/users/{me}/workout-plans/{plan_id}", json={"name": "Renamed"})
    assert patched.status_code == 200


def cancel_the_plan(client, me, test_engine, shown, plan_id, clock):
    patched = client.patch(f"/users/{me}/workout-plans/{plan_id}", json={"status": "CANCELLED"})
    assert patched.status_code == 200


def change_the_stored_proposal(client, me, test_engine, shown, plan_id, clock):
    with Session(test_engine) as session:
        stored = session.get(WorkoutPlanProposal, shown["proposal_id"])
        session.execute(
            update(WorkoutPlanProposal)
            .where(WorkoutPlanProposal.proposal_id == shown["proposal_id"])
            .values(parameters={**stored.parameters, "name": "Not what was shown"})
        )
        session.commit()


def retire_an_exercise(client, me, test_engine, shown, plan_id, clock):
    """Returns what puts the exercise back: the catalog is shared by every test."""
    retired = shown["exercises"][0]["exercise_id"]
    with Session(test_engine) as session:
        session.execute(update(Exercise).where(Exercise.id == retired).values(is_active=False))
        session.commit()

    def restore():
        with Session(test_engine) as session:
            session.execute(update(Exercise).where(Exercise.id == retired).values(is_active=True))
            session.commit()

    return restore


@pytest.mark.parametrize(
    "make_stale",
    [
        reject_it,
        expire_it,
        rename_the_plan,
        cancel_the_plan,
        change_the_stored_proposal,
        retire_an_exercise,
    ],
    ids=[
        "rejected",
        "expired",
        "plan renamed",
        "plan cancelled",
        "stored proposal changed",
        "exercise retired",
    ],
)
def test_the_coach_is_not_shown_what_the_user_could_not_approve(
    client, use_provider, me, plan_id, ids, test_engine, clock, make_stale
):
    shown = revise(client, use_provider, me, ids, plan_id, sets=4)
    assert [item["proposal_id"] for item in listed(client, me)] == [shown["proposal_id"]]

    undo = make_stale(client, me, test_engine, shown, plan_id, clock)
    try:
        # the list and the coach agree: nothing waits
        assert listed(client, me) == []
        nothing_found(*read(client, use_provider, me, found=False))
        # and the approval is refused, as it always was
        assert approve(client, me, shown).status_code == 409
    finally:
        if undo:
            undo()


def test_a_proposal_that_was_approved_awaits_nothing(client, use_provider, me, plan_id, ids):
    shown = revise(client, use_provider, me, ids, plan_id, sets=4)

    assert approve(client, me, shown).status_code == 201

    assert listed(client, me) == []
    nothing_found(*read(client, use_provider, me, found=False))


def test_a_stale_newest_proposal_does_not_hide_an_older_one_that_can_be_approved(
    client, use_provider, me, plan_id, later_id, ids, test_engine, clock
):
    older = revise(client, use_provider, me, ids, later_id, sets=4)
    clock.now += timedelta(minutes=5)
    revise(client, use_provider, me, ids, plan_id, sets=4)
    # the newest one's plan changes under it
    renamed = client.patch(f"/users/{me}/workout-plans/{plan_id}", json={"name": "Renamed"})
    assert renamed.status_code == 200

    answer, body, instructions = read(client, use_provider, me, found=True)

    # the one the user could approve is the one read, with nothing older behind it
    assert [item["proposal_id"] for item in listed(client, me)] == [older["proposal_id"]]
    assert answer["output"]["revision"]["replaces_plan_id"] == later_id
    assert answer["output"]["earlier_proposals_awaiting_approval"] == 0
    assert body["proposal"]["proposal_id"] == older["proposal_id"]
    assert NOTE in instructions
    assert f"replace their saved plan {later_id}" in instructions


def test_what_the_coach_is_told_of_the_proposal_waiting_is_the_one_it_can_read(
    client, use_provider, me, plan_id, ids
):
    revise(client, use_provider, me, ids, plan_id, sets=4)
    cancelled = client.patch(f"/users/{me}/workout-plans/{plan_id}", json={"status": "CANCELLED"})
    assert cancelled.status_code == 200

    _, provider = ask(client, use_provider, me, *none_waiting(), message="What did you propose?")

    assert "get_pending_proposal before saying" not in instructions_of(provider)


# --- a request that names a plan is about that plan ---


def test_a_request_about_plan_a_is_not_answered_with_the_proposal_for_plan_b(
    client, use_provider, me, plan_id, later_id, ids
):
    revise(client, use_provider, me, ids, later_id, sets=4)

    # without a plan named, the coach reads it, as it always did
    answer, body, _ = read(client, use_provider, me, found=True)
    assert answer["output"]["revision"]["replaces_plan_id"] == later_id
    assert body["proposal"]["revision"]["replaces_plan_id"] == later_id

    # about today's plan, it is another plan's proposal: not read, not told of, not shown again
    nothing_found(*read(client, use_provider, me, found=False, workout_plan_id=plan_id))


def test_the_message_tells_a_request_about_a_plan_why_nothing_is_found(
    client, use_provider, me, plan_id, later_id, ids
):
    revise(client, use_provider, me, ids, later_id, sets=4)

    answer, *_ = read(client, use_provider, me, found=False, workout_plan_id=plan_id)

    # Phase 2.5: it also says that another workout's proposal waits (never what it holds), so
    # the reply cannot turn "none for this workout" into "none at all"
    assert answer["error"]["message"] == (
        f"the user has no workout proposal awaiting approval for workout plan {plan_id}: none "
        "was made for it, or it was approved, rejected or expired, or can no longer be "
        "approved; there is no id to ask for; the user does have 1 other workout proposal "
        "awaiting approval, for other workouts, which this request does not read: say only "
        "that none was made for this workout, never that they have none"
    )


def test_a_newer_version_of_the_named_plans_workout_is_the_one_read(
    client, use_provider, me, plan_id, later_id, ids, clock
):
    mine = revise(client, use_provider, me, ids, plan_id, sets=4)
    clock.now += timedelta(minutes=5)
    # the newest proposal of all is for the other plan
    revise(client, use_provider, me, ids, later_id, sets=4)

    answer, body, instructions = read(client, use_provider, me, found=True, workout_plan_id=plan_id)

    assert answer["output"]["revision"]["replaces_plan_id"] == plan_id
    assert answer["output"]["earlier_proposals_awaiting_approval"] == 0
    # it is shown again as it is kept, with its own binding
    assert (body["proposal"]["proposal_id"], body["proposal"]["binding"]) == (
        mine["proposal_id"],
        mine["binding"],
    )
    assert f"replace their saved plan {plan_id}" in instructions


def test_a_refinement_is_the_newest_version_for_its_plan(
    client, use_provider, me, plan_id, later_id, ids, clock, test_engine
):
    older = revise(client, use_provider, me, ids, plan_id, sets=4)
    clock.now += timedelta(minutes=5)
    newer = revise(client, use_provider, me, ids, plan_id, sets=5)
    clock.now += timedelta(minutes=5)
    revise(client, use_provider, me, ids, later_id, sets=4)

    answer, body, _ = read(client, use_provider, me, found=True, workout_plan_id=plan_id)

    assert body["proposal"]["proposal_id"] == newer["proposal_id"]
    # Phase 2.7: the older version of this plan's workout was superseded when the newer one was
    # kept, so it is not behind it any more; the other plan's is not counted either
    assert answer["output"]["earlier_proposals_awaiting_approval"] == 0
    with Session(test_engine) as session:
        assert session.get(WorkoutPlanProposal, older["proposal_id"]).status == "SUPERSEDED"


def test_a_new_workout_waiting_is_not_about_the_named_plan(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    propose(client, use_provider, me, ids)
    named = plan_on(test_engine, me, ids, 1, "Core")

    nothing_found(*read(client, use_provider, me, found=False, workout_plan_id=named))
    # and it is still there for a conversation about no plan, and in the list
    assert len(listed(client, me)) == 1
    answer, *_ = read(client, use_provider, me, found=True)
    assert answer["output"]["revision"] is None


def test_naming_a_plan_never_hides_a_proposal_from_the_list_or_the_approval(
    client, use_provider, me, plan_id, later_id, ids, test_engine
):
    other = revise(client, use_provider, me, ids, later_id, sets=4)

    nothing_found(*read(client, use_provider, me, found=False, workout_plan_id=plan_id))

    # the user's own approval of it is untouched by what the coach reads
    assert [item["proposal_id"] for item in listed(client, me)] == [other["proposal_id"]]
    assert approve(client, me, other).status_code == 201


def test_the_named_plans_proposal_is_not_one_of_anothers(
    client, use_provider, users, ids, test_engine
):
    me, them = users
    mine = plan_on(test_engine, me, ids, 0, "Mine")
    theirs = plan_on(test_engine, them, ids, 0, "Theirs")
    revise(client, use_provider, them, ids, theirs, sets=4)

    # their proposal is never read for me, whichever plan I name
    nothing_found(*read(client, use_provider, me, found=False, workout_plan_id=mine))
    nothing_found(*read(client, use_provider, me, found=False))
    assert len(stored_proposals(test_engine, them)) == 1
    assert stored_proposals(test_engine, me) == []


def test_the_approval_of_a_proposal_for_another_plan_is_still_the_users_own_to_make(
    client, use_provider, me, plan_id, later_id, ids, test_engine
):
    first = revise(client, use_provider, me, ids, later_id, sets=4)

    # the coach, asked about today's plan, saved and changed nothing
    nothing_found(*read(client, use_provider, me, found=False, workout_plan_id=plan_id))
    with Session(test_engine) as session:
        assert session.get(WorkoutPlan, later_id).status == "PLANNED"
    assert approve(client, me, first).status_code == 201
    with Session(test_engine) as session:
        assert session.get(WorkoutPlan, later_id).status == "CANCELLED"
