"""Formiq's observability interface: the trace of one coach request.

The coach records what happened (which steps ran, in what order, how long they
took, how they ended) as a tree of observations under one trace per request.
The interface is Formiq's own; a backend sends it somewhere: Langfuse in
production (app.observability.langfuse), nothing when tracing is off, or memory
in tests.

Two rules hold whatever the backend does:

- Observability never changes the request. Every backend call is guarded: if it
  fails or is slow to fail, the coach carries on exactly as it would without
  it, and the failure is logged without its details. Nothing recorded is read
  back by the coach.
- Only metadata is recorded: counts, sizes, names, statuses, categories and
  identifiers Formiq generates, never the user's words, the conversation, tool
  results, the instructions or the model's reasoning. Observations take no input
  or output, and safe_metadata() keeps only flat, short, primitive values, so a
  dict of data cannot be recorded by mistake.
"""

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Literal, Protocol

from app.observability.failures import classify

logger = logging.getLogger(__name__)

Kind = Literal["agent", "chain", "span", "generation", "tool", "guardrail"]
Level = Literal["DEFAULT", "WARNING", "ERROR"]
Metadata = dict[str, bool | int | float | str | list[bool | int | float | str] | None]

# the longest string value recorded: names, categories and ids, not text
MAX_VALUE_CHARS = 100
# the longest list value recorded, such as the tools a turn used
MAX_LIST_ITEMS = 25

_PRIMITIVES = (bool, int, float, str)


def safe_metadata(values: Mapping[str, Any]) -> Metadata:
    """Only what may be recorded: primitive values (and short lists of them),
    strings cut to MAX_VALUE_CHARS. Anything else, such as a dict of data or an
    object, is left out."""
    safe: Metadata = {}
    for key, value in values.items():
        if not isinstance(key, str):
            continue
        if value is None or isinstance(value, _PRIMITIVES):
            safe[key] = value[:MAX_VALUE_CHARS] if isinstance(value, str) else value
        elif isinstance(value, list | tuple) and all(isinstance(v, _PRIMITIVES) for v in value):
            safe[key] = [
                v[:MAX_VALUE_CHARS] if isinstance(v, str) else v for v in value[:MAX_LIST_ITEMS]
            ]
    return safe


class Backend(Protocol):
    """Where observations go. Every call may fail; Observation guards them."""

    def start_trace(
        self, *, name: str, request_id: str, user_id: str, metadata: Metadata
    ) -> Any: ...

    def start(
        self, parent: Any, *, name: str, kind: Kind, metadata: Metadata, model: str | None
    ) -> Any: ...

    def update(
        self,
        handle: Any,
        *,
        metadata: Metadata,
        level: Level | None,
        status_message: str | None,
        usage: dict[str, int] | None,
    ) -> None: ...

    def end(self, handle: Any) -> None: ...

    def end_trace(self, handle: Any) -> None: ...


class NoBackend:
    """Tracing off: nothing is recorded."""

    def start_trace(self, **kwargs: Any) -> None:
        return None

    def start(self, parent: Any, **kwargs: Any) -> None:
        return None

    def update(self, handle: Any, **kwargs: Any) -> None:
        return None

    def end(self, handle: Any) -> None:
        return None

    def end_trace(self, handle: Any) -> None:
        return None


