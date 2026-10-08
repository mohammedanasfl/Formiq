"""Coach requests at the same time: whatever overlaps, each request sees only
its own user, message, history, tool results, model and outcome.

Requests share what production shares: the compiled graph, one real
GeminiProvider (its SDK sending to a mock transport, see tests.reliability)
and one tracer. Each has its own database session, as get_db gives. Barriers
in the model hold every request in flight until all of them are, so the
requests truly overlap; no test depends on which finishes first.

They require the local PostgreSQL container to be running. No test calls
Gemini or Langfuse.
"""

import asyncio
import re
import threading
from dataclasses import dataclass
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.agent import ConversationTurn
from app.ai import AIModelOutputError
from app.api.dependencies import get_ai_provider, get_tracer
from app.main import app
from app.models import Exercise
from app.schemas import (
    UserCreate,
    UserProfileCreate,
    WorkoutPlanCreate,
    WorkoutPlanExerciseCreate,
)
from app.services import (
    CoachService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
)
from tests.auth import bearer
from tests.coach import fake_provider, respond_turn
from tests.reliability import (
    WAIT_SECONDS,
    EchoModel,
    api_error,
    concurrent_tracer,
    concurrently,
    model_calls,
    respond_response,
    transport_provider,
)

PEOPLE = 12
REQUEST_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class Person:
    user_id: int
    age: int
    plan_id: int
    canary: str
    token: str


@pytest.fixture
def bench_id(service_session):
    return service_session.scalar(select(Exercise.id).where(Exercise.name == "Barbell Bench Press"))


@pytest.fixture
def people(service_session, profile_fields, bench_id):
    """Users with their own profile (a different age each) and a plan whose name
    is that user's canary."""
    found = []
    for number in range(PEOPLE):
        user = UserService(service_session).create_user(
            UserCreate(email=f"concurrent-{number}@formiq.test")
        )
        UserProfileService(service_session).create_profile(
            user.id, UserProfileCreate(**{**profile_fields, "age": 20 + number})
        )
        canary = f"TOOL_RESULT_{number}_CANARY"
        plan = WorkoutPlanService(service_session).create_plan(
            user.id,
            WorkoutPlanCreate(
                name=canary,
                exercises=[
                    WorkoutPlanExerciseCreate(exercise_id=bench_id, exercise_order=1, sets=3, reps=8)
                ],
            ),
        )
        found.append(Person(user.id, 20 + number, plan.id, canary, f"req{number}"))
    # the fixtures' session holds no connection while the requests run
    service_session.rollback()
    return found


def coach(test_engine, provider, tracer, user_id, message, history=()):
    """One request, as the API runs it: its own session, the shared rest."""

    def request():
        with Session(test_engine) as session:
            return CoachService(session, provider, tracer).reply(user_id, message, history)

    return request


# --- different users, same user ---


def test_simultaneous_requests_of_different_users_each_get_only_their_own_answer(
    test_engine, people
):
    model = EchoModel(threading.Barrier(PEOPLE))
    tracer, backend = concurrent_tracer()
    provider = transport_provider(model)

    replies = concurrently(
        [coach(test_engine, provider, tracer, p.user_id, f"{p.token} goal") for p in people]
    )

    for person, reply in zip(people, replies, strict=True):
        assert reply == f"{person.token} user={person.user_id} age={person.age}"
        sent = model.requests(person.token)
        assert len(sent) == 2
        # the tools read this request's user only, and the model saw only that
        assert [r["response"]["output"]["user_id"] for s in sent for r in s.results] == [
            person.user_id
        ]
    roots = backend.roots()
    assert sorted(int(root.metadata["user_id"]) for root in roots) == sorted(
        p.user_id for p in people
    )
    for root in roots:
        assert root.metadata["status"] == "success"
        assert root.metadata["model_requests"] == 2
        assert root.metadata["tool_calls_executed"] == 1
        assert root.ended


