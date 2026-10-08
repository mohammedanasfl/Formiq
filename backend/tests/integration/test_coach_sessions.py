"""The coach's database sessions and transactions: each request's session is
closed however the request ends, and no request holds a database connection
while the model answers.

The requests go through the application's own get_db (not an override), whose
SessionLocal makes sessions on the test database that report being closed
(tests.reliability.TrackedSessions). The model is a real GeminiProvider whose
SDK sends to a mock transport; it checks the database at every request it
receives.

They require the local PostgreSQL container to be running.
"""

import threading
from functools import partial
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.agent import CoachContext
from app.api.dependencies import get_ai_provider, get_tracer
from app.db import database
from app.evaluation import create_fixtures
from app.main import app
from app.services import UserProfileService
from tests.auth import bearer
from tests.reliability import (
    EchoModel,
    TrackedSessions,
    api_error,
    concurrent_tracer,
    model_response,
    transport_provider,
)

MISSING_USER_ID = 2_147_483_647


@pytest.fixture
def fixtures(service_session):
    created = create_fixtures(service_session)
    # the fixtures' session holds no connection while the requests run
    service_session.rollback()
    return created


@pytest.fixture
def sessions(test_engine, monkeypatch):
    """The application's get_db, making tracked sessions on the test database."""
    tracked = TrackedSessions()
    monkeypatch.setattr(
        database, "SessionLocal", sessionmaker(bind=test_engine, class_=tracked.session_class)
    )
    return tracked


class Watched(EchoModel):
    """The echo model, noting at each request whether a connection or a
    transaction is held while it answers."""

    def __init__(self, test_engine, sessions, barrier=None):
        super().__init__(barrier)
        self.held: list[tuple[int, int]] = []

        def check(sent):
            with self.lock:
                self.held.append(
                    (test_engine.pool.checkedout(), len(sessions.in_transaction()))
                )

        self.on_request = check


@pytest.fixture
def api(sessions, test_engine):
    """The API with the watched model and a recording tracer; server errors are
    answered with 500, as in production."""
    model = Watched(test_engine, sessions)
    tracer, backend = concurrent_tracer()
    provider = transport_provider(model)
    app.dependency_overrides[get_ai_provider] = lambda: provider
    app.dependency_overrides[get_tracer] = lambda: tracer
    try:
        yield TestClient(app, raise_server_exceptions=False), model, backend
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)
        app.dependency_overrides.pop(get_tracer, None)


def released(sessions, test_engine):
    assert sessions.opened, "the request opened no session"
    assert sessions.unclosed() == []
    assert sessions.in_transaction() == []
    assert test_engine.pool.checkedout() == 0


# Every way a request can end. The model answers by the message's token
# (tests.reliability.EchoModel); each case sets what else goes wrong.
CASES = {
    "success": ("goal", 200, "success"),
    # a token whose user does not exist: authentication turns it away, before the coach
    "user_not_found": ("goal", 401, None),
    "profile_not_found": ("goal", 200, "cannot_answer"),
    "tool_failure": ("goal", 200, "cannot_answer"),
    "provider_failure": ("goal", 502, "provider_error"),
    "provider_timeout": ("goal", 502, "provider_timeout"),
    "model_output_invalid": ("goal", 502, "model_output_invalid"),
    "safety_redirect": ("I have chest pain when I run. Should I keep going?", 200, "safety_redirect"),
    "context_budget_exceeded": ("goal", 200, "cannot_answer"),
}


@pytest.mark.parametrize("case", CASES)
def test_every_request_closes_its_session_and_holds_nothing(
    api, fixtures, sessions, test_engine, case, monkeypatch
):
    client, model, backend = api
    ask, http_status, status = CASES[case]
    user_id = {"user_not_found": MISSING_USER_ID, "profile_not_found": fixtures.other_user_id}.get(
        case, fixtures.user_id
    )
    failure = {
        "provider_failure": api_error(503, "UNAVAILABLE"),
        "provider_timeout": httpx.ReadTimeout("UPSTREAM_DETAIL_CANARY"),
        "model_output_invalid": httpx.Response(200, json={"candidates": []}),
    }.get(case)
    if failure is not None:
        model.failures["s"] = failure
    if case == "tool_failure":
        monkeypatch.setattr(
            UserProfileService,
            "get_profile_by_user_id",
            lambda *args: (_ for _ in ()).throw(RuntimeError("TOOL_DETAIL_CANARY")),
        )
    if case == "context_budget_exceeded":
        monkeypatch.setattr(
            "app.services.coach_service.CoachContext", partial(CoachContext, max_context_chars=100)
        )

    response = client.post("/coach/message", headers=bearer(user_id), json={"message": f"s {ask}"})

    assert response.status_code == http_status
    assert "CANARY" not in response.text
    if status is None:
        assert backend.roots() == []
    else:
        (root,) = backend.roots()
        assert root.metadata["status"] == status
    released(sessions, test_engine)
    # the model never answered while a connection or a transaction was held
    assert model.held == [(0, 0)] * len(model.requests("s"))


