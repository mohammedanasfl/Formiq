"""Interrupted coach requests: an interruption (a BaseException that is not an
Exception, such as KeyboardInterrupt) goes through the coach unchanged, never
becomes an error response or a success, and leaves no transaction open.

The coach's endpoint is synchronous: FastAPI runs it in a worker thread, and
Python cannot stop a thread from outside. So what can interrupt a request is
an interruption raised inside it, which these tests raise at each point of a
turn, or the cancellation of the ASGI task that waits for the thread, which
the last tests cover with what the framework does.

They require the local PostgreSQL container to be running.
"""

import asyncio
import threading

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_ai_provider, get_tracer
from app.db import database
from app.main import app
from app.observability import Tracer
from app.observability.memory import MemoryBackend
from app.repositories import UserRepository
from app.services import CoachService, UserProfileService
from tests.auth import bearer
from tests.integration.agent_fixtures import create_fixtures
from tests.reliability import (
    WAIT_SECONDS,
    ConcurrentBackend,
    EchoModel,
    TrackedSessions,
    model_response,
    transport_provider,
)


@pytest.fixture
def fixtures(service_session):
    created = create_fixtures(service_session)
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


class Interrupt(KeyboardInterrupt):
    """An interruption raised inside the request."""


class Rounds(EchoModel):
    """Reads the profile three rounds, then answers; raises interrupt at the
    at-th model request (from 1)."""

    def __init__(self, at=None, interrupt=None):
        super().__init__()
        self.at, self.interrupt = at, interrupt

    def turn(self, sent):
        if len(sent.results) + 1 == self.at:
            raise self.interrupt
        if len(sent.results) < 3:
            return model_response("get_user_profile")
        return super().turn(sent)


class InterruptingBackend(MemoryBackend):
    """Tracing that is interrupted when the first tool observation ends."""

    def __init__(self, interrupt):
        super().__init__()
        self.interrupt = interrupt

    def end(self, handle):
        super().end(handle)
        if handle.kind == "tool":
            raise self.interrupt


def run(fixtures, test_engine, *, model, tracer=None):
    """A request as the API runs it, through get_db; returns the interruption
    and the session, which FastAPI does not close when an interruption goes
    through it (its dependency cleanup runs for an Exception only)."""
    dependency = database.get_db()
    session = next(dependency)
    provider = transport_provider(model)
    with pytest.raises(BaseException) as raised:
        CoachService(session, provider, tracer or Tracer()).reply(fixtures.user_id, "i goal")
    return raised.value, session, dependency


@pytest.mark.parametrize(
    "at", [1, 2, 4], ids=["during_the_first_model_call", "after_a_tool", "later_in_the_turn"]
)
def test_an_interruption_in_the_model_goes_through_unchanged_and_holds_nothing(
    fixtures, test_engine, sessions, at
):
    interrupt = Interrupt()
    model = Rounds(at, interrupt)

    raised, session, dependency = run(fixtures, test_engine, model=model)

    # the same exception, not a provider error and not an answer
    assert raised is interrupt
    # nothing ran after it
    assert len(model.requests("i")) == at
    # even unclosed, the session holds no transaction or connection
    assert not session.in_transaction()
    assert test_engine.pool.checkedout() == 0
    dependency.close()
    assert sessions.unclosed() == []


def test_an_interruption_during_a_tools_read_ends_the_read(
    fixtures, test_engine, sessions, monkeypatch
):
    interrupt = Interrupt()
    real = UserProfileService.get_profile_by_user_id

    def interrupted(self, user_id):
        real(self, user_id)  # the read has started its transaction
        raise interrupt

    monkeypatch.setattr(UserProfileService, "get_profile_by_user_id", interrupted)
    model = Rounds()

    raised, session, dependency = run(fixtures, test_engine, model=model)

    # not turned into a tool error for the model to read
    assert raised is interrupt
    assert len(model.requests("i")) == 1
    assert not session.in_transaction()
    assert test_engine.pool.checkedout() == 0
    dependency.close()


def test_an_interruption_in_tracing_goes_through_unchanged(fixtures, test_engine, sessions):
    interrupt = Interrupt()
    model = Rounds()

    raised, session, dependency = run(
        fixtures, test_engine, model=model, tracer=Tracer(InterruptingBackend(interrupt))
    )

    # tracing swallows its own errors, never an interruption
    assert raised is interrupt
    assert not session.in_transaction()
    assert test_engine.pool.checkedout() == 0
    dependency.close()


