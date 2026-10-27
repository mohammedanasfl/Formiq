"""The life of a workout proposal beyond its first approval, as the API keeps it.

A proposal is PENDING until it is approved, rejected, or 30 minutes old:

- GET /coach/proposals/pending lists the signed-in user's proposals that can
  still be approved, as they were shown (their binding included), the most
  recent first, and nothing else: not another user's, not an expired, approved
  or rejected one, not a revision of a plan that changed since. It reads only.
- Approving a proposal again, with its binding, returns the plan the first
  approval saved (200, where the first answer was 201) while that plan is still
  PLANNED and as the proposal made it: a client whose answer was lost learns
  what happened. It never saves a second plan, even when requests race, and
  never gets past the user, the binding or a plan that changed.
- POST /coach/proposals/{id}/reject, with the binding, makes it REJECTED: it can
  no longer be approved, listed, or seen by the coach. Rejecting again is no
  error; an approved proposal cannot be rejected.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

import threading
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.api.dependencies import PROPOSAL_TTL
from app.main import app
from app.models import WorkoutPlan, WorkoutPlanProposal
from app.services.plan_proposal_service import (
    APPROVED_NOT_REJECTABLE,
    APPROVED_PLAN_CHANGED,
    CHANGED,
    EXPIRED,
    REJECTED_PROPOSAL,
    REJECTION_CHANGED,
    REPLACED_PLAN_CHANGED,
)
from tests.auth import bearer
from tests.integration.test_coach_follow_ups import ask as ask_the_coach
from tests.integration.test_coach_follow_ups import instructions_of, none_waiting
from tests.integration.test_plan_proposals import approve, ask, plans_of, proposals_of, proposing
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

PENDING = "/coach/proposals/pending"


def pending(client, user_id):
    return client.get(PENDING, headers=bearer(user_id))


def listed(client, user_id):
    response = pending(client, user_id)
    assert response.status_code == 200, response.json()
    return response.json()["proposals"]


def reject(client, user_id, shown, binding=None):
    return client.post(
        f"/coach/proposals/{shown['proposal_id']}/reject",
        headers=bearer(user_id),
        json={"binding": binding or shown["binding"]},
    )


def propose(client, use_provider, user_id, ids):
    return ask(client, use_provider, user_id, *proposing(ids))[0]["proposal"]


def propose_a_rewrite(client, use_provider, user_id, ids, plan, sets=4):
    body, _ = ask(
        client, use_provider, user_id, *rewriting(ids, plan, *CORE_PLAN, sets=sets), message=REWRITE
    )
    return body["proposal"]


def row_of(test_engine, shown):
    with Session(test_engine) as session:
        row = session.get(WorkoutPlanProposal, shown["proposal_id"])
        return None if row is None else (row.status, row.workout_plan_id, row.approved_at)


# --- GET /coach/proposals/pending ---


def test_the_pending_proposals_are_the_signed_in_users_only(client):
    assert client.get(PENDING).status_code == 401
    assert client.get(PENDING, headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_with_nothing_waiting_the_list_is_empty(client, users):
    me, _ = users

    assert pending(client, me).json() == {"proposals": []}


def test_a_proposal_waiting_is_listed_as_it_was_shown(client, use_provider, users, ids, clock):
    me, _ = users
    shown = propose(client, use_provider, me, ids)

    (item,) = listed(client, me)

    # the same card, with the same id and binding, and when it was made
    assert datetime.fromisoformat(item.pop("created_at")) == clock.now
    assert item == shown
    assert item["revision"] is None and item["changes"] is None


def test_a_revision_is_listed_with_what_it_replaces_and_changes(
    client, use_provider, me, plan_id, ids
):
    shown = propose_a_rewrite(client, use_provider, me, ids, plan_id)

    (item,) = listed(client, me)

    del item["created_at"]
    assert item == shown
    assert item["revision"]["replaces_plan_id"] == plan_id
    assert item["revision"]["replaces_plan_estimated_minutes"] == 21
    assert item["changes"]["compared_with_plan_id"] == plan_id
    assert [change["exercise_name"] for change in item["changes"]["changed"]] == list(CORE_PLAN)


def test_the_latest_comes_first_and_every_one_is_listed(
    client, use_provider, users, ids, clock
):
    me, _ = users
    first = propose(client, use_provider, me, ids)
    clock.now += timedelta(minutes=10)
    second = ask(client, use_provider, me, *proposing(ids, push_up_sets=2))[0]["proposal"]

    items = listed(client, me)

    # none is chosen for the client: both can be approved, and the latest is the first
    assert [item["proposal_id"] for item in items] == [second["proposal_id"], first["proposal_id"]]
    assert items[0]["created_at"] > items[1]["created_at"]
    assert approve(client, me, items[1]).status_code == 201
    assert [item["proposal_id"] for item in listed(client, me)] == [second["proposal_id"]]


def test_only_the_users_own_proposals_are_listed(client, use_provider, users, ids):
    me, them = users
    mine = propose(client, use_provider, me, ids)
    theirs = propose(client, use_provider, them, ids)

    assert [item["proposal_id"] for item in listed(client, me)] == [mine["proposal_id"]]
    assert [item["proposal_id"] for item in listed(client, them)] == [theirs["proposal_id"]]
    # and nothing of mine can be approved or rejected through theirs
    assert approve(client, them, mine).status_code == 404
    assert reject(client, them, mine).status_code == 404
    assert [item["proposal_id"] for item in listed(client, me)] == [mine["proposal_id"]]


def test_a_listed_proposal_is_approved_with_its_own_id_and_binding(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    propose(client, use_provider, me, ids)
    (item,) = listed(client, me)

    response = approve(client, me, item)

    assert response.status_code == 201
    assert plans_of(test_engine, me) == [response.json()["id"]]
    assert listed(client, me) == []


def test_listing_proposes_approves_and_changes_nothing(
    client, use_provider, me, plan_id, ids, test_engine
):
    propose_a_rewrite(client, use_provider, me, ids, plan_id)

    def state():
        with Session(test_engine) as session:
            rows = session.execute(
                select(
                    WorkoutPlanProposal.proposal_id,
                    WorkoutPlanProposal.status,
                    WorkoutPlanProposal.binding,
                    WorkoutPlanProposal.workout_plan_id,
                ).order_by(WorkoutPlanProposal.proposal_id)
            ).all()
            plans = session.execute(
                select(WorkoutPlan.id, WorkoutPlan.status, WorkoutPlan.updated_at).order_by(
                    WorkoutPlan.id
                )
            ).all()
            return rows, plans

    before = state()
    first = listed(client, me)
    second = listed(client, me)

    # retried as often as the client likes: the same answer, and no row or plan touched
    assert first == second
    assert state() == before


def test_an_expired_proposal_is_not_listed_and_cannot_be_approved(
    client, use_provider, users, ids, clock
):
    me, _ = users
    shown = propose(client, use_provider, me, ids)
    clock.now += PROPOSAL_TTL - timedelta(seconds=1)
    assert len(listed(client, me)) == 1

    clock.now += timedelta(seconds=1)

    assert listed(client, me) == []
    refused = approve(client, me, shown)
    assert (refused.status_code, refused.json()) == (409, {"detail": EXPIRED})


def test_an_approved_proposal_is_not_listed(client, use_provider, users, ids):
    me, _ = users
    shown = propose(client, use_provider, me, ids)

    assert approve(client, me, shown).status_code == 201

    assert listed(client, me) == []


def test_a_rejected_proposal_is_not_listed_and_cannot_be_approved(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    shown = propose(client, use_provider, me, ids)

    assert reject(client, me, shown).status_code == 204

    assert listed(client, me) == []
    refused = approve(client, me, shown)
    assert (refused.status_code, refused.json()) == (409, {"detail": REJECTED_PROPOSAL})
    assert plans_of(test_engine, me) == []


@pytest.mark.parametrize("change", [{"name": "Renamed"}, {"status": "CANCELLED"}])
def test_a_revision_of_a_plan_changed_since_is_not_listed(
    client, use_provider, me, plan_id, ids, test_engine, change
):
    shown = propose_a_rewrite(client, use_provider, me, ids, plan_id)
    assert len(listed(client, me)) == 1

    assert client.patch(f"/users/{me}/workout-plans/{plan_id}", json=change).status_code == 200

    # what approving it would refuse, a client is never offered
    assert listed(client, me) == []
    refused = approve(client, me, shown)
    assert (refused.status_code, refused.json()) == (409, {"detail": REPLACED_PLAN_CHANGED})
    assert row_of(test_engine, shown)[0] == "PENDING"


def test_a_revision_whose_plan_another_approval_replaced_is_not_listed(
    client, use_provider, me, plan_id, ids, test_engine
):
    """Two pending revisions of one plan can no longer be made (the newer supersedes the older,
    Phase 2.7), but they can exist: a race that the approval won, or rows kept from before. The
    listing and the approval still hold on the plan, whatever the rows say."""
    first = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=4)
    second = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=3)
    assert [item["proposal_id"] for item in listed(client, me)] == [second["proposal_id"]]
    with Session(test_engine) as session:
        session.get(WorkoutPlanProposal, first["proposal_id"]).status = "PENDING"
        session.commit()
    assert len(listed(client, me)) == 2

    assert approve(client, me, first).status_code == 201

    assert listed(client, me) == []
    refused = approve(client, me, second)
    assert (refused.status_code, refused.json()) == (409, {"detail": REPLACED_PLAN_CHANGED})


# --- approving again ---


def test_approving_again_returns_the_saved_plan_and_writes_nothing(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    shown = propose(client, use_provider, me, ids)
    first = approve(client, me, shown)
    before = row_of(test_engine, shown)
    with Session(test_engine) as session:
        updated = session.get(WorkoutPlan, first.json()["id"]).updated_at

    again = approve(client, me, shown)

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()
    assert plans_of(test_engine, me) == [first.json()["id"]]
    # the proposal row and the plan are as the first approval left them
    assert row_of(test_engine, shown) == before
    with Session(test_engine) as session:
        assert session.get(WorkoutPlan, first.json()["id"]).updated_at == updated


def test_a_revision_approved_again_replaces_nothing_more(
    client, use_provider, me, plan_id, ids, test_engine
):
    shown = propose_a_rewrite(client, use_provider, me, ids, plan_id)
    first = approve(client, me, shown)

    again = approve(client, me, shown)

    assert (again.status_code, again.json()) == (200, first.json())
    assert stored_plans(test_engine, me) == [
        (plan_id, "CANCELLED"),
        (first.json()["id"], "PLANNED"),
    ]


def test_a_plan_saved_is_found_again_after_the_proposal_would_have_expired(
    client, use_provider, users, ids, clock
):
    me, _ = users
    shown = propose(client, use_provider, me, ids)
    first = approve(client, me, shown)
    clock.now += PROPOSAL_TTL * 3

    again = approve(client, me, shown)

    # approval is what expires; a plan that was saved stays saved
    assert (again.status_code, again.json()) == (200, first.json())


def test_approving_again_never_gets_past_the_user_or_the_binding(
    client, use_provider, users, ids, test_engine
):
    me, them = users
    shown = propose(client, use_provider, me, ids)
    first = approve(client, me, shown)

    stranger = approve(client, them, shown)
    other_binding = approve(client, me, shown, binding="0" * 64)
    unknown = client.post(
        f"/coach/proposals/{'0' * 32}/approve", headers=bearer(me), json={"binding": shown["binding"]}
    )

    assert stranger.status_code == 404
    assert (other_binding.status_code, other_binding.json()) == (409, {"detail": CHANGED})
    assert unknown.status_code == 404
    # and they got nothing of mine
    assert plans_of(test_engine, them) == []
    assert plans_of(test_engine, me) == [first.json()["id"]]


@pytest.mark.parametrize(
    "change",
    [
        lambda client, me, plan: client.patch(f"/users/{me}/workout-plans/{plan['id']}", json={"name": "Renamed"}),
        lambda client, me, plan: client.patch(
            f"/users/{me}/workout-plans/{plan['id']}", json={"status": "CANCELLED"}
        ),
        lambda client, me, plan: client.patch(
            f"/users/{me}/workout-plans/{plan['id']}", json={"scheduled_date": "2026-10-20"}
        ),
        # the exercises as prescribed: a weight, the sets
        lambda client, me, plan: client.patch(
            f"/users/{me}/workout-plans/{plan['id']}/exercises/{plan['exercises'][2]['id']}",
            json={"weight_kg": 20},
        ),
        lambda client, me, plan: client.patch(
            f"/users/{me}/workout-plans/{plan['id']}/exercises/{plan['exercises'][2]['id']}",
            json={"sets": 4},
        ),
        lambda client, me, plan: client.delete(
            f"/users/{me}/workout-plans/{plan['id']}/exercises/{plan['exercises'][2]['id']}"
        ),
    ],
    ids=["renamed", "cancelled", "moved", "weight added", "sets changed", "exercise removed"],
)
def test_approving_again_is_refused_once_the_saved_plan_is_no_longer_what_was_approved(
    client, use_provider, users, ids, test_engine, change
):
    me, _ = users
    shown = propose(client, use_provider, me, ids)
    first = approve(client, me, shown).json()
    assert change(client, me, first).status_code in (200, 204)
    changed = client.get(f"/users/{me}/workout-plans/{first['id']}").json()

    again = approve(client, me, shown)

    # no second plan, and no answer that says it is as it was
    assert (again.status_code, again.json()) == (409, {"detail": APPROVED_PLAN_CHANGED})
    assert plans_of(test_engine, me) == [first["id"]]
    assert client.get(f"/users/{me}/workout-plans/{first['id']}").json() == changed


def test_approving_again_is_refused_when_the_plan_it_saved_is_gone(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    shown = propose(client, use_provider, me, ids)
    assert approve(client, me, shown).status_code == 201
    with Session(test_engine) as session:
        session.get(WorkoutPlanProposal, shown["proposal_id"]).workout_plan_id = None
        session.commit()

    again = approve(client, me, shown)

    assert (again.status_code, again.json()) == (409, {"detail": APPROVED_PLAN_CHANGED})


def test_requests_that_race_to_approve_one_proposal_save_one_plan(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    shown = propose(client, use_provider, me, ids)
    start = threading.Barrier(5)
    answers = []

    def approve_at_once():
        # each its own client, as separate requests would be
        each = TestClient(app)
        start.wait()
        answers.append(approve(each, me, shown))

    threads = [threading.Thread(target=approve_at_once) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)

    assert sorted(answer.status_code for answer in answers) == [200, 200, 200, 200, 201]
    assert len({answer.json()["id"] for answer in answers}) == 1
    assert plans_of(test_engine, me) == [answers[0].json()["id"]]


def test_an_approval_that_races_a_rejection_has_one_outcome(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    for _ in range(4):
        shown = propose(client, use_provider, me, ids)
        start = threading.Barrier(2)
        answers = {}

        def do(name, call, shown=shown, start=start, answers=answers):
            each = TestClient(app)
            start.wait()
            answers[name] = call(each, me, shown)

        threads = [
            threading.Thread(target=do, args=("approve", approve)),
            threading.Thread(target=do, args=("reject", reject)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not any(thread.is_alive() for thread in threads)

        status, plan, _ = row_of(test_engine, shown)
        statuses = (answers["approve"].status_code, answers["reject"].status_code)
        if status == "APPROVED":
            # approved first: the rejection found a saved plan
            assert statuses == (201, 409) and plan is not None
        else:
            # rejected first: nothing was saved
            assert (status, plan, statuses) == ("REJECTED", None, (409, 204))
        # whichever won, the proposal is not waiting any more
        assert listed(client, me) == []
    # a rejected proposal never became a plan: the plans are exactly the approved proposals'
    with Session(test_engine) as session:
        saved = session.scalars(
            select(WorkoutPlanProposal.workout_plan_id).where(
                WorkoutPlanProposal.user_id == me, WorkoutPlanProposal.status == "APPROVED"
            )
        ).all()
    assert sorted(plans_of(test_engine, me)) == sorted(saved)


# --- POST /coach/proposals/{id}/reject ---


def test_rejecting_a_proposal_makes_it_rejected(client, use_provider, users, ids, test_engine):
    me, _ = users
    shown = propose(client, use_provider, me, ids)

    response = reject(client, me, shown)

    assert (response.status_code, response.content) == (204, b"")
    assert proposals_of(test_engine, me) == {shown["proposal_id"]: "REJECTED"}
    assert plans_of(test_engine, me) == []


def test_rejecting_again_is_no_error(client, use_provider, users, ids, test_engine):
    me, _ = users
    shown = propose(client, use_provider, me, ids)

    statuses = [reject(client, me, shown).status_code for _ in range(3)]

    assert statuses == [204, 204, 204]
    assert proposals_of(test_engine, me) == {shown["proposal_id"]: "REJECTED"}


def test_a_rejection_must_carry_the_binding_shown(client, use_provider, users, ids, test_engine):
    me, _ = users
    shown = propose(client, use_provider, me, ids)

    response = reject(client, me, shown, binding="0" * 64)

    assert (response.status_code, response.json()) == (409, {"detail": REJECTION_CHANGED})
    # nothing changed: it still waits, and can be approved
    assert proposals_of(test_engine, me) == {shown["proposal_id"]: "PENDING"}
    assert approve(client, me, shown).status_code == 201


def test_a_rejection_is_for_the_user_it_was_made_for_only(
    client, use_provider, users, ids, test_engine
):
    me, them = users
    shown = propose(client, use_provider, me, ids)

    stranger = reject(client, them, shown)
    unknown = client.post(
        f"/coach/proposals/{'1' * 32}/reject", headers=bearer(me), json={"binding": shown["binding"]}
    )

    assert stranger.status_code == unknown.status_code == 404
    assert stranger.json()["detail"].startswith("there is no workout plan proposal")
    assert proposals_of(test_engine, me) == {shown["proposal_id"]: "PENDING"}
    assert len(listed(client, me)) == 1


def test_an_approved_proposal_cannot_be_rejected(client, use_provider, users, ids, test_engine):
    me, _ = users
    shown = propose(client, use_provider, me, ids)
    saved = approve(client, me, shown).json()

    response = reject(client, me, shown)

    assert (response.status_code, response.json()) == (409, {"detail": APPROVED_NOT_REJECTABLE})
    assert proposals_of(test_engine, me) == {shown["proposal_id"]: "APPROVED"}
    # the plan is untouched, and approving again still returns it
    assert approve(client, me, shown).json() == saved
    assert plans_of(test_engine, me) == [saved["id"]]


@pytest.mark.parametrize(
    ("path", "body", "headers"),
    [
        ("/coach/proposals/not-an-id/reject", {"binding": "0" * 64}, True),
        (f"/coach/proposals/{'A' * 32}/reject", {"binding": "0" * 64}, True),
        (f"/coach/proposals/{'0' * 32}/reject", {}, True),
        (f"/coach/proposals/{'0' * 32}/reject", {"binding": "short"}, True),
        (f"/coach/proposals/{'0' * 32}/reject", {"binding": "0" * 64, "approved": True}, True),
        (f"/coach/proposals/{'0' * 32}/reject", {"binding": "0" * 64, "user_id": 1}, True),
        (f"/coach/proposals/{'0' * 32}/reject", {"binding": "0" * 64}, False),
    ],
    ids=["bad id", "capital id", "no binding", "short binding", "an approval", "a user", "no token"],
)
def test_a_malformed_or_unauthenticated_rejection_is_refused(client, users, path, body, headers):
    me, _ = users

    response = client.post(path, headers=bearer(me) if headers else {}, json=body)

    assert response.status_code == (422 if headers else 401)


def test_a_rejected_proposal_is_not_one_the_coach_sees(client, use_provider, users, ids):
    me, _ = users
    shown = propose(client, use_provider, me, ids)
    assert reject(client, me, shown).status_code == 204

    body, provider = ask_the_coach(client, use_provider, me, *none_waiting())

    # told nothing of a proposal waiting, and the read finds none
    assert "get_pending_proposal before saying" not in instructions_of(provider)
    contents = provider.generate_turn.call_args_list[1].args[0][-1]
    (part,) = contents.parts
    assert part.function_response.response["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert "proposal" not in body


def test_the_same_workout_may_be_proposed_again_once_it_was_rejected(
    client, use_provider, users, ids
):
    me, _ = users
    first = propose(client, use_provider, me, ids)
    assert reject(client, me, first).status_code == 204

    again = propose(client, use_provider, me, ids)

    assert again["proposal_id"] != first["proposal_id"]
    assert [item["proposal_id"] for item in listed(client, me)] == [again["proposal_id"]]


def test_rejecting_a_revision_leaves_the_plan_it_would_replace_alone(
    client, use_provider, me, plan_id, ids, test_engine
):
    original = client.get(f"/users/{me}/workout-plans/{plan_id}").json()
    shown = propose_a_rewrite(client, use_provider, me, ids, plan_id)

    assert reject(client, me, shown).status_code == 204

    assert stored_plans(test_engine, me) == [(plan_id, "PLANNED")]
    assert client.get(f"/users/{me}/workout-plans/{plan_id}").json() == original


def test_an_expired_proposal_may_be_rejected_and_is_cleared_with_the_next_one(
    client, use_provider, users, ids, clock, test_engine
):
    me, _ = users
    shown = propose(client, use_provider, me, ids)
    clock.now += PROPOSAL_TTL + timedelta(seconds=1)

    assert reject(client, me, shown).status_code == 204
    assert row_of(test_engine, shown)[0] == "REJECTED"

    # the user's expired proposals that were never approved are cleared when they get a new one,
    # rejected ones included
    fresh = propose(client, use_provider, me, ids)
    assert row_of(test_engine, shown) is None
    assert proposals_of(test_engine, me) == {fresh["proposal_id"]: "PENDING"}


def test_rejecting_again_is_204_only_while_the_row_is_kept_and_a_cleared_one_is_not_found(
    client, use_provider, users, ids, clock, test_engine
):
    me, _ = users
    shown = propose(client, use_provider, me, ids)
    clock.now += PROPOSAL_TTL + timedelta(seconds=1)

    # while its row is kept, even expired, rejecting is no error, and neither is rejecting again
    assert reject(client, me, shown).status_code == 204
    assert reject(client, me, shown).status_code == 204
    assert row_of(test_engine, shown)[0] == "REJECTED"

    # the user's next proposal clears it: from then on it is a proposal that is not there, which
    # is not told apart from another user's, whether it is rejected or approved
    propose(client, use_provider, me, ids)
    assert row_of(test_engine, shown) is None
    rejected = reject(client, me, shown)
    approved = approve(client, me, shown)
    assert (rejected.status_code, approved.status_code) == (404, 404)
    assert rejected.json() == {"detail": f"there is no workout plan proposal {shown['proposal_id']}"}
    assert approved.json() == rejected.json()


def test_a_rejected_proposal_that_has_not_expired_is_kept_until_it_does(
    client, use_provider, users, ids, clock, test_engine
):
    me, _ = users
    shown = propose(client, use_provider, me, ids)
    assert reject(client, me, shown).status_code == 204

    clock.now += timedelta(minutes=1)
    fresh = ask(client, use_provider, me, *proposing(ids, push_up_sets=2))[0]["proposal"]

    assert proposals_of(test_engine, me) == {
        shown["proposal_id"]: "REJECTED",
        fresh["proposal_id"]: "PENDING",
    }


def test_the_status_column_holds_rejected_without_a_migration(test_engine):
    """A proposal's status is text of up to 20 characters, with no constraint that names
    its values: REJECTED needed no schema change."""
    columns = {item["name"]: item for item in inspect(test_engine).get_columns("workout_plan_proposals")}

    assert columns["status"]["type"].length >= len("REJECTED")
    assert inspect(test_engine).get_check_constraints("workout_plan_proposals") == []
