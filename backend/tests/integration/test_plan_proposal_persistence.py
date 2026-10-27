"""The proposals waiting for the user's approval are kept in PostgreSQL
(app.services.plan_proposal_service): what that guarantees beyond the API flow
in test_plan_proposals.py.

A proposal outlives the process that made it; two approvals at once save one
plan; an approval that fails saves nothing and uses nothing up; a stored
proposal that was changed, or whose own text is unsafe, is not approved; and
registering a proposal clears only the user's own expired, unapproved ones.

They require the local PostgreSQL container to be running.
"""

import threading
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.agent.safety import SAFE
from app.api.dependencies import PROPOSAL_TTL
from app.approvals import (
    ProposalDraft,
    ProposalTerms,
    WriteAction,
    WriteProposal,
    propose,
    restore,
)
from app.models import Exercise, WorkoutPlan, WorkoutPlanProposal
from app.services import PlanProposalService
from app.services.exceptions import (
    InactiveExerciseError,
    ProposalNotApprovableError,
    ProposalNotFoundError,
    ProposalNotRejectableError,
)
from tests.integration.workout_plans import add_user

NOW = datetime(2026, 10, 13, 9, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def terms(clock):
    return ProposalTerms(clock=clock, ttl=PROPOSAL_TTL)


@pytest.fixture
def users(service_session):
    me = add_user(service_session, "persisted-me@example.com")
    them = add_user(service_session, "persisted-them@example.com")
    service_session.commit()
    return me.id, them.id


@pytest.fixture
def push_up(catalog_exercise_ids):
    return catalog_exercise_ids["Push-Up"]


def proposal_for(user_id, exercise_id, clock) -> WriteProposal:
    """A one-exercise workout plan proposed to the user, as the tool makes it."""
    record = {
        "exercise_order": 1,
        "section": "MAIN_WORKOUT",
        "exercise_id": exercise_id,
        "sets": 3,
        "reps": 10,
    }
    return propose(
        ProposalDraft(
            action=WriteAction.CREATE_WORKOUT_PLAN,
            parameters={
                "name": "Persisted Push",
                "scheduled_date": date(2026, 10, 13).isoformat(),
                "exercises": [record],
            },
        ),
        trusted_user_id=user_id,
        request=SAFE,
        resource_version=None,
        now=clock(),
        ttl=PROPOSAL_TTL,
    )


def registered(test_engine, terms, proposal):
    with Session(test_engine) as session:
        PlanProposalService(session, terms).register(proposal)
    return proposal


def stored(test_engine, proposal_id):
    with Session(test_engine) as session:
        row = session.get(WorkoutPlanProposal, proposal_id)
        return None if row is None else (row.status, row.workout_plan_id)


def plans_of(test_engine, user_id):
    with Session(test_engine) as session:
        return session.scalars(select(WorkoutPlan.id).where(WorkoutPlan.user_id == user_id)).all()


def test_a_proposal_outlives_the_process_that_made_it(
    test_engine, test_database_url, terms, users, push_up
):
    me, _ = users
    proposal = registered(test_engine, terms, proposal_for(me, push_up, terms.clock))

    # another process: its own engine and service, and nothing kept from the first
    restarted = create_engine(test_database_url)
    try:
        with Session(restarted) as session:
            approval = PlanProposalService(session, terms).approve(
                me, proposal.proposal_id, proposal.binding()
            )
            assert approval.created
            plan_id = approval.plan.id
    finally:
        restarted.dispose()

    assert stored(test_engine, proposal.proposal_id) == ("APPROVED", plan_id)
    assert plans_of(test_engine, me) == [plan_id]


def test_two_approvals_at_once_save_one_plan(test_engine, terms, users, push_up):
    me, _ = users
    proposal = registered(test_engine, terms, proposal_for(me, push_up, terms.clock))
    start = threading.Barrier(2)
    outcomes = []

    def approve():
        with Session(test_engine) as session:
            start.wait()
            try:
                approval = PlanProposalService(session, terms).approve(
                    me, proposal.proposal_id, proposal.binding()
                )
                outcomes.append(("saved" if approval.created else "recovered", approval.plan.id))
            except ProposalNotApprovableError as error:
                outcomes.append(("refused", str(error)))

    threads = [threading.Thread(target=approve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    # the one that waited for the other's row found the plan it saved, and saved nothing
    assert sorted(kind for kind, _ in outcomes) == ["recovered", "saved"]
    (plan_id,) = [value for kind, value in outcomes if kind == "saved"]
    assert ("recovered", plan_id) in outcomes
    assert plans_of(test_engine, me) == [plan_id]
    assert stored(test_engine, proposal.proposal_id) == ("APPROVED", plan_id)


def test_an_approval_that_fails_saves_nothing_and_uses_nothing_up(
    test_engine, terms, users, retirable_exercise_id
):
    me, _ = users
    proposal = registered(test_engine, terms, proposal_for(me, retirable_exercise_id, terms.clock))
    with Session(test_engine) as session:
        session.execute(
            update(Exercise).where(Exercise.id == retirable_exercise_id).values(is_active=False)
        )
        session.commit()

    with Session(test_engine) as session, pytest.raises(InactiveExerciseError):
        PlanProposalService(session, terms).approve(me, proposal.proposal_id, proposal.binding())

    # the plan and the approval are one transaction: neither happened
    assert plans_of(test_engine, me) == []
    assert stored(test_engine, proposal.proposal_id) == ("PENDING", None)


@pytest.mark.parametrize(
    "change",
    [
        lambda row: {**row.parameters, "name": "Something Else"},
        lambda row: {
            **row.parameters,
            "exercises": [{**row.parameters["exercises"][0], "sets": 10}],
        },
    ],
    ids=["name", "sets"],
)
def test_a_stored_proposal_that_was_changed_approves_nothing(
    test_engine, terms, users, push_up, change
):
    me, _ = users
    proposal = registered(test_engine, terms, proposal_for(me, push_up, terms.clock))
    with Session(test_engine) as session:
        row = session.get(WorkoutPlanProposal, proposal.proposal_id)
        row.parameters = change(row)
        session.commit()

    with (
        Session(test_engine) as session,
        pytest.raises(ProposalNotApprovableError, match="this proposal cannot be approved"),
    ):
        PlanProposalService(session, terms).approve(me, proposal.proposal_id, proposal.binding())

    assert plans_of(test_engine, me) == []
    assert stored(test_engine, proposal.proposal_id) == ("PENDING", None)


def test_the_proposals_own_text_is_checked_again_on_approval(test_engine, terms, users, push_up):
    me, _ = users
    # propose() refuses such notes; a proposal stored with them anyway, such as
    # one made before a safety rule existed, is not approved either
    safe = proposal_for(me, push_up, terms.clock)
    values = safe.values()
    values["exercises"][0]["notes"] = "push through the sharp pain"
    unsafe = restore(
        proposal_id=safe.proposal_id,
        trusted_user_id=me,
        action=safe.action,
        parameters=values,
        created_at=safe.created_at,
        expires_at=safe.expires_at,
    )
    registered(test_engine, terms, unsafe)

    with (
        Session(test_engine) as session,
        pytest.raises(ProposalNotApprovableError, match="this proposal cannot be approved"),
    ):
        PlanProposalService(session, terms).approve(me, unsafe.proposal_id, unsafe.binding())

    assert plans_of(test_engine, me) == []


def test_only_the_user_it_was_made_for_finds_it(test_engine, terms, users, push_up):
    me, them = users
    proposal = registered(test_engine, terms, proposal_for(me, push_up, terms.clock))

    with Session(test_engine) as session, pytest.raises(ProposalNotFoundError):
        PlanProposalService(session, terms).approve(them, proposal.proposal_id, proposal.binding())

    assert stored(test_engine, proposal.proposal_id) == ("PENDING", None)


def test_registering_clears_only_the_users_own_expired_unapproved_proposals(
    test_engine, terms, clock, users, push_up
):
    me, them = users
    mine_expired = registered(test_engine, terms, proposal_for(me, push_up, clock))
    mine_approved = registered(test_engine, terms, proposal_for(me, push_up, clock))
    theirs_expired = registered(test_engine, terms, proposal_for(them, push_up, clock))
    with Session(test_engine) as session:
        PlanProposalService(session, terms).approve(
            me, mine_approved.proposal_id, mine_approved.binding()
        )

    clock.now += PROPOSAL_TTL + timedelta(seconds=1)
    fresh = registered(test_engine, terms, proposal_for(me, push_up, clock))

    assert stored(test_engine, mine_expired.proposal_id) is None
    # an approved proposal stays, as the record of the plan it saved
    assert stored(test_engine, mine_approved.proposal_id)[0] == "APPROVED"
    assert stored(test_engine, theirs_expired.proposal_id) == ("PENDING", None)
    assert stored(test_engine, fresh.proposal_id) == ("PENDING", None)


# --- the proposals that can still be approved, and rejecting one ---


def focused(user_id, exercise_id, clock, **changes) -> WriteProposal:
    """proposal_for(), with what it is for recorded, as the tool records it: only such a
    proposal can be shown again (one made before Formiq recorded it cannot)."""
    plain = proposal_for(user_id, exercise_id, clock)
    return restore(
        proposal_id=plain.proposal_id,
        trusted_user_id=user_id,
        action=plain.action,
        parameters={**plain.values(), "focus": "FULL_BODY", **changes},
        created_at=plain.created_at,
        expires_at=plain.expires_at,
    )


def waiting(test_engine, terms, user_id):
    with Session(test_engine) as session:
        return PlanProposalService(session, terms).pending(user_id)


def test_a_stored_proposal_is_listed_with_what_approving_it_needs(
    test_engine, terms, users, push_up
):
    me, them = users
    proposal = registered(test_engine, terms, focused(me, push_up, terms.clock))

    (item,) = waiting(test_engine, terms, me)

    assert (item.proposal_id, item.binding) == (proposal.proposal_id, proposal.binding())
    assert (item.name, item.expires_at, item.created_at) == (
        "Persisted Push",
        proposal.expires_at,
        proposal.created_at,
    )
    assert item.coverage.focus == "FULL_BODY" and item.revision is None and item.changes is None
    assert [(each.exercise_name, each.sets, each.reps) for each in item.exercises] == [
        ("Push-Up", 3, 10)
    ]
    # only for the user it was made for
    assert waiting(test_engine, terms, them) == []
    # and what is listed is what approve() takes
    with Session(test_engine) as session:
        approval = PlanProposalService(session, terms).approve(me, item.proposal_id, item.binding)
        assert approval.created


def test_a_proposal_made_before_what_it_is_for_was_recorded_is_not_listed_but_still_approves(
    test_engine, terms, users, push_up
):
    me, _ = users
    # no focus: its coverage cannot be judged again, so it cannot be shown as it was (limitation 12)
    proposal = registered(test_engine, terms, proposal_for(me, push_up, terms.clock))

    assert waiting(test_engine, terms, me) == []
    with Session(test_engine) as session:
        assert PlanProposalService(session, terms).approve(
            me, proposal.proposal_id, proposal.binding()
        ).created


def test_a_proposal_whose_exercise_was_retired_is_not_listed_and_cannot_be_approved(
    test_engine, terms, users, retirable_exercise_id
):
    me, _ = users
    proposal = registered(test_engine, terms, focused(me, retirable_exercise_id, terms.clock))
    assert len(waiting(test_engine, terms, me)) == 1
    with Session(test_engine) as session:
        session.execute(
            update(Exercise).where(Exercise.id == retirable_exercise_id).values(is_active=False)
        )
        session.commit()

    assert waiting(test_engine, terms, me) == []
    with Session(test_engine) as session, pytest.raises(InactiveExerciseError):
        PlanProposalService(session, terms).approve(me, proposal.proposal_id, proposal.binding())
    assert stored(test_engine, proposal.proposal_id) == ("PENDING", None)


def test_a_stored_proposal_that_was_changed_or_is_unsafe_is_not_listed(
    test_engine, terms, users, push_up
):
    me, _ = users
    changed = registered(test_engine, terms, focused(me, push_up, terms.clock))
    with Session(test_engine) as session:
        row = session.get(WorkoutPlanProposal, changed.proposal_id)
        row.parameters = {**row.parameters, "name": "Something Else"}
        session.commit()
    safe = focused(me, push_up, terms.clock)
    values = safe.values()
    values["exercises"][0]["notes"] = "push through the sharp pain"
    unsafe = restore(
        proposal_id=safe.proposal_id, trusted_user_id=me, action=safe.action, parameters=values,
        created_at=safe.created_at, expires_at=safe.expires_at,
    )  # fmt: skip
    registered(test_engine, terms, unsafe)
    fine = registered(test_engine, terms, focused(me, push_up, terms.clock))

    assert [item.proposal_id for item in waiting(test_engine, terms, me)] == [fine.proposal_id]
    for refused in (changed, unsafe):
        with (
            Session(test_engine) as session,
            pytest.raises(ProposalNotApprovableError, match="this proposal cannot be approved"),
        ):
            PlanProposalService(session, terms).approve(
                me, refused.proposal_id, refused.binding()
            )


def test_an_approval_repeated_returns_the_plan_and_says_it_was_not_made_now(
    test_engine, terms, users, push_up
):
    me, _ = users
    proposal = registered(test_engine, terms, focused(me, push_up, terms.clock))

    with Session(test_engine) as session:
        first = PlanProposalService(session, terms).approve(
            me, proposal.proposal_id, proposal.binding()
        )
        first_id = first.plan.id
        assert first.created
    with Session(test_engine) as session:
        again = PlanProposalService(session, terms).approve(
            me, proposal.proposal_id, proposal.binding()
        )
        assert (again.created, again.plan.id) == (False, first_id)
    assert plans_of(test_engine, me) == [first_id]
    assert stored(test_engine, proposal.proposal_id) == ("APPROVED", first_id)


def test_rejecting_refuses_another_user_another_binding_and_an_approved_proposal(
    test_engine, terms, users, push_up
):
    me, them = users
    proposal = registered(test_engine, terms, focused(me, push_up, terms.clock))
    approved = registered(test_engine, terms, focused(me, push_up, terms.clock))
    with Session(test_engine) as session:
        PlanProposalService(session, terms).approve(me, approved.proposal_id, approved.binding())

    with Session(test_engine) as session, pytest.raises(ProposalNotFoundError):
        PlanProposalService(session, terms).reject(them, proposal.proposal_id, proposal.binding())
    with Session(test_engine) as session, pytest.raises(ProposalNotRejectableError):
        PlanProposalService(session, terms).reject(me, proposal.proposal_id, "0" * 64)
    with Session(test_engine) as session, pytest.raises(ProposalNotRejectableError):
        PlanProposalService(session, terms).reject(me, approved.proposal_id, approved.binding())

    assert stored(test_engine, proposal.proposal_id) == ("PENDING", None)
    assert stored(test_engine, approved.proposal_id)[0] == "APPROVED"


def test_a_rejected_proposal_is_never_approved(test_engine, terms, users, push_up):
    me, _ = users
    proposal = registered(test_engine, terms, focused(me, push_up, terms.clock))
    with Session(test_engine) as session:
        PlanProposalService(session, terms).reject(me, proposal.proposal_id, proposal.binding())
        # again: no error, and no change
        PlanProposalService(session, terms).reject(me, proposal.proposal_id, proposal.binding())

    with (
        Session(test_engine) as session,
        pytest.raises(ProposalNotApprovableError, match="this proposal was rejected"),
    ):
        PlanProposalService(session, terms).approve(me, proposal.proposal_id, proposal.binding())

    assert plans_of(test_engine, me) == []
    assert stored(test_engine, proposal.proposal_id) == ("REJECTED", None)
    assert waiting(test_engine, terms, me) == []
    with Session(test_engine) as session:
        assert not PlanProposalService(session, terms).awaits_approval(me)
