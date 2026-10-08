"""Failures of the coach's model, tools and tracing: each ends its own request
the way the contracts say, is tried once, changes no data, shows the client
nothing of its cause, and leaves the next request as if it had not happened.

The model is a real GeminiProvider whose SDK sends to a mock transport
(tests.reliability), so "tried once" counts the HTTP requests the SDK sends,
retries included. The client fixture sends every request to the test
database.

They require the local PostgreSQL container to be running. No test calls
Gemini or Langfuse.
"""

import threading

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent import SAFETY_POLICY, SafetyCategory
from app.ai import GeminiProvider
from app.api.dependencies import get_ai_provider, get_tracer
from app.evaluation import create_fixtures
from app.main import app
from app.models import User, UserProfile, WorkoutPlan, WorkoutSession, WorkoutSet
from app.observability import TRACING_OFF, Tracer
from app.repositories import UserRepository
from app.services import CoachService, UserProfileService
from tests.auth import bearer
from tests.observability import FailingBackend
from tests.reliability import (
    EchoModel,
    api_error,
    concurrent_tracer,
    concurrently,
    model_response,
    transport_provider,
)

URL = "/coach/message"
FLAGGED = "I have sharp knee pain when I squat. Should I push through it?"
CANARY = "UPSTREAM_DETAIL_CANARY"


@pytest.fixture
def fixtures(client, service_session):
    created = create_fixtures(service_session)
    service_session.rollback()
    return created


@pytest.fixture
def api(client):
    """The API with a shared model and a recording tracer, as production shares
    them; returns (client that answers 500 on a server error, model, backend)."""
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


def rows(test_engine):
    with Session(test_engine) as session:
        return [
            session.scalar(select(func.count()).select_from(model))
            for model in (User, UserProfile, WorkoutPlan, WorkoutSession, WorkoutSet)
        ]


def status_of(backend, request_number=-1):
    return backend.roots()[request_number].metadata["status"]


# --- the provider failure matrix ---

FAILURES = {
    # what the transport does: (response or exception, HTTP status, trace status)
    "timeout": (httpx.ReadTimeout(CANARY), 502, "provider_timeout"),
    "rate_limit": (api_error(429, "RESOURCE_EXHAUSTED"), 502, "rate_limit"),
    "unavailable": (api_error(503, "UNAVAILABLE"), 502, "provider_error"),
    "gateway_timeout": (api_error(504, "DEADLINE_EXCEEDED"), 502, "provider_timeout"),
    "server_error": (api_error(500, "INTERNAL"), 502, "provider_error"),
    "network": (httpx.ConnectError(CANARY), 502, "provider_error"),
    "malformed_body": (httpx.Response(200, content=b"<html>" + CANARY.encode()), 502, "provider_error"),
    "no_candidates": (httpx.Response(200, json={"candidates": []}), 502, "model_output_invalid"),
    "empty_output": (httpx.Response(200, json={}), 502, "model_output_invalid"),
    "blocked_output": (
        httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}),
        502,
        "model_output_invalid",
    ),
    "text_without_decision": (
        httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": CANARY}]}}]}),
        502,
        "model_output_invalid",
    ),
}


@pytest.mark.parametrize("failure", FAILURES)
def test_a_provider_failure_is_tried_once_and_changes_nothing(
    api, fixtures, test_engine, failure
):
    client, model, backend = api
    model.failures["f"] = FAILURES[failure][0]
    before = rows(test_engine)

    response = client.post(URL, headers=bearer(fixtures.user_id), json={"message": "f goal"})

    assert response.status_code == FAILURES[failure][1]
    assert response.json() == {"detail": "the AI coach could not answer; try again later"}
    assert status_of(backend) == FAILURES[failure][2]
    # one attempt: the SDK does not retry, and neither does Formiq
    assert len(model.requests("f")) == 1
    assert rows(test_engine) == before
    assert test_engine.pool.checkedout() == 0
    # the next request starts clean, on the same shared provider
    after = client.post(URL, headers=bearer(fixtures.user_id), json={"message": "n goal"})
    assert after.json() == {"reply": f"n user={fixtures.user_id} age=30"}
    assert backend.roots()[-1].metadata["model_requests"] == 2


def test_an_unconfigured_provider_sends_nothing_and_answers_503(client, fixtures, test_engine):
    tracer, backend = concurrent_tracer()
    app.dependency_overrides[get_ai_provider] = lambda: GeminiProvider(
        None, "gemini-reliability", timeout_seconds=30
    )
    app.dependency_overrides[get_tracer] = lambda: tracer
    before = rows(test_engine)
    try:
        response = client.post(
            URL, headers=bearer(fixtures.user_id), json={"message": "How often?"}
        )
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)
        app.dependency_overrides.pop(get_tracer, None)

    assert response.status_code == 503
    assert response.json() == {"detail": "the AI coach is not configured"}
    assert status_of(backend) == "provider_not_configured"
    assert rows(test_engine) == before


