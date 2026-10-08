"""The coach's resources stay bounded: request after request, nothing grows,
nothing is left open, and each request's limits start from zero; the largest
requests the API accepts stay within the context budget and the tools' size
limits.

Requests go through the API with the application's own get_db on the test
database (tracked sessions), a real GeminiProvider whose SDK sends to a mock
transport, and a recording tracer. No measurement depends on timing or on
memory figures, which vary between machines: bounds are checked by counting.

They require the local PostgreSQL container to be running.
"""

import gc
import re
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.agent import CONTEXT_MAX_CHARS, trust
from app.ai import ModelTurn, ToolResult
from app.api import dependencies
from app.api.dependencies import get_ai_provider, get_tracer
from app.db import database
from app.evaluation import create_fixtures
from app.main import app
from app.models import Exercise
from app.schemas import (
    UserCreate,
    UserProfileCreate,
    WorkoutPlanCreate,
    WorkoutPlanExerciseCreate,
)
from app.schemas.coach import MAX_HISTORY_TEXT_LENGTH, MAX_HISTORY_TURNS
from app.services import UserProfileService, UserService, WorkoutPlanService
from app.tools.limits import MAX_EXERCISES, MAX_TEXT_LENGTH
from tests.auth import bearer
from tests.reliability import (
    EchoModel,
    TrackedSessions,
    api_error,
    concurrent_tracer,
    model_calls,
    respond_response,
    transport_provider,
)

URL = "/coach/message"


@pytest.fixture
def fixtures(service_session):
    created = create_fixtures(service_session)
    service_session.rollback()
    return created


@pytest.fixture
def sessions(test_engine, monkeypatch):
    tracked = TrackedSessions()
    monkeypatch.setattr(
        database, "SessionLocal", sessionmaker(bind=test_engine, class_=tracked.session_class)
    )
    return tracked


@pytest.fixture
def api(sessions):
    model = EchoModel()
    tracer, backend = concurrent_tracer()
    provider = transport_provider(model)
    app.dependency_overrides[get_ai_provider] = lambda: provider
    app.dependency_overrides[get_tracer] = lambda: tracer
    try:
        yield TestClient(app, raise_server_exceptions=False), model, backend
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)
        app.dependency_overrides.pop(get_tracer, None)


def alive(kind):
    gc.collect()
    return sum(isinstance(item, kind) for item in gc.get_objects())


def test_request_after_request_nothing_builds_up(api, fixtures, sessions, test_engine):
    client, model, backend = api
    model.failures["fail"] = api_error(503, "UNAVAILABLE")
    kinds = {
        "goal": (f"user={fixtures.user_id} age=30", 200),
        "pl": (f"plan={fixtures.plan_id} exercises=1", 200),
        "fail": (None, 502),
        "safe": (None, 200),
    }
    messages = {
        "goal": "goal goal",
        "pl": f"pl plan {fixtures.plan_id}",
        "fail": "fail goal",
        "safe": "safe I have chest pain when I run. Should I keep going?",
    }

    def round_of_requests():
        for kind, (reply, status) in kinds.items():
            response = client.post(
                URL, headers=bearer(fixtures.user_id), json={"message": messages[kind]}
            )
            assert response.status_code == status
            if reply is not None:
                assert response.json() == {"reply": f"{kind} {reply}"}

    round_of_requests()
    turns, results = alive(ModelTurn), alive(ToolResult)
    for _ in range(12):
        round_of_requests()

    # 52 requests: a session each, all closed, nothing held
    assert len(sessions.opened) == 52
    assert sessions.unclosed() == [] and sessions.in_transaction() == []
    assert test_engine.pool.checkedout() == 0
    # no turn's messages outlive it
    assert (alive(ModelTurn), alive(ToolResult)) == (turns, results)
    # each kind of request costs the same every time: no counter carries over
    by_kind: dict[int, list[dict]] = {}
    for number, root in enumerate(backend.roots()):
        by_kind.setdefault(number % 4, []).append({**root.metadata, "request_id": None})
    for traces in by_kind.values():
        assert all(trace == traces[0] for trace in traces)
    # the reply check's cache is bounded
    assert trust._shingles.cache_info().currsize <= trust._shingles.cache_info().maxsize