def test_simultaneous_requests_of_the_same_user_stay_apart(test_engine, people, bench_id):
    person = people[0]
    asks = {
        "a0": ("goal", f"user={person.user_id} age={person.age}"),
        "a1": (f"plan {person.plan_id}", f"plan={person.plan_id} exercises=1"),
        "a2": (f"exercise {bench_id}", f"exercise={bench_id}"),
        "a3": ("goal", f"user={person.user_id} age={person.age}"),
        "a4": (f"plan {person.plan_id}", f"plan={person.plan_id} exercises=1"),
        "a5": (f"exercise {bench_id}", f"exercise={bench_id}"),
    }
    model = EchoModel(threading.Barrier(len(asks)))
    provider = transport_provider(model)
    tracer, _ = concurrent_tracer()

    replies = concurrently(
        [
            coach(test_engine, provider, tracer, person.user_id, f"{token} {ask}")
            for token, (ask, _) in asks.items()
        ]
    )

    assert replies == [f"{token} {answer}" for token, (_, answer) in asks.items()]


def test_more_simultaneous_requests_than_database_connections_all_complete(test_engine, people):
    # 20 requests wait in the model at once while the pool has 15 connections
    # (5 + 10 overflow): it only works because no request holds a connection
    # while the model answers
    capacity = test_engine.pool.size() + test_engine.pool._max_overflow
    requests = [people[number % PEOPLE] for number in range(capacity + 5)]
    model = EchoModel(threading.Barrier(len(requests)))
    provider = transport_provider(model)
    tracer, _ = concurrent_tracer()

    replies = concurrently(
        [
            coach(test_engine, provider, tracer, person.user_id, f"bulk{number} goal")
            for number, person in enumerate(requests)
        ]
    )

    assert replies == [
        f"bulk{number} user={person.user_id} age={person.age}"
        for number, person in enumerate(requests)
    ]
    assert test_engine.pool.checkedout() == 0


# --- what each request sends the model ---


def test_a_requests_history_never_reaches_another_request(test_engine, people):
    a, b, c = people[:3]
    histories = {
        a.token: [
            ConversationTurn("user", "FORMIQ_HISTORY_USER_A_CANARY: I train on Mondays."),
            ConversationTurn("coach", "Noted."),
        ],
        b.token: [ConversationTurn("user", "FORMIQ_HISTORY_USER_B_CANARY: I train at home.")],
        c.token: [],
    }
    model = EchoModel(threading.Barrier(3))
    provider = transport_provider(model)
    tracer, _ = concurrent_tracer()

    concurrently(
        [
            coach(test_engine, provider, tracer, p.user_id, f"{p.token} goal", histories[p.token])
            for p in (a, b, c)
        ]
    )

    def canaries(person):
        return {
            found
            for sent in model.requests(person.token)
            for found in re.findall(r"FORMIQ_HISTORY_USER_\w_CANARY", sent.text)
        }

    assert canaries(a) == {"FORMIQ_HISTORY_USER_A_CANARY"}
    assert canaries(b) == {"FORMIQ_HISTORY_USER_B_CANARY"}
    # a request without history gets none, not the last one seen
    assert canaries(c) == set()
    assert all(sent.history == "" for sent in model.requests(c.token))


def test_a_requests_tool_results_never_reach_another_request(test_engine, people):
    model = EchoModel(threading.Barrier(PEOPLE))
    provider = transport_provider(model)
    tracer, _ = concurrent_tracer()

    replies = concurrently(
        [
            coach(test_engine, provider, tracer, p.user_id, f"{p.token} plan {p.plan_id}")
            for p in people
        ]
    )

    for person, reply in zip(people, replies, strict=True):
        assert reply == f"{person.token} plan={person.plan_id} exercises=1"
        first, second = model.requests(person.token)
        assert re.findall(r"TOOL_RESULT_\d+_CANARY", first.text) == []
        assert set(re.findall(r"TOOL_RESULT_\d+_CANARY", second.text)) == {person.canary}


def test_each_request_uses_its_own_model(test_engine, people):
    a, b = people[:2]
    barrier = threading.Barrier(2)

    def model(output):
        provider = fake_provider()

        def turn(contents, **kwargs):
            barrier.wait(WAIT_SECONDS)
            return respond_turn(output)

        provider.generate_turn.side_effect = turn
        return provider

    model_a, model_b = model("Output A: three sessions a week."), model("Output B: rest days help.")
    tracer, _ = concurrent_tracer()

    replies = concurrently(
        [
            coach(test_engine, model_a, tracer, a.user_id, "How often should I train? (A)"),
            coach(test_engine, model_b, tracer, b.user_id, "How often should I train? (B)"),
        ]
    )

    assert replies == ["Output A: three sessions a week.", "Output B: rest days help."]
    for provider, mine in ((model_a, "(A)"), (model_b, "(B)")):
        (sent,) = provider.generate_turn.call_args_list
        message = sent.args[0][0].parts[-1].text
        assert message.endswith(mine)


