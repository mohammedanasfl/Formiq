"""Tracing test doubles: a backend that records in memory what the coach would
send, and backends that fail. No test sends anything over the network."""

import io
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import NamedTuple

import pytest

from app.api.dependencies import get_tracer
from app.core.config import settings
from app.observability import Tracer
from app.observability.debug import DebugSink
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
    would otherwise send its trace to that real project. The same goes for
    AGENT_DEBUG, which a developer may turn on in backend/.env to watch the
    playground: no test prints a turn to the terminal, and the tracer stays the
    shared off one, unless the test says so. A test that is about tracing or the
    debug output gives its own tracer or settings, as those tests do."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "langfuse_tracing_enabled", False)
        patch.setattr(settings, "agent_debug", "off")
        # a tracer built before from the loaded settings is not reused
        get_tracer.cache_clear()
        try:
            yield
        finally:
            get_tracer.cache_clear()


def comparable(metadata: dict) -> dict:
    """A request's root metadata without what differs between identical requests:
    its id, and every measured duration (latency fields and the milliseconds in
    the trajectory's event codes). What is left must be the same for requests of
    one kind, which is how a test sees that no counter carries over."""
    kept = {
        key: value
        for key, value in metadata.items()
        if key != "request_id" and not key.startswith("latency_") and key != "model_request_ms"
    }
    if "trajectory" in kept:
        kept["trajectory"] = [re.sub(r":\d+ms$", "", code) for code in kept["trajectory"]]
    return kept


class Debugging(NamedTuple):
    """A tracer with the local debug output (AGENT_DEBUG) on, writing to memory:
    the tracer, what its recording backend was sent, the stream and the sink."""

    tracer: Tracer
    backend: "RecordingBackend"
    stream: io.StringIO
    sink: DebugSink


def debugging(level: str = "content", **options) -> Debugging:
    stream = io.StringIO()
    backend = RecordingBackend()
    sink = DebugSink(level, stream, **options)
    return Debugging(Tracer(backend, debug=sink), backend, stream, sink)


@dataclass
class Line:
    """One logical line of the debug output: its head, and the lines that continue it."""

    tag: str
    seq: int
    ms: int | None
    label: str
    fields: str
    body: list[str] = field(default_factory=list)

    def has(self, text: str) -> bool:
        return text in self.fields or any(text in line for line in self.body)


_HEAD = re.compile(r"^\[(\w{8}) #(\d{3}) \+(\d+)ms\] (\S+)(?: (.*))?$")
_BODY = re.compile(r"^\[(\w{8}) #(\d{3})\]   (.*)$")


def parse(output: str) -> list[Line]:
    """The debug output as its lines (the header of each turn is left out)."""
    lines: list[Line] = []
    for raw in output.splitlines():
        if raw.startswith("=== agent turn"):
            continue
        if head := _HEAD.match(raw):
            tag, seq, ms, label, fields = head.groups()
            lines.append(Line(tag, int(seq), int(ms), label, fields or ""))
        elif body := _BODY.match(raw):
            assert (
                lines and (lines[-1].tag, lines[-1].seq) == (body.group(1), int(body.group(2)))
            ), f"a stray line: {raw!r}"
            lines[-1].body.append(body.group(3))
        else:
            raise AssertionError(f"a line that is not the debug output's: {raw!r}")
    return lines


def labelled(lines: list[Line], label: str) -> list[Line]:
    return [line for line in lines if line.label == label]
