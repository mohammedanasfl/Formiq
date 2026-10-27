import threading
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorkoutPlanProposal
from app.services.exceptions import ProposalNotApprovableError
from app.services.plan_proposal_service import SUPERSEDED_PROPOSAL, PlanProposalService
from tests.coach import tool_turn
from tests.integration.test_coach_daily import TODAY, recommend
from tests.integration.test_coach_target import ask, later_id, reads  # noqa: F401 (fixture)
from tests.integration.test_pending_eligibility import revise
from tests.integration.test_plan_proposals import approve, proposal, proposing
from tests.integration.test_plan_proposals import propose as propose_with_tools
from tests.integration.test_plan_revisions import (  # noqa: F401 (fixtures)
    clock,
    core_plan,
    ids,
    me,
    plan_id,
    stored_plans,
    terms,
    today,
    tools,
    use_provider,
    use_terms,
    users,
)
from tests.integration.test_proposal_lifecycle import (
    listed,
    propose,
    propose_a_rewrite,
    reject,
    row_of,
)
from tests.integration.test_revision_dates import REPLY as MOVE_REPLY
from tests.integration.test_revision_dates import (  # noqa: F401 (fixture)
    adjust,
    moving,
    unchanged_plan_id,
)


def status_of(test_engine, shown):
    return row_of(test_engine, shown)[0]


def statuses(test_engine, user_id):
    """Every proposal of the user's, oldest first: (id, status)."""
    with Session(test_engine) as session:
        return session.execute(
            select(WorkoutPlanProposal.proposal_id, WorkoutPlanProposal.status)
            .where(WorkoutPlanProposal.user_id == user_id)
            .order_by(WorkoutPlanProposal.created_at, WorkoutPlanProposal.recorded_at)
        ).all()


# --- refining one workout ---


def test_a_refinement_supersedes_the_earlier_version_of_the_same_workout(
    client, use_provider, me, plan_id, ids, test_engine
):
    first = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=4)
    assert [item["proposal_id"] for item in listed(client, me)] == [first["proposal_id"]]

    second = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=5)

    # one version is offered: the newest, as it was shown
    assert [item["proposal_id"] for item in listed(client, me)] == [second["proposal_id"]]
    assert status_of(test_engine, first) == "SUPERSEDED"
    assert status_of(test_engine, second) == "PENDING"


def test_a_superseded_proposal_cannot_be_approved_and_the_newest_can(
    client, use_provider, me, plan_id, ids, test_engine
):
    first = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=4)
    second = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=5)

    stale = approve(client, me, first)

    assert (stale.status_code, stale.json()) == (409, {"detail": SUPERSEDED_PROPOSAL})
    # nothing was saved or changed by trying
    assert stored_plans(test_engine, me) == [(plan_id, "PLANNED")]
    assert status_of(test_engine, first) == "SUPERSEDED"
    saved = approve(client, me, second)
    assert saved.status_code == 201
    assert stored_plans(test_engine, me) == [(plan_id, "CANCELLED"), (saved.json()["id"], "PLANNED")]
    assert listed(client, me) == []
    # and the stale one still says why, with the plan cancelled
    assert approve(client, me, first).status_code == 409


def test_every_refinement_leaves_exactly_one_version_waiting(
    client, use_provider, me, plan_id, ids, test_engine
):
    shown = []
    for sets in (4, 5, 6, 7):
        shown.append(propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=sets))

        assert [item["proposal_id"] for item in listed(client, me)] == [shown[-1]["proposal_id"]]

    assert [status for _, status in statuses(test_engine, me)] == [
        "SUPERSEDED",
        "SUPERSEDED",
        "SUPERSEDED",
        "PENDING",
    ]


