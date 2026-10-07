"""AI provider errors. The API layer translates them into HTTP responses without
their details, which can hold provider internals."""


class AIProviderError(Exception):
    """The model could not answer: the request failed or returned no text."""


class AIProviderNotConfiguredError(AIProviderError):
    """No API key is configured, so the model cannot be called."""


class AIModelOutputError(AIProviderError):
    """The model answered, but not as the request required: no text, no tool
    call, or tool calls the turn does not allow."""
