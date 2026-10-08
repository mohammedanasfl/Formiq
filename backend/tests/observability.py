"""Tracing test doubles: a backend that records in memory what the coach would
send, and backends that fail. No test sends anything over the network."""

import json

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

    start_trace = start = update = end = end_trace = shutdown = _fail
