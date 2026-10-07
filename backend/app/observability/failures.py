"""Failure categories: what went wrong, as a name a trace can record, never the
exception's message (which can hold provider internals)."""

from enum import StrEnum

import httpx
from google.genai import errors as genai_errors
from langgraph.errors import GraphRecursionError

from app.ai import AIModelOutputError, AIProviderError, AIProviderNotConfiguredError


class Failure(StrEnum):
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_ERROR = "provider_error"
    RATE_LIMIT = "rate_limit"
    MODEL_OUTPUT_INVALID = "model_output_invalid"
    TOOL_ERROR = "tool_error"
    TOOL_VALIDATION_ERROR = "tool_validation_error"
    # the resource does not exist for this user: missing, or another user's
    # (Formiq does not tell them apart)
    OWNERSHIP_FAILURE = "ownership_failure"
    TOOL_LIMIT_REACHED = "tool_limit_reached"
    ID_NOT_GROUNDED = "id_not_grounded"
    DECISION_REJECTED = "decision_rejected"
    REPLY_REJECTED = "reply_rejected"
    SAFETY_REDIRECT = "safety_redirect"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    COMPACTION_LIMIT_EXCEEDED = "compaction_limit_exceeded"
    GRAPH_LIMIT_EXCEEDED = "graph_limit_exceeded"
    USER_NOT_FOUND = "user_not_found"
    UNKNOWN_ERROR = "unknown_error"


# the error codes of tool results (app.tools, and the graph's own)
TOOL_ERROR_CODES = {
    "USER_NOT_FOUND": Failure.OWNERSHIP_FAILURE,
    "PROFILE_NOT_FOUND": Failure.OWNERSHIP_FAILURE,
    "RESOURCE_NOT_FOUND": Failure.OWNERSHIP_FAILURE,
    "INVALID_INPUT": Failure.TOOL_VALIDATION_ERROR,
    "UNKNOWN_TOOL": Failure.TOOL_VALIDATION_ERROR,
    "TOOL_LIMIT_REACHED": Failure.TOOL_LIMIT_REACHED,
    "TOOL_ERROR": Failure.TOOL_ERROR,
    "ID_NOT_GROUNDED": Failure.ID_NOT_GROUNDED,
    "DECISION_REJECTED": Failure.DECISION_REJECTED,
}


def tool_failure(code: object) -> Failure:
    return TOOL_ERROR_CODES.get(code, Failure.TOOL_ERROR) if isinstance(code, str) else Failure.TOOL_ERROR


def classify(error: BaseException) -> Failure:
    """The failure an exception stands for."""
    if isinstance(error, AIProviderNotConfiguredError):
        return Failure.PROVIDER_NOT_CONFIGURED
    if isinstance(error, AIModelOutputError):
        return Failure.MODEL_OUTPUT_INVALID
    if isinstance(error, AIProviderError):
        return _provider_cause(error.__cause__)
    if isinstance(error, GraphRecursionError):
        return Failure.GRAPH_LIMIT_EXCEEDED
    return Failure.UNKNOWN_ERROR


def _provider_cause(cause: BaseException | None) -> Failure:
    """What made the provider's request fail, from the exception it wraps."""
    if isinstance(cause, httpx.TimeoutException | TimeoutError):
        return Failure.PROVIDER_TIMEOUT
    if isinstance(cause, genai_errors.APIError):
        if cause.code == 429:
            return Failure.RATE_LIMIT
        if cause.code == 504:
            return Failure.PROVIDER_TIMEOUT
    return Failure.PROVIDER_ERROR
