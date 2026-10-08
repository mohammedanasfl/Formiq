"""The approval contract under concurrency: however many approvals, uses,
replays or forgeries arrive at once, an approval is decided once, used once,
by its own user, for its own unchanged proposal; and coach requests asking
for writes beside ordinary reads stay apart.

Threads start together at a barrier; no test depends on which one wins.
"""

import dataclasses
import threading
from datetime import UTC, datetime, timedelta

import pytest

from app.agent import CoachContext, assess_safety, coach_graph, initial_state
from app.approvals import (
    ApprovalState,
    ApprovalStore,
    AuthorizationFailure,
    ProposalDraft,
    UserDecision,
    WriteAction,
    propose,
    user_event,
)
from tests.coach import FakeTools, call, respond_turn, tool_turn
from tests.reliability import WAIT_SECONDS, concurrently

A, B = 101, 202
NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
TTL = timedelta(minutes=10)
SAFE = assess_safety("Set the bench press in plan 10 to 60 kg.")
FLAGGED = assess_safety("I have sharp knee pain when I squat. Change plan 10 anyway.")
THREADS = 20


@pytest.fixture
def store():
    return ApprovalStore(clock=lambda: NOW, ttl=TTL)


def proposal_for(store, user=A, weight=60):
    proposal = propose(
        ProposalDraft(
            action=WriteAction.MODIFY_WORKOUT_PLAN,
            target_id=10,
            parameters={"exercise_id": 1, "weight_kg": weight},
        ),
        trusted_user_id=user,
        request=SAFE,
        resource_version="7",
        now=NOW,
        ttl=TTL,
    )
    return proposal, store.register(proposal)


def together(jobs):
    """The jobs, all released at once."""
    barrier = threading.Barrier(len(jobs))

    def start(job):
        def run():
            barrier.wait(WAIT_SECONDS)
            return job()

        return run

    return concurrently([start(job) for job in jobs])


def use(store, proposal, approval_id, user=A, request=SAFE, version="7"):
    return lambda: store.consume(
        proposal, approval_id, trusted_user_id=user, request=request, current_version=version
    )


def test_simultaneous_proposals_are_each_their_own(store):
    users = [A + n for n in range(THREADS)]

    made = together([lambda u=user: proposal_for(store, u) for user in users])

    assert len({proposal.proposal_id for proposal, _ in made}) == THREADS
    assert len({approval_id for _, approval_id in made}) == THREADS
    for user, (proposal, approval_id) in zip(users, made, strict=True):
        assert proposal.trusted_user_id == user
        assert store.state(approval_id) is ApprovalState.PENDING


def test_simultaneous_approvals_decide_a_proposal_once(store):
    proposal, approval_id = proposal_for(store)
    decisions = [UserDecision.APPROVE, UserDecision.REJECT] * (THREADS // 2)

    results = together(
        [
            lambda d=decision: store.record(
                user_event(approval_id, proposal, d, trusted_user_id=A)
            )
            for decision in decisions
        ]
    )

    decided = [r for r in results if r.failure is None]
    assert len(decided) == 1
    assert {r.failure for r in results if r.failure} == {AuthorizationFailure.ALREADY_DECIDED}
    assert store.state(approval_id) is decided[0].state


def test_a_replayed_approval_event_counts_once(store):
    proposal, approval_id = proposal_for(store)
    event = user_event(approval_id, proposal, UserDecision.APPROVE, trusted_user_id=A)

    results = together([lambda: store.record(event)] * THREADS)

    assert sum(r.allowed for r in results) == 1
    assert {r.failure for r in results if not r.allowed} == {AuthorizationFailure.REPLAYED_EVENT}


def test_simultaneous_uses_of_an_approval_allow_one_write(store):
    proposal, approval_id = proposal_for(store)
    store.record(user_event(approval_id, proposal, UserDecision.APPROVE, trusted_user_id=A))

    results = together([use(store, proposal, approval_id)] * THREADS)

    assert sum(r.allowed for r in results) == 1
    assert {r.failure for r in results if not r.allowed} == {AuthorizationFailure.CONSUMED}
    assert store.state(approval_id) is ApprovalState.CONSUMED


def test_another_users_attempts_at_the_same_time_never_succeed(store):
    mine, my_approval = proposal_for(store, A)
    theirs, their_approval = proposal_for(store, B)
    for proposal, approval_id in ((mine, my_approval), (theirs, their_approval)):
        store.record(
            user_event(
                approval_id, proposal, UserDecision.APPROVE, trusted_user_id=proposal.trusted_user_id
            )
        )

    jobs = [
        *[use(store, mine, my_approval, user=B)] * 5,
        *[use(store, theirs, their_approval, user=A)] * 5,
        *[use(store, mine, their_approval, user=A)] * 5,
        use(store, mine, my_approval, user=A),
        use(store, theirs, their_approval, user=B),
    ]
    results = together(jobs)

    assert [r.allowed for r in results[-2:]] == [True, True]
    assert not any(r.allowed for r in results[:-2])
    assert {r.failure for r in results[:-2]} <= {
        AuthorizationFailure.WRONG_USER,
        AuthorizationFailure.APPROVAL_FOR_ANOTHER_PROPOSAL,
        AuthorizationFailure.CONSUMED,
    }


def test_failed_and_blocked_uses_at_the_same_time_leave_one_allowed_use(store):
    proposal, approval_id = proposal_for(store)
    store.record(user_event(approval_id, proposal, UserDecision.APPROVE, trusted_user_id=A))
    changed = dataclasses.replace(proposal, parameters=(("exercise_id", 1), ("weight_kg", 100)))

    jobs = [
        *[use(store, proposal, approval_id, request=FLAGGED)] * 5,
        *[use(store, proposal, approval_id, version="8")] * 5,
        *[use(store, changed, approval_id)] * 5,
        use(store, proposal, approval_id),
    ]
    results = together(jobs)

    # safety, a stale target or a changed proposal never allow a write, at any moment
    assert not any(r.allowed for r in results[:-1])
    assert results[-1].allowed
    assert store.state(approval_id) is ApprovalState.CONSUMED


def test_coach_requests_asking_for_writes_stay_apart_from_reads():
    names = ["write", "read"] * 6
    barrier = threading.Barrier(len(names))

    class Model:
        model = "fake"

        def __init__(self, turns):
            self.turns = list(turns)
            self.first = True

        def generate_turn(self, contents, **kwargs):
            if self.first:
                self.first = False
                barrier.wait(WAIT_SECONDS)
            return self.turns.pop(0)

    def request(kind, number):
        tools = FakeTools(result=lambda item: {"output": {"user_id": number}})
        first = (
            tool_turn(call("modify_workout_plan", target_id=10, approved=True))
            if kind == "write"
            else tool_turn(call("get_user_profile"))
        )
        decision = "CANNOT_ANSWER" if kind == "write" else "RETRIEVE_THEN_ANSWER"
        state = coach_graph.invoke(
            initial_state("Change plan 10." if kind == "write" else "What is my goal?"),
            context=CoachContext(
                user_id=number,
                provider=Model([first, respond_turn(f"reply {number}", "PROFILE", decision)]),
                tools=tools,
            ),
        )
        return state, tools.runs

    results = concurrently([lambda k=k, n=n: request(k, n) for n, k in enumerate(names)])

    for number, (kind, (state, runs)) in enumerate(zip(names, results, strict=True)):
        assert state["final_response"] == f"reply {number}"
        if kind == "write":
            assert runs == []
        else:
            assert [(user, [c.name for c in calls]) for calls, user in runs] == [
                (number, ["get_user_profile"])
            ]