def test_a_date_only_refinement_supersedes_the_date_only_move_it_refines(
    client, use_provider, me, ids, test_engine, unchanged_plan_id
):
    moved = (TODAY + timedelta(days=1)).isoformat()
    first, _ = ask(
        client, use_provider, me, *moving(ids, unchanged_plan_id, 1),
        message="Move it to tomorrow.", workout_plan_id=unchanged_plan_id,
    )  # fmt: skip
    # the user says nothing of a day now: the model repeats the day of the proposal it refines
    second, _ = ask(
        client, use_provider, me,
        reads(),
        tool_turn(proposal(**adjust(unchanged_plan_id, ids, sets=4, scheduled_date=moved))),
        recommend(MOVE_REPLY),
        message="Make it a little harder.", workout_plan_id=unchanged_plan_id,
    )  # fmt: skip

    assert (first.status_code, second.status_code) == (200, 200)
    (item,) = listed(client, me)
    assert item["proposal_id"] == second.json()["proposal"]["proposal_id"]
    # the one that waits carries the move and the change
    assert item["scheduled_date"] == moved
    assert item["changes"]["scheduled_date_changed"] is True
    assert status_of(test_engine, first.json()["proposal"]) == "SUPERSEDED"


# --- what is not superseded ---


def test_only_proposals_for_the_same_plan_of_the_same_user_are_superseded(
    client, use_provider, users, ids, test_engine, clock, later_id, plan_id
):
    me, them = users
    with Session(test_engine) as session:
        theirs_plan = core_plan(session, them, ids).id
        session.commit()
    # several PLANNED plans: every request names the plan it is about
    elsewhere = revise(client, use_provider, me, ids, later_id, sets=4)
    clock.now += timedelta(minutes=1)
    new = propose(client, use_provider, me, ids)
    clock.now += timedelta(minutes=1)
    theirs = revise(client, use_provider, them, ids, theirs_plan, sets=4)
    clock.now += timedelta(minutes=1)
    older = revise(client, use_provider, me, ids, plan_id, sets=4)
    clock.now += timedelta(minutes=1)

    newer = revise(client, use_provider, me, ids, plan_id, sets=5)

    # only the older version of plan_id was replaced
    assert status_of(test_engine, older) == "SUPERSEDED"
    for untouched in (elsewhere, new, theirs, newer):
        assert status_of(test_engine, untouched) == "PENDING", untouched["name"]
    assert {item["proposal_id"] for item in listed(client, me)} == {
        elsewhere["proposal_id"],
        new["proposal_id"],
        newer["proposal_id"],
    }
    assert [item["proposal_id"] for item in listed(client, them)] == [theirs["proposal_id"]]


def test_a_rejected_proposal_stays_rejected_when_a_newer_one_is_made(
    client, use_provider, me, plan_id, ids, test_engine
):
    first = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=4)
    assert reject(client, me, first).status_code == 204

    second = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=5)

    assert status_of(test_engine, first) == "REJECTED"
    assert status_of(test_engine, second) == "PENDING"


def test_a_new_workout_does_not_supersede_a_revision_nor_another_new_workout(
    client, use_provider, users, ids, test_engine, plan_id
):
    me, _ = users
    revision = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=4)
    one = propose(client, use_provider, me, ids)
    response, _ = ask(
        client, use_provider, me, *proposing(ids, push_up_sets=2), message="Another one."
    )
    two = response.json()["proposal"]

    # a new workout is for no saved plan: nothing is its older version
    assert {status_of(test_engine, item) for item in (revision, one, two)} == {"PENDING"}
    assert len(listed(client, me)) == 3


# --- rejecting a superseded proposal ---


def test_rejecting_a_superseded_proposal_changes_nothing(
    client, use_provider, me, plan_id, ids, test_engine
):
    first = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=4)
    second = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=5)

    assert reject(client, me, first).status_code == 204
    assert reject(client, me, first).status_code == 204

    # it stays superseded, and the newest is as it was
    assert status_of(test_engine, first) == "SUPERSEDED"
    assert status_of(test_engine, second) == "PENDING"
    # but the binding is still checked: another version of it is never rejected
    assert reject(client, me, first, binding="0" * 64).status_code == 409


