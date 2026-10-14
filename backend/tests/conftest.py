"""Configuration shared by every backend test."""

import pytest

from tests.observability import application_tracing_off


@pytest.fixture(scope="session", autouse=True)
def tracing_off():
    """No test sends a trace to Langfuse unless it says so: the application's
    tracer is off for the whole run (tests.observability)."""
    with application_tracing_off():
        yield