# --- failures that overlap successes ---


def test_a_failing_tool_fails_only_its_own_request(test_engine, people):
    failing = people[0]
    model = EchoModel(threading.Barrier(PEOPLE))
    provider = transport_provider(model)
    tracer, backend = concurrent_tracer()
    real_get_plan = WorkoutPlanService.get_plan

    def get_plan(self, user_id, plan_id):
        if user_id == failing.user_id:
            # a real database error, which aborts this request's transaction
            self.plans.session.execute(text("SELECT 1/0"))
        return real_get_plan(self, user_id, plan_id)

    with patch.object(WorkoutPlanService, "get_plan", get_plan):
        replies = concurrently(
            [
                coach(test_engine, provider, tracer, p.user_id, f"{p.token} plan {p.plan_id}")
                for p in people
            ]
        )

    assert replies[0] == f"{failing.token} error=tool_error"
    for person, reply in zip(people[1:], replies[1:], strict=True):
        assert reply == f"{person.token} plan={person.plan_id} exercises=1"
    statuses = sorted(root.metadata["status"] for root in backend.roots())
    assert statuses == ["cannot_answer"] + ["success"] * (PEOPLE - 1)
    # nothing of the failure stays: the same request now works
    model.barrier = None
    again = coach(test_engine, provider, tracer, failing.user_id, f"again plan {failing.plan_id}")
    assert again() == f"again plan={failing.plan_id} exercises=1"


def test_a_failing_model_fails_only_its_own_request(test_engine, people):
    model = EchoModel(threading.Barrier(PEOPLE))
    failing = {people[0].token, people[5].token}
    for token in failing:
        model.failures[token] = api_error(503, "UNAVAILABLE")
    provider = transport_provider(model)
    tracer, backend = concurrent_tracer()

    replies = concurrently(
        [coach(test_engine, provider, tracer, p.user_id, f"{p.token} goal") for p in people]
    )

    for person, reply in zip(people, replies, strict=True):
        if person.token in failing:
            assert type(reply).__name__ == "AIProviderError"
            assert "UPSTREAM_DETAIL_CANARY" not in str(reply)
            assert len(model.requests(person.token)) == 1
        else:
            assert reply == f"{person.token} user={person.user_id} age={person.age}"
    assert sorted(root.metadata["status"] for root in backend.roots()) == (
        ["provider_error"] * 2 + ["success"] * (PEOPLE - 2)
    )


# --- limits are per request ---


class LimitSeeker(EchoModel):
    """A model that asks for as many tool calls as it may, every turn, and
    decides only when Formiq allows nothing else."""

    def __init__(self, barrier, calls_per_turn):
        super().__init__(barrier)
        self.calls_per_turn = calls_per_turn

    def turn(self, sent):
        if sent.allowed == ["respond"]:
            return respond_response(f"{sent.token} gave up", "EXERCISE", "CANNOT_ANSWER")
        exercise_id = int(sent.message.split()[-1])
        calls = self.calls_per_turn.get(sent.token, 20)
        return model_calls([("get_exercise", {"exercise_id": exercise_id})] * calls)


def test_each_simultaneous_request_reaches_its_own_limits(test_engine, people, bench_id):
    # 20 requests that each want 20 calls a turn, and one that wants 21
    tokens = [f"limit{number}" for number in range(21)]
    model = LimitSeeker(threading.Barrier(len(tokens)), {"limit20": 21})
    provider = transport_provider(model)
    tracer, backend = concurrent_tracer()

    results = concurrently(
        [
            coach(
                test_engine,
                provider,
                tracer,
                people[number % PEOPLE].user_id,
                f"{token} exercise {bench_id}",
            )
            for number, token in enumerate(tokens)
        ]
    )

    assert results[:20] == [f"{token} gave up" for token in tokens[:20]]
    assert isinstance(results[20], AIModelOutputError)
    for root in backend.roots():
        counts = root.metadata
        if counts["status"] == "model_output_invalid":
            # the 21-call turn is refused before any call runs
            assert counts["model_requests"] == 1
            assert "tool_calls_executed" not in counts
            continue
        # 5 rounds of 20 requested calls, 5 run each, then the forced decision:
        # whatever the other requests did at the same time
        assert counts["status"] == "cannot_answer"
        assert counts["model_requests"] == 6
        assert counts["iterations"] == 5
        assert counts["tool_calls_requested"] == 100
        calls = [node for node in backend.subtree(root) if node.kind == "tool"]
        refused = [c for c in calls if c.metadata.get("error_code") == "TOOL_LIMIT_REACHED"]
        assert (len(calls), len(refused)) == (100, 75)
        assert counts["tool_tool_limit_reached"] == 75
    assert len(backend.roots()) == 21