class Observation:
    """One step of a request's trace. Every method is safe to call: a failing
    backend is logged and ignored."""

    def __init__(self, backend: Backend, handle: Any) -> None:
        self._backend = backend
        self._handle = handle

    def _guard(self, action: str, call: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return call(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - observability must not fail the request
            # the type only: a message could hold a URL or a key
            logger.warning("Tracing %s failed (%s); the request goes on", action, type(error).__name__)
            return None

    @contextmanager
    def child(
        self, name: str, kind: Kind = "span", *, model: str | None = None, **metadata: Any
    ) -> Iterator["Observation"]:
        """A step under this one, from entering the block to leaving it. An
        exception from the block marks it failed and goes on unchanged."""
        child = self.start(name, kind, model=model, **metadata)
        try:
            yield child
        except BaseException as error:
            child.fail(failure_category(error))
            raise
        finally:
            child.end()

    def start(
        self, name: str, kind: Kind = "span", *, model: str | None = None, **metadata: Any
    ) -> "Observation":
        """A step under this one, ended by end()."""
        handle = self._guard(
            "start",
            self._backend.start,
            self._handle,
            name=name,
            kind=kind,
            metadata=safe_metadata(metadata),
            model=model,
        )
        return Observation(self._backend, handle)

    def update(self, **metadata: Any) -> None:
        self._update(metadata)

    def usage(self, usage: Mapping[str, int] | None) -> None:
        """The model's token counts, as the provider reported them; none
        reported is recorded as unavailable, never estimated."""
        counts = {k: v for k, v in (usage or {}).items() if isinstance(v, int) and v >= 0}
        self._update({"usage_available": bool(counts)}, usage=counts or None)

    def warn(self, category: str, **metadata: Any) -> None:
        self._update({**metadata, "outcome": category}, level="WARNING", status_message=category)

    def fail(self, category: str, **metadata: Any) -> None:
        self._update({**metadata, "outcome": category}, level="ERROR", status_message=category)

    def end(self) -> None:
        self._guard("end", self._backend.end, self._handle)

    def _update(
        self,
        metadata: Mapping[str, Any],
        *,
        level: Level | None = None,
        status_message: str | None = None,
        usage: dict[str, int] | None = None,
    ) -> None:
        self._guard(
            "update",
            self._backend.update,
            self._handle,
            metadata=safe_metadata(metadata),
            level=level,
            status_message=status_message,
            usage=usage,
        )


# What a request ended with. ERROR statuses are failures of the request; the
# others are answers, even when the answer is that the coach cannot answer.
SUCCESS_STATUSES = frozenset({"success", "clarification"})
WARNING_STATUSES = frozenset({"safety_redirect", "cannot_answer"})


class RunTrace(Observation):
    """The trace of one coach request: its root observation, its counters and
    its final status."""

    def __init__(self, backend: Backend, handle: Any, request_id: str) -> None:
        super().__init__(backend, handle)
        self.request_id = request_id
        self.counts: dict[str, int] = {}
        self.status: str | None = None

    def count(self, name: str, amount: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + amount

    def finish(self, status: str, **metadata: Any) -> None:
        """The request's outcome, with its counters."""
        self.status = status
        values = {**metadata, **self.counts, "status": status}
        if status in SUCCESS_STATUSES:
            self._update(values, status_message=status)
        elif status in WARNING_STATUSES:
            self._update(values, level="WARNING", status_message=status)
        else:
            self._update(values, level="ERROR", status_message=status)


class Tracer:
    """Starts the trace of each request on its backend."""

    def __init__(self, backend: Backend | None = None) -> None:
        self.backend: Backend = backend or NoBackend()

    @property
    def enabled(self) -> bool:
        return not isinstance(self.backend, NoBackend)

    @contextmanager
    def request(self, name: str, *, request_id: str, user_id: int, **metadata: Any) -> Iterator[RunTrace]:
        """The trace of one request, from entering the block to leaving it. An
        exception from the block goes on unchanged; tracing errors never do."""
        probe = Observation(self.backend, None)
        handle = probe._guard(
            "start",
            self.backend.start_trace,
            name=name,
            request_id=request_id,
            user_id=str(user_id),
            metadata=safe_metadata({**metadata, "request_id": request_id}),
        )
        trace = RunTrace(self.backend, handle, request_id)
        try:
            yield trace
        finally:
            trace._guard("end", self.backend.end_trace, handle)

    def shutdown(self) -> None:
        """Send what is still buffered; called once, when the application stops."""
        shutdown = getattr(self.backend, "shutdown", None)
        if shutdown is not None:
            Observation(self.backend, None)._guard("shutdown", shutdown)


TRACING_OFF = Tracer()


def no_trace() -> RunTrace:
    """A trace that records nothing, for a run outside a traced request."""
    return RunTrace(NoBackend(), None, request_id="")


def failure_category(error: BaseException) -> str:
    """The failure an exception stands for, as a category: never its message."""
    return classify(error)