@pytest.mark.parametrize("failure", FAILURES)
def test_a_flagged_request_keeps_the_fixed_safe_reply_whatever_the_provider_does(
    api, fixtures, failure
):
    client, model, backend = api
    model.failures["f"] = FAILURES[failure][0]

    response = client.post(URL, headers=bearer(fixtures.user_id), json={"message": f"f {FLAGGED}"})

    assert response.status_code == 200
    assert response.json() == {"reply": SAFETY_POLICY[SafetyCategory.PAIN_OR_INJURY].fallback_reply}
    assert status_of(backend) == "safety_redirect"
    assert len(model.requests("f")) == 1


def test_the_configured_timeout_bounds_every_model_request(api, fixtures):
    client, model, _ = api

    client.post(URL, headers=bearer(fixtures.user_id), json={"message": "t goal"})

    timeouts = [sent.timeout for sent in model.requests("t")]
    assert timeouts == [{"connect": 30.0, "read": 30.0, "write": 30.0, "pool": 30.0}] * 2


# --- the same failure, again and again ---


@pytest.mark.parametrize(
    "failure", [httpx.ReadTimeout(CANARY), api_error(503, "UNAVAILABLE")], ids=["timeout", "503"]
)
def test_a_repeated_provider_failure_never_builds_up(api, fixtures, test_engine, failure):
    client, model, backend = api
    model.failures["f"] = failure

    responses = [
        client.post(URL, headers=bearer(fixtures.user_id), json={"message": "f goal"})
        for _ in range(10)
    ]

    assert {response.status_code for response in responses} == {502}
    # one attempt each, never more as failures accumulate
    assert len(model.requests("f")) == 10
    traces = [{**root.metadata, "request_id": None} for root in backend.roots()]
    assert all(trace == traces[0] for trace in traces)
    assert traces[0]["model_requests"] == 1
    assert test_engine.pool.checkedout() == 0
    after = client.post(URL, headers=bearer(fixtures.user_id), json={"message": "n goal"})
    assert after.status_code == 200
    assert backend.roots()[-1].metadata["model_requests"] == 2
    assert backend.roots()[-1].metadata["iterations"] == 1


def test_a_repeated_tool_failure_never_builds_up(api, fixtures, monkeypatch):
    client, model, backend = api

    def broken(*args):
        raise RuntimeError("TOOL_DETAIL_CANARY")

    monkeypatch.setattr(UserProfileService, "get_profile_by_user_id", broken)

    replies = [
        client.post(URL, headers=bearer(fixtures.user_id), json={"message": "f goal"}).json()
        for _ in range(10)
    ]

    assert replies == [{"reply": "f error=tool_error"}] * 10
    traces = [{**root.metadata, "request_id": None} for root in backend.roots()]
    assert all(trace == traces[0] for trace in traces)
    assert traces[0]["tool_tool_error"] == 1
    assert traces[0]["model_requests"] == 2
    # the cause reaches neither the client nor the model
    assert all("TOOL_DETAIL_CANARY" not in sent.text for sent in model.requests("f"))


def test_a_repeated_tracing_failure_never_builds_up(service_session, fixtures):
    backend = FailingBackend(ConnectionError)
    tracer = Tracer(backend)

    def ask(tracer):
        provider = transport_provider(EchoModel())
        return CoachService(service_session, provider, tracer).reply(fixtures.user_id, "f goal")

    expected = ask(TRACING_OFF)
    calls = []
    for _ in range(10):
        before = backend.calls
        assert ask(tracer) == expected
        calls.append(backend.calls - before)

    # the same backend calls each time: nothing is queued or retried
    assert len(set(calls)) == 1


# --- timeouts at each point of a turn ---


class TimeoutAt(EchoModel):
    """For the token "t", times out at the request-th model request (from 1) of
    its turn. Every turn reads the profile three rounds, then answers."""

    def __init__(self, request, barrier=None):
        super().__init__(barrier)
        self.at = request

    def turn(self, sent):
        if sent.token == "t" and len(sent.results) + 1 == self.at:
            raise httpx.ReadTimeout(CANARY)
        if len(sent.results) < 3:
            return model_response("get_user_profile")
        return super().turn(sent)


@pytest.mark.parametrize("at", [1, 2, 4], ids=["first_request", "after_a_tool", "fourth_request"])
def test_a_timeout_anywhere_in_a_turn_ends_it_without_a_retry(client, fixtures, test_engine, at):
    model = TimeoutAt(at)
    tracer, backend = concurrent_tracer()
    app.dependency_overrides[get_ai_provider] = lambda: transport_provider(model)
    app.dependency_overrides[get_tracer] = lambda: tracer
    try:
        api = TestClient(app, raise_server_exceptions=False)
        response = api.post(URL, headers=bearer(fixtures.user_id), json={"message": "t goal"})
        after = api.post(URL, headers=bearer(fixtures.user_id), json={"message": "n goal"})
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)
        app.dependency_overrides.pop(get_tracer, None)

    assert response.status_code == 502
    first = backend.roots()[0].metadata
    assert first["status"] == "provider_timeout"
    # the requests before it, and the one that timed out: nothing more
    assert len(model.requests("t")) == at
    assert first["model_requests"] == at
    assert test_engine.pool.checkedout() == 0
    # the next request starts from nothing
    assert after.status_code == 200
    assert backend.roots()[1].metadata["model_requests"] == 4