def test_one_model_provider_serves_every_request():
    dependencies.get_ai_provider.cache_clear()
    try:
        assert dependencies.get_ai_provider() is dependencies.get_ai_provider()
        assert dependencies.get_ai_provider.cache_info().currsize == 1
    finally:
        dependencies.get_ai_provider.cache_clear()


def test_the_largest_histories_stay_within_the_budget_and_apart(api, fixtures):
    client, model, backend = api
    count = 4
    model.barrier = threading.Barrier(count)
    filler = "x" * (MAX_HISTORY_TEXT_LENGTH - 40)

    def history(number):
        turns = [
            {"role": "user" if n % 2 == 0 else "coach", "text": f"turn {n} {filler}"}
            for n in range(MAX_HISTORY_TURNS - 1)
        ]
        # the canary leads the most recent turn, which the coach keeps
        return [*turns, {"role": "user", "text": f"HISTORY_{number}_CANARY {filler}"}]

    responses = {}

    def send(number):
        responses[number] = client.post(
            URL,
            headers=bearer(fixtures.user_id),
            json={"message": f"h{number} goal", "history": history(number)},
        )

    threads = [threading.Thread(target=send, args=(n,)) for n in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)

    assert [responses[n].status_code for n in range(count)] == [200] * count
    for number in range(count):
        for sent in model.requests(f"h{number}"):
            assert re.findall(r"HISTORY_\d_CANARY", sent.text) == [f"HISTORY_{number}_CANARY"]
    for root in backend.roots():
        generations = [node for node in backend.subtree(root) if node.name == "gemini"]
        assert generations
        assert all(node.metadata["context_chars"] <= CONTEXT_MAX_CHARS for node in generations)
        fits = [node for node in backend.subtree(root) if node.name == "context_fit"]
        # the conversation is cut to the turns the coach keeps
        assert all(node.metadata["conversation_omitted"] > 0 for node in fits)


def test_a_large_plan_reaches_the_model_within_the_tools_limits(api, service_session, profile_fields):
    client, model, _ = api
    user = UserService(service_session).create_user(UserCreate(email="large-plan@formiq.test"))
    UserProfileService(service_session).create_profile(user.id, UserProfileCreate(**profile_fields))
    exercise_ids = service_session.scalars(select(Exercise.id).limit(4)).all()
    plan = WorkoutPlanService(service_session).create_plan(
        user.id,
        WorkoutPlanCreate(
            name="Large",
            exercises=[
                WorkoutPlanExerciseCreate(
                    exercise_id=exercise_ids[n % len(exercise_ids)],
                    exercise_order=n + 1,
                    sets=3,
                    reps=8,
                    notes="n" * 2_000,
                )
                for n in range(MAX_EXERCISES + 10)
            ],
        ),
    )
    plan_id = plan.id
    service_session.rollback()

    response = client.post(URL, headers=bearer(user.id), json={"message": f"big plan {plan_id}"})

    assert response.status_code == 200
    (result,) = model.requests("big")[-1].results
    output = result["response"]["output"]
    assert len(output["exercises"]) == MAX_EXERCISES
    assert output["truncated"] is True
    assert all(len(item["notes"]) <= MAX_TEXT_LENGTH for item in output["exercises"])


def test_limits_start_from_zero_for_every_request(api, fixtures):
    client, _, backend = api

    class Seeker(EchoModel):
        def turn(self, sent):
            if sent.token == "seek":
                if sent.allowed == ["respond"]:
                    return respond_response("seek gave up", "PROFILE", "CANNOT_ANSWER")
                return model_calls([("get_user_profile", {})] * 20)
            return super().turn(sent)

    seeker = Seeker()
    provider = transport_provider(seeker)
    app.dependency_overrides[get_ai_provider] = lambda: provider

    for _ in range(3):
        seek = client.post(URL, headers=bearer(fixtures.user_id), json={"message": "seek"})
        assert seek.status_code == 200
        normal = client.post(URL, headers=bearer(fixtures.user_id), json={"message": "n goal"})
        assert normal.json() == {"reply": f"n user={fixtures.user_id} age=30"}

    seeking, normal = backend.roots()[0::2], backend.roots()[1::2]
    assert {(r.metadata["model_requests"], r.metadata["iterations"]) for r in seeking} == {(6, 5)}
    assert {(r.metadata["model_requests"], r.metadata["iterations"]) for r in normal} == {(2, 1)}