def test_an_interruption_before_the_model_is_called(fixtures, test_engine, sessions):
    interrupt = Interrupt()

    class InterruptedStart(MemoryBackend):
        def start_trace(self, **kwargs):
            raise interrupt

    model = Rounds()

    raised, session, dependency = run(
        fixtures, test_engine, model=model, tracer=Tracer(InterruptedStart())
    )

    assert raised is interrupt
    assert model.requests("i") == []
    assert not session.in_transaction()
    dependency.close()


def test_an_interruption_during_the_user_lookup_holds_its_read_until_the_session_closes(
    fixtures, test_engine, sessions, monkeypatch
):
    # The one point where an interruption leaves a transaction open: the user
    # lookup, before the coach ends its read. The session holds it until it is
    # closed, which get_db does for an Exception and FastAPI skips for an
    # interruption, so it waits for the session to be dropped.
    interrupt = Interrupt()
    real = UserRepository.get_by_id

    def interrupted(self, user_id):
        real(self, user_id)
        raise interrupt

    monkeypatch.setattr(UserRepository, "get_by_id", interrupted)

    raised, session, dependency = run(fixtures, test_engine, model=Rounds())

    assert raised is interrupt
    assert session.in_transaction()
    dependency.close()
    assert not session.in_transaction()
    assert test_engine.pool.checkedout() == 0


def test_after_an_interruption_the_next_request_is_unaffected(fixtures, test_engine, sessions):
    model = Rounds(2, Interrupt())
    run(fixtures, test_engine, model=model)[2].close()

    session = database.SessionLocal()
    try:
        reply = CoachService(session, transport_provider(Rounds())).reply(
            fixtures.user_id, "n goal"
        )
    finally:
        session.close()

    assert reply == f"n user={fixtures.user_id} age=30"


def test_a_cancelled_error_raised_in_a_node_is_never_a_success(client, fixtures):
    # LangGraph turns an asyncio.CancelledError raised inside a node into its
    # NodeCancelledError, an Exception: the request fails as an unknown error
    # (500), never as an answer
    model = Rounds(1, asyncio.CancelledError())
    backend = ConcurrentBackend()
    provider = transport_provider(model)
    app.dependency_overrides[get_ai_provider] = lambda: provider
    app.dependency_overrides[get_tracer] = lambda: Tracer(backend)
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            "/coach/message", headers=bearer(fixtures.user_id), json={"message": "i goal"}
        )
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)
        app.dependency_overrides.pop(get_tracer, None)

    assert response.status_code == 500
    (root,) = backend.roots()
    assert root.metadata["status"] == "unknown_error"


def test_a_cancelled_api_request_runs_to_its_own_end_and_then_holds_nothing(
    fixtures, test_engine, sessions
):
    # Cancelling the ASGI task does not stop the endpoint's thread: the turn
    # goes on to its end, within its own limits, and its reply is dropped. The
    # session is closed when FastAPI drops the dependency, possibly before the
    # turn ends; the tools end each read anyway, so once the turn is over no
    # connection or transaction is held.
    entered, release, done = threading.Event(), threading.Event(), threading.Event()

    class Held(Rounds):
        def turn(self, sent):
            if not sent.results:
                entered.set()
                release.wait(WAIT_SECONDS)
            return super().turn(sent)

    class Finishing(ConcurrentBackend):
        def end_trace(self, handle):
            super().end_trace(handle)
            done.set()

    model, backend = Held(), Finishing()
    provider = transport_provider(model)
    app.dependency_overrides[get_ai_provider] = lambda: provider
    app.dependency_overrides[get_tracer] = lambda: Tracer(backend)

    async def cancel_during_the_model_call():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://formiq.test") as api:
            task = asyncio.create_task(
                api.post(
                    "/coach/message", headers=bearer(fixtures.user_id), json={"message": "c goal"}
                )
            )
            assert await asyncio.to_thread(entered.wait, WAIT_SECONDS)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    try:
        asyncio.run(cancel_during_the_model_call())
        release.set()
        assert done.wait(WAIT_SECONDS)
    finally:
        release.set()
        app.dependency_overrides.pop(get_ai_provider, None)
        app.dependency_overrides.pop(get_tracer, None)

    # it went on: three reads of the trusted user's profile and the answer
    sent = model.requests("c")
    assert len(sent) == 4
    assert {r["response"]["output"]["user_id"] for s in sent for r in s.results} == {
        fixtures.user_id
    }
    (root,) = backend.roots()
    assert root.metadata["status"] == "success"
    assert sessions.in_transaction() == []
    assert test_engine.pool.checkedout() == 0