def test_simultaneous_timeouts_end_only_their_own_requests(test_engine, fixtures):
    count = 8
    model = EchoModel(threading.Barrier(count))
    timing_out = {f"c{n}" for n in range(0, count, 2)}
    for token in timing_out:
        model.failures[token] = httpx.ReadTimeout(CANARY)
    provider = transport_provider(model)
    tracer, backend = concurrent_tracer()

    def ask(token):
        def request():
            with Session(test_engine) as session:
                return CoachService(session, provider, tracer).reply(
                    fixtures.user_id, f"{token} goal"
                )

        return request

    results = concurrently([ask(f"c{n}") for n in range(count)])

    for n, result in enumerate(results):
        token = f"c{n}"
        if token in timing_out:
            assert type(result).__name__ == "AIProviderError"
            assert len(model.requests(token)) == 1
        else:
            assert result == f"{token} user={fixtures.user_id} age=30"
    statuses = sorted(root.metadata["status"] for root in backend.roots())
    assert statuses == ["provider_timeout"] * 4 + ["success"] * 4
    assert test_engine.pool.checkedout() == 0


# --- unexpected exceptions ---

SECRET = "SECRET_EXCEPTION_CANARY"


def raising(*args, **kwargs):
    raise RuntimeError(f"{SECRET} password=hunter2 host=db.internal")


class FailingUserLookup(UserRepository):
    """The coach service's user lookup, failing; authentication's still works."""

    get_by_id = raising


EXCEPTIONS = {
    # where it is raised, and what the client gets
    "service": ("app.services.coach_service.UserRepository", 500, "unknown_error"),
    "graph_node": ("app.agent.graph.fit_request", 500, "unknown_error"),
    "safety_check": ("app.agent.graph.assess_safety", 500, "unknown_error"),
    "tool": ("app.services.UserProfileService.get_profile_by_user_id", 200, "cannot_answer"),
}


@pytest.mark.parametrize("where", EXCEPTIONS)
def test_an_unexpected_exception_ends_only_its_request_and_shows_nothing(
    api, fixtures, test_engine, monkeypatch, where
):
    client, model, backend = api
    target, http_status, status = EXCEPTIONS[where]
    monkeypatch.setattr(target, FailingUserLookup if where == "service" else raising)

    response = client.post(URL, headers=bearer(fixtures.user_id), json={"message": "x goal"})

    assert response.status_code == http_status
    assert SECRET not in response.text
    assert all(SECRET not in sent.text for sent in model.requests("x"))
    assert status_of(backend) == status
    assert test_engine.pool.checkedout() == 0
    monkeypatch.undo()
    after = client.post(URL, headers=bearer(fixtures.user_id), json={"message": "n goal"})
    assert after.status_code == 200
    assert status_of(backend) == "success"


def test_an_unexpected_exception_in_the_provider_is_a_provider_error(api, fixtures):
    client, model, backend = api
    model.failures["x"] = RuntimeError(f"{SECRET} password=hunter2")

    response = client.post(URL, headers=bearer(fixtures.user_id), json={"message": "x goal"})

    # the provider turns anything its SDK raises into a provider error
    assert response.status_code == 502
    assert SECRET not in response.text
    assert status_of(backend) == "provider_error"


@pytest.mark.parametrize("error", [RuntimeError, TimeoutError, ConnectionError, ValueError])
def test_an_unexpected_exception_in_tracing_changes_nothing(api, fixtures, error):
    client, _, _ = api
    expected = client.post(URL, headers=bearer(fixtures.user_id), json={"message": "x goal"})
    app.dependency_overrides[get_tracer] = lambda: Tracer(FailingBackend(error))

    response = client.post(URL, headers=bearer(fixtures.user_id), json={"message": "x goal"})

    assert (response.status_code, response.json()) == (expected.status_code, expected.json())


def test_the_user_lookup_failing_is_not_a_missing_user(api, fixtures, monkeypatch):
    # a database failure is a server error, never a 404 that would tell the
    # client the user does not exist
    client, _, backend = api
    monkeypatch.setattr("app.services.coach_service.UserRepository", FailingUserLookup)

    response = client.post(URL, headers=bearer(fixtures.user_id), json={"message": "x goal"})

    assert response.status_code == 500
    assert status_of(backend) == "unknown_error"


def test_the_authentication_lookup_failing_is_a_server_error(api, fixtures, monkeypatch):
    # nor a 401 that would tell the client its token is bad: the request ends
    # before the coach, so nothing reaches the model or the trace
    client, model, backend = api
    monkeypatch.setattr(UserRepository, "get_by_id", raising)

    response = client.post(URL, headers=bearer(fixtures.user_id), json={"message": "x goal"})

    assert response.status_code == 500
    assert SECRET not in response.text
    assert model.requests("x") == []
    assert backend.roots() == []