# --- request ids ---


def test_every_request_gets_its_own_request_id(test_engine, people):
    model = EchoModel(threading.Barrier(PEOPLE))
    model.failures[people[1].token] = api_error(503, "UNAVAILABLE")
    provider = transport_provider(model)
    tracer, backend = concurrent_tracer()
    messages = {
        # a safety request and a failed one get an id like every other
        people[0].token: f"{people[0].token} I have chest pain when I run. Should I keep going?",
    }

    concurrently(
        [
            coach(
                test_engine,
                provider,
                tracer,
                p.user_id,
                messages.get(p.token, f"{p.token} goal"),
            )
            for p in people
        ]
    )

    roots = backend.roots()
    ids = [root.metadata["request_id"] for root in roots]
    assert len(ids) == PEOPLE == len(set(ids))
    assert all(REQUEST_ID.fullmatch(request_id) for request_id in ids)
    statuses = [root.metadata["status"] for root in roots]
    assert statuses.count("safety_redirect") == 1
    assert statuses.count("provider_error") == 1
    # nothing of the request is in its id: it is random
    for root in roots:
        user = root.metadata["user_id"]
        assert user not in root.metadata["request_id"]
        assert "formiq" not in root.metadata["request_id"]


# --- the API ---


def test_simultaneous_api_requests_get_their_own_responses(client, people, bench_id):
    model = EchoModel(threading.Barrier(PEOPLE))
    failing = {"api10", "api11"}
    for token in failing:
        model.failures[token] = api_error(503, "UNAVAILABLE")
    tracer, backend = concurrent_tracer()
    # one provider and one tracer for every request, as in production
    provider = transport_provider(model)
    app.dependency_overrides[get_ai_provider] = lambda: provider
    app.dependency_overrides[get_tracer] = lambda: tracer
    owner = people[0]
    requests = [
        # different users
        *[(f"api{n}", people[n].user_id, f"api{n} goal") for n in range(8)],
        # the same user again, at the same time
        ("api8", owner.user_id, f"api8 plan {owner.plan_id}"),
        ("api9", owner.user_id, f"api9 exercise {bench_id}"),
        # and two failures among them
        ("api10", people[10].user_id, "api10 goal"),
        ("api11", owner.user_id, "api11 goal"),
    ]

    async def send_all():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://formiq.test") as api:
            return await asyncio.gather(
                *[
                    api.post("/coach/message", headers=bearer(user_id), json={"message": message})
                    for _, user_id, message in requests
                ]
            )

    try:
        responses = asyncio.run(send_all())
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)
        app.dependency_overrides.pop(get_tracer, None)

    expected = {
        **{
            f"api{n}": f"api{n} user={people[n].user_id} age={people[n].age}" for n in range(8)
        },
        "api8": f"api8 plan={owner.plan_id} exercises=1",
        "api9": f"api9 exercise={bench_id}",
    }
    for (token, user_id, _), response in zip(requests, responses, strict=True):
        # the request id is the server's own: no response carries it
        assert not any(
            REQUEST_ID.search(value) for value in response.headers.values()
        ), response.headers
        if token in failing:
            assert response.status_code == 502
            assert "UPSTREAM_DETAIL_CANARY" not in response.text
            continue
        assert response.status_code == 200
        assert response.json() == {"reply": expected[token]}
        # the tools ran for the request's own user
        results = [r for sent in model.requests(token) for r in sent.results]
        if results and "user_id" in results[0]["response"]["output"]:
            assert results[0]["response"]["output"]["user_id"] == user_id
    roots = backend.roots()
    assert len({root.metadata["request_id"] for root in roots}) == len(requests)
    assert sorted(int(root.metadata["user_id"]) for root in roots) == sorted(
        user_id for _, user_id, _ in requests
    )