def test_a_superseded_proposal_is_cleared_once_it_has_expired(
    client, use_provider, me, plan_id, ids, test_engine, clock
):
    first = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=4)
    second = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=5)
    assert status_of(test_engine, first) == "SUPERSEDED"

    clock.now += timedelta(minutes=31)
    third = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=6)

    # the user's next proposal clears what expired and was never approved: both older ones
    assert row_of(test_engine, first) is None
    assert row_of(test_engine, second) is None
    assert [status for _, status in statuses(test_engine, me)] == ["PENDING"]
    assert [item["proposal_id"] for item in listed(client, me)] == [third["proposal_id"]]


# --- at the same time ---


def two_refinements(tools, me, ids, plan_id):
    """Two proposals for the same saved plan as the tool makes them, ready to be kept."""
    user = SimpleNamespace(id=me)  # the tools take the user's id
    kept = []
    for sets in (4, 5):
        propose_with_tools(tools, user, **adjust(plan_id, ids, sets=sets))
        kept.append(tools.proposals[-1][0])
    return kept


def register(test_engine, terms, proposal_):
    with Session(test_engine) as session:
        PlanProposalService(session, terms).register(proposal_)


def test_simultaneous_refinements_leave_exactly_one_pending(
    tools, me, ids, plan_id, test_engine, terms
):
    first, second = two_refinements(tools, me, ids, plan_id)
    failures = []
    start = threading.Barrier(2)

    def keep(proposal_):
        try:
            start.wait(timeout=10)
            register(test_engine, terms, proposal_)
        except Exception as error:  # a deadlock or a unique clash would show here
            failures.append(error)

    threads = [threading.Thread(target=keep, args=(item,)) for item in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert failures == []
    states = dict(statuses(test_engine, me))
    assert sorted(states.values()) == ["PENDING", "SUPERSEDED"]
    assert set(states) == {first.proposal_id, second.proposal_id}


def test_an_approval_racing_a_refinement_never_leaves_a_proposal_both_approved_and_superseded(
    tools, me, ids, plan_id, test_engine, terms
):
    older, newer = two_refinements(tools, me, ids, plan_id)
    register(test_engine, terms, older)
    outcome = {}
    start = threading.Barrier(2)

    def approving():
        start.wait(timeout=10)
        try:
            with Session(test_engine) as session:
                PlanProposalService(session, terms).approve(me, older.proposal_id, older.binding())
            outcome["approve"] = "approved"
        except ProposalNotApprovableError as error:
            outcome["approve"] = str(error)
        except Exception as error:
            outcome["approve"] = error

    def refining():
        start.wait(timeout=10)
        try:
            register(test_engine, terms, newer)
            outcome["register"] = "kept"
        except Exception as error:
            outcome["register"] = error

    threads = [threading.Thread(target=approving), threading.Thread(target=refining)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    # no deadlock, no unexpected error: the two orders have two outcomes, both consistent
    assert outcome["register"] == "kept", outcome
    states = dict(statuses(test_engine, me))
    if outcome["approve"] == "approved":
        # the approval won: it is saved and never superseded; the plan is replaced
        assert states[older.proposal_id] == "APPROVED"
        assert (plan_id, "CANCELLED") in stored_plans(test_engine, me)
    else:
        # the refinement won: the older one was superseded and approving it saved nothing
        assert outcome["approve"] == SUPERSEDED_PROPOSAL, outcome
        assert states[older.proposal_id] == "SUPERSEDED"
        assert stored_plans(test_engine, me) == [(plan_id, "PLANNED")]
    assert states[newer.proposal_id] == "PENDING"


# --- the coach's reads ---


def test_the_coach_reads_and_points_to_only_the_newest_version(
    client, use_provider, me, plan_id, ids, test_engine, terms
):
    propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=4)
    newest = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=5)

    with Session(test_engine) as session:
        waiting = PlanProposalService(session, terms).awaiting_approval(me, revising=plan_id)
        everything = PlanProposalService(session, terms).awaiting_approval(me)

    assert [item.proposal_id for item in waiting] == [newest["proposal_id"]]
    assert [item.proposal_id for item in everything] == [newest["proposal_id"]]
