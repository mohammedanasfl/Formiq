"""Tracing test doubles: a backend that records in memory what the coach would
send, and backends that fail. No test sends anything over the network."""

import json
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from app.api.dependencies import get_tracer
from app.core.config import settings
from app.observability import Tracer
from app.observability.memory import MemoryBackend


class RecordingBackend(MemoryBackend):
    """The in-memory backend, with everything it was handed as text, to search
    for canaries."""

    def everything(self) -> str:
        return json.dumps(self.sent, default=repr)


def recording() -> tuple[Tracer, RecordingBackend]:
    backend = RecordingBackend()
    return Tracer(backend), backend


class FailingBackend:
    """A backend whose every call fails, as an unreachable or broken Langfuse
    would: the message carries a canary that must never reach anything."""

    def __init__(self, error: type[BaseException] = RuntimeError) -> None:
        self.error = error
        self.calls = 0

    def _fail(self, *args, **kwargs):
        self.calls += 1
        raise self.error("API_KEY_CANARY: tracing backend unavailable")

    start_trace = start = update = end = end_trace = content = shutdown = _fail


@contextmanager
def application_tracing_off() -> Iterator[None]:
    """The application's own tracer (get_tracer) is off while this lasts,
    whatever backend/.env configures: the settings are loaded from it, and it
    may enable Langfuse for development, so a test request through the API
    would otherwise send its trace to that real project. A test that is about
    tracing gives its own tracer or settings, as the tracing tests do."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "langfuse_tracing_enabled", False)
        # a tracer built before from the loaded settings is not reused
        get_tracer.cache_clear()
        try:
            yield
        finally:
            get_tracer.cache_clear()