class ThreeRounds(Watched):
    """Reads the profile three rounds running, then answers."""

    def turn(self, sent):
        if len(sent.results) < 3:
            return model_response("get_user_profile")
        return super().turn(sent)


def test_a_request_with_several_tool_rounds_holds_nothing_while_the_model_answers(
    api, fixtures, sessions, test_engine
):
    client, _, _ = api
    model = ThreeRounds(test_engine, sessions)
    provider = transport_provider(model)
    app.dependency_overrides[get_ai_provider] = lambda: provider

    response = client.post(
        "/coach/message", headers=bearer(fixtures.user_id), json={"message": "s goal"}
    )

    assert response.status_code == 200
    assert len(model.requests("s")) == 4
    assert model.held == [(0, 0)] * 4
    released(sessions, test_engine)


def test_simultaneous_api_requests_each_close_their_session(api, fixtures, sessions, test_engine):
    client, model, backend = api
    count = 8
    at_once = []
    # when all of them are in the model at once, none may hold anything
    model.barrier = threading.Barrier(
        count,
        action=lambda: at_once.append(
            (test_engine.pool.checkedout(), len(sessions.in_transaction()))
        ),
    )
    users = [fixtures.user_id, fixtures.other_user_id]

    def send(number):
        return client.post(
            "/coach/message",
            headers=bearer(users[number % 2]), json={"message": f"r{number} goal"},
        )

    threads = []
    responses = {}
    for number in range(count):
        thread = threading.Thread(target=lambda n=number: responses.__setitem__(n, send(n)))
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join(30)

    assert [responses[n].status_code for n in range(count)] == [200, 200] * (count // 2)
    assert len(sessions.opened) == count
    released(sessions, test_engine)
    assert at_once == [(0, 0)]
    assert len(backend.roots()) == count


def test_the_read_before_the_model_is_ended_and_its_connection_returned(
    fixtures, test_engine, sessions
):
    # the user lookup's transaction is ended before the model is asked, so the
    # connection is back in the pool even though the session stays open
    from app.services import CoachService
    from tests.coach import fake_provider, respond_turn

    seen = []
    provider = fake_provider()

    def turn(*args, **kwargs):
        seen.append((test_engine.pool.checkedout(), session.in_transaction()))
        return respond_turn("Three times a week.")

    provider.generate_turn.side_effect = turn
    session = database.SessionLocal()
    try:
        CoachService(session, provider).reply(fixtures.user_id, "How often should I train?")
    finally:
        session.close()

    assert seen == [(0, False)]


def test_a_tool_database_error_leaves_the_turns_other_calls_working(fixtures, sessions):
    # One call's database error aborts its transaction; the tools end it, so
    # the next call in the same batch reads normally.
    from sqlalchemy import text

    from app.ai import ToolCall
    from app.services import CoachService, WorkoutPlanService

    session = database.SessionLocal()
    tools = CoachService(session, None)._tools()

    def broken(self, user_id, plan_id):
        self.plans.session.execute(text("SELECT 1/0"))

    try:
        with patch.object(WorkoutPlanService, "get_plan", broken):
            results = tools.run(
                [
                    ToolCall("get_workout_plan", {"plan_id": fixtures.plan_id}),
                    ToolCall("get_user_profile", {}),
                    ToolCall("get_exercise", {"exercise_id": fixtures.bench_id}),
                ],
                user_id=fixtures.user_id,
            )
        assert results[0] == {
            "error": {"code": "TOOL_ERROR", "message": "the data could not be read"}
        }
        assert results[1]["output"]["user_id"] == fixtures.user_id
        assert results[2]["output"]["exercise_id"] == fixtures.bench_id
        assert not session.in_transaction()
    finally:
        session.close()
