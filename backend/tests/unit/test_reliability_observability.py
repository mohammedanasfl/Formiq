"""Tracing that fails, hangs, is malformed or shuts down never changes a turn:
every scenario ends exactly as it does with tracing off, alone or at the same
time as others. And the real Langfuse SDK keeps each request's trace to that
request, however requests end.

The scenarios are those of test_reliability_state (a profile answer, a
compacted run to the limit, a flagged request whose model fails, an invalid
model output, refused calls). What is compared is the turn's outcome, never
the trace. Langfuse exports to memory, to a failing or hanging exporter, or to
a closed local port: no test sends anything over the network.
"""

import threading
import time
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.api import dependencies
from app.main import app
from app.observability import TRACING_OFF, Tracer
from app.observability.langfuse_backend import create_tracer
from app.observability.memory import MemoryBackend
from tests.observability import FailingBackend
from tests.reliability import WAIT_SECONDS, concurrently
from tests.unit.test_reliability_state import SCENARIOS, ScenarioModel, outcome


@pytest.fixture(scope="module")
def baseline():
    """Each scenario's outcome with tracing off."""
    return {name: outcome(scenario) for name, scenario in SCENARIOS.items()}


def langfuse(exporter: SpanExporter | None, *, base_url: str = "http://127.0.0.1:9") -> Tracer:
    """The real Langfuse tracer, exporting to exporter (or over HTTP to
    base_url). The SDK shares one client per public key in a process, so each
    tracer gets its own key: one test's shutdown must not be another's."""
    tracer = create_tracer(
        enabled=True,
        public_key=f"pk-lf-{uuid.uuid4().hex}",
        secret_key="sk-lf-reliability",
        base_url=base_url,
        environment="test",
        timeout_seconds=1,
        span_exporter=exporter,
    )
    assert tracer.enabled
    return tracer


class RaisingExporter(SpanExporter):
    """An export that fails, as Langfuse refusing or erroring would."""

    def __init__(self):
        self.exports = 0

    def export(self, spans):
        self.exports += 1
        raise ConnectionError("API_KEY_CANARY: export failed")

    def shutdown(self):
        pass


class HangingExporter(SpanExporter):
    """An export that waits until released, as a Langfuse that does not answer."""

    def __init__(self):
        self.release = threading.Event()
        self.started = threading.Event()

    def export(self, spans):
        self.started.set()
        self.release.wait(WAIT_SECONDS)
        return SpanExportResult.FAILURE

    def shutdown(self):
        self.release.set()


class MalformedBackend:
    """A backend that breaks its contract: odd handles back, and failures on
    what it is given back."""

    def start_trace(self, **kwargs):
        return {"not": "a handle"}

    def start(self, parent, **kwargs):
        if not isinstance(parent, int):
            return 0
        raise TypeError("API_KEY_CANARY")

    def update(self, handle, **kwargs):
        return handle["missing"]

    def end(self, handle):
        return 1 / handle

    def end_trace(self, handle):
        raise RecursionError("API_KEY_CANARY")


TRACERS = {
    "unavailable": lambda: Tracer(FailingBackend(ConnectionError)),
    "connection_timeout": lambda: Tracer(FailingBackend(TimeoutError)),
    "broken": lambda: Tracer(FailingBackend(RuntimeError)),
    "malformed": lambda: Tracer(MalformedBackend()),
    "memory": lambda: Tracer(MemoryBackend()),
    "langfuse_export_failure": lambda: langfuse(RaisingExporter()),
    "langfuse_unreachable": lambda: langfuse(None),
}


