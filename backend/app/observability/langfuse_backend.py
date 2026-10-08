"""The Langfuse backend of Formiq's tracing (Langfuse Python SDK v4).

It uses the SDK's manual observation API: the request's root observation is the
current one (start_as_current_observation) inside propagate_attributes, which
gives the trace its name, the trusted Formiq user id and the request id; every
other observation is started from its parent (start_observation) and ended
explicitly. The trace id is derived from Formiq's request id, so a log line
and its trace can be matched.

The client gets its own OpenTelemetry tracer provider, so it neither replaces
the application's global one nor exports other libraries' spans, and it exports
only Langfuse spans. Spans are exported in the background in batches: no
request waits for Langfuse, and nothing is flushed per request. As a second
line of defense, the client's mask applies safe_metadata() to whatever the SDK
is about to send.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langfuse import Langfuse, is_langfuse_span, propagate_attributes
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter

from app.observability.tracing import (
    TRACING_OFF,
    Kind,
    Level,
    Metadata,
    Tracer,
    safe_metadata,
)

logger = logging.getLogger(__name__)


@dataclass
class _Root:
    """The open root of a request's trace and the contexts it entered."""

    attributes: Any
    current: Any
    span: Any


def mask(*, data: Any, **kwargs: Any) -> Any:
    """What the SDK may send of an observation's input, output or metadata:
    Formiq records no input or output, and only safe metadata."""
    return safe_metadata(data) if isinstance(data, Mapping) else None


class LangfuseBackend:
    def __init__(self, client: Any) -> None:
        self.client = client

    def start_trace(
        self, *, name: str, request_id: str, user_id: str, metadata: Metadata
    ) -> _Root:
        attributes = propagate_attributes(
            user_id=user_id, trace_name=name, metadata={"request_id": request_id}
        )
        attributes.__enter__()
        try:
            current = self.client.start_as_current_observation(
                trace_context={"trace_id": Langfuse.create_trace_id(seed=request_id)},
                name=name,
                as_type="agent",
                metadata=metadata,
            )
            span = current.__enter__()
        except BaseException:
            attributes.__exit__(None, None, None)
            raise
        return _Root(attributes, current, span)

    def start(
        self, parent: Any, *, name: str, kind: Kind, metadata: Metadata, model: str | None
    ) -> Any:
        if parent is None:
            return None
        span = parent.span if isinstance(parent, _Root) else parent
        if kind == "generation":
            return span.start_observation(
                name=name, as_type=kind, metadata=metadata, model=model
            )
        return span.start_observation(name=name, as_type=kind, metadata=metadata)

    def update(
        self,
        handle: Any,
        *,
        metadata: Metadata,
        level: Level | None,
        status_message: str | None,
        usage: dict[str, int] | None,
    ) -> None:
        if handle is None:
            return
        span = handle.span if isinstance(handle, _Root) else handle
        values: dict[str, Any] = {"metadata": metadata}
        if level is not None:
            values["level"] = level
        if status_message is not None:
            values["status_message"] = status_message
        if usage:
            values["usage_details"] = usage
        span.update(**values)

    def end(self, handle: Any) -> None:
        if handle is not None:
            handle.end()

    def end_trace(self, handle: Any) -> None:
        if handle is None:
            return
        try:
            handle.current.__exit__(None, None, None)
        finally:
            handle.attributes.__exit__(None, None, None)

    def shutdown(self) -> None:
        self.client.shutdown()


def create_tracer(
    *,
    enabled: bool,
    public_key: str | None,
    secret_key: str | None,
    base_url: str,
    environment: str,
    timeout_seconds: int,
    span_exporter: SpanExporter | None = None,
) -> Tracer:
    """The Langfuse tracer, or tracing off when it is disabled, not configured,
    or cannot start: the coach works the same either way."""
    if not enabled:
        return TRACING_OFF
    if not public_key or not secret_key:
        logger.warning("Langfuse tracing is enabled but its keys are not set; tracing is off")
        return TRACING_OFF
    try:
        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            tracing_enabled=True,
            environment=environment,
            timeout=timeout_seconds,
            tracer_provider=TracerProvider(),
            should_export_span=is_langfuse_span,
            mask=mask,
            span_exporter=span_exporter,
        )
    except Exception as error:  # noqa: BLE001 - observability must not stop the application
        logger.warning("Langfuse could not start (%s); tracing is off", type(error).__name__)
        return TRACING_OFF
    return Tracer(LangfuseBackend(client))