@pytest.mark.parametrize("tracer", TRACERS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_a_turn_ends_the_same_whatever_its_tracing_does(baseline, scenario, tracer):
    tracing = TRACERS[tracer]()

    result = outcome(SCENARIOS[scenario], tracer=tracing)
    tracing.shutdown()

    assert result == baseline[scenario]


def test_langfuse_failing_to_start_leaves_turns_unchanged(baseline):
    with patch("app.observability.langfuse_backend.Langfuse", side_effect=RuntimeError):
        tracing = create_tracer(
            enabled=True,
            public_key="pk",
            secret_key="sk",
            base_url="http://127.0.0.1:9",
            environment="test",
            timeout_seconds=1,
        )

    assert tracing is TRACING_OFF
    assert {name: outcome(s, tracer=tracing) for name, s in SCENARIOS.items()} == baseline


def test_a_hanging_langfuse_export_never_holds_a_turn(baseline):
    exporter = HangingExporter()
    tracing = langfuse(exporter)
    # the first export starts in the background and hangs there
    outcome(SCENARIOS["A"], tracer=tracing)
    threading.Thread(target=tracing.backend.client.flush, daemon=True).start()
    assert exporter.started.wait(WAIT_SECONDS)

    try:
        start = time.perf_counter()
        results = {name: outcome(s, tracer=tracing) for name, s in SCENARIOS.items()}
        elapsed = time.perf_counter() - start
    finally:
        exporter.release.set()
        tracing.shutdown()

    assert results == baseline
    # the turns did not wait for the export; the bound is generous
    assert elapsed < WAIT_SECONDS / 2


@pytest.mark.parametrize("tracer", ["unavailable", "malformed", "langfuse_export_failure"])
def test_simultaneous_turns_end_the_same_on_a_shared_failing_tracer(baseline, tracer):
    tracing = TRACERS[tracer]()
    names = list(SCENARIOS) * 3
    barrier = threading.Barrier(len(names))

    results = concurrently([lambda n=name: outcome(SCENARIOS[n], barrier, tracing) for name in names])
    tracing.shutdown()

    for name, result in zip(names, results, strict=True):
        assert result == baseline[name], name


def test_repeated_tracing_failures_never_change_a_turn(baseline):
    backend = FailingBackend(ConnectionError)
    tracing = Tracer(backend)
    per_turn = []

    for _ in range(10):
        before = backend.calls
        assert outcome(SCENARIOS["A"], tracer=tracing) == baseline["A"]
        per_turn.append(backend.calls - before)

    # the same backend calls each time: nothing queues up or is retried
    assert len(set(per_turn)) == 1


# --- the real Langfuse SDK: one trace per request ---


def roots(spans):
    """The spans of a trace whose parent is not in it. The coach's root
    observation has a remote parent: the trace id Langfuse derives from the
    request id."""
    ids = {span.context.span_id for span in spans}
    return [span.name for span in spans if span.parent is None or span.parent.span_id not in ids]


def traces(tracer, exporter):
    tracer.backend.client.flush()
    found = {}
    for span in exporter.get_finished_spans():
        found.setdefault(span.context.trace_id, []).append(span)
    return found


def test_each_request_is_its_own_langfuse_trace_however_it_ends():
    exporter = InMemorySpanExporter()
    tracing = langfuse(exporter)
    context_before = otel_context.get_current()
    names = ["A", "C", "D", "B", "A"]

    for name in names:
        outcome(SCENARIOS[name], tracer=tracing)
        # nothing of the request stays current in this thread
        assert otel_context.get_current() == context_before
        assert not otel_trace.get_current_span().get_span_context().is_valid

    found = traces(tracing, exporter)
    tracing.shutdown()
    assert len(found) == len(names)
    for spans in found.values():
        assert roots(spans) == ["coach_request"]
        # every span of a trace is the same request's
        assert len({span.attributes["user.id"] for span in spans}) == 1
    assert sorted(spans[0].attributes["user.id"] for spans in found.values()) == sorted(
        str(SCENARIOS[name].user_id) for name in names
    )


def test_an_interrupted_request_leaves_no_langfuse_context_behind():
    exporter = InMemorySpanExporter()
    tracing = langfuse(exporter)
    context_before = otel_context.get_current()

    with (
        pytest.raises(KeyboardInterrupt),
        tracing.request("coach_request", request_id="interrupted", user_id=1),
    ):
        raise KeyboardInterrupt

    assert otel_context.get_current() == context_before
    outcome(SCENARIOS["A"], tracer=tracing)
    found = traces(tracing, exporter)
    tracing.shutdown()
    # the next request is a trace of its own, not a child of the interrupted one
    assert len(found) == 2
    assert all(roots(spans) == ["coach_request"] for spans in found.values())


def test_simultaneous_requests_are_separate_langfuse_traces():
    exporter = InMemorySpanExporter()
    tracing = langfuse(exporter)
    names = list(SCENARIOS) * 2
    barrier = threading.Barrier(len(names))

    concurrently([lambda n=name: outcome(SCENARIOS[n], barrier, tracing) for name in names])

    found = traces(tracing, exporter)
    tracing.shutdown()
    assert len(found) == len(names)
    for spans in found.values():
        assert roots(spans) == ["coach_request"]
        assert len({span.attributes["user.id"] for span in spans}) == 1


# --- shutdown ---


@pytest.fixture
def app_tracer(monkeypatch):
    """Makes the application's tracer the one given, for the lifespan."""

    def use(tracer):
        monkeypatch.setattr(dependencies, "create_tracer", lambda **kwargs: tracer)
        dependencies.get_tracer.cache_clear()
        assert dependencies.get_tracer() is tracer

    try:
        yield use
    finally:
        dependencies.get_tracer.cache_clear()


def test_the_application_stops_cleanly_with_no_tracer_made():
    dependencies.get_tracer.cache_clear()

    with TestClient(app):
        pass

    assert dependencies.get_tracer.cache_info().currsize == 0


def test_the_application_stops_cleanly_when_tracing_fails_to_flush(app_tracer):
    backend = FailingBackend(RuntimeError)
    app_tracer(Tracer(backend))

    with TestClient(app):
        pass

    # the flush was tried, failed, and the shutdown went on
    assert backend.calls == 1


def test_the_application_stops_cleanly_when_langfuse_is_unreachable(app_tracer, baseline):
    tracing = langfuse(None)
    app_tracer(tracing)
    assert outcome(SCENARIOS["A"], tracer=tracing) == baseline["A"]

    start = time.perf_counter()
    with TestClient(app):
        pass

    # bounded by the export timeout, not by Langfuse
    assert time.perf_counter() - start < WAIT_SECONDS / 2


def test_a_shutdown_during_a_request_does_not_change_it(baseline):
    exporter = InMemorySpanExporter()
    tracing = langfuse(exporter)
    shut = threading.Event()
    generate_turn = ScenarioModel.generate_turn

    def shutting_down(self, contents, **kwargs):
        # the tracer is shut down, from another thread, while the trace is open
        if not shut.is_set():
            thread = threading.Thread(target=tracing.shutdown)
            thread.start()
            thread.join(WAIT_SECONDS)
            shut.set()
        return generate_turn(self, contents, **kwargs)

    with patch.object(ScenarioModel, "generate_turn", shutting_down):
        result = outcome(SCENARIOS["B"], tracer=tracing)

    assert shut.is_set()
    assert result == baseline["B"]
