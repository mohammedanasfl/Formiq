"""Integration tests for tracing coach requests: one trace per request through
CoachService and the API, its final status, the real Langfuse SDK's exported
spans, and that tracing never changes a request.

They require the local PostgreSQL container to be running. The model is a fake,
or a real GeminiProvider whose SDK client is a mock; Langfuse exports to memory
or to a closed local port. No test calls Gemini or Langfuse.
"""

import json
import logging
import time
import uuid
from unittest.mock import patch

import httpx
import pytest
from google.genai import errors
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from app.agent import SAFETY_POLICY, ConversationTurn, SafetyCategory
from app.ai import AIProviderError, GeminiProvider
from app.api import dependencies
from app.api.dependencies import get_ai_provider, get_tracer
from app.core.config import Settings
from app.main import app
from app.observability import TRACING_OFF, Tracer
from app.observability.langfuse_backend import create_tracer, mask
from app.schemas import UserCreate, UserProfileCreate, WorkoutPlanCreate
from app.services import (
    CoachService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
)
from tests.auth import bearer
from tests.coach import call, fake_provider, respond_turn, tool_turn
from tests.observability import FailingBackend, recording

API_KEY = "API_KEY_CANARY"
CANARIES = (
    "SECRET_SYSTEM_PROMPT_CANARY",
    "CHAIN_OF_THOUGHT_CANARY",
    "USER_PROFILE_PRIVATE_CANARY",
    "WORKOUT_HISTORY_PRIVATE_CANARY",
    "USER_MESSAGE_CANARY",
    API_KEY,
)


@pytest.fixture
def user(service_session, profile_fields):
    user = UserService(service_session).create_user(UserCreate(email="traced@example.com"))
    UserProfileService(service_session).create_profile(
        user.id,
        UserProfileCreate(
            **{
                **profile_fields,
                "first_name": "USER_PROFILE_PRIVATE_CANARY",
                # returned by get_user_profile, so it reaches the model's request
                "dietary_preference": "USER_PROFILE_PRIVATE_CANARY",
                "goal": "muscle_gain",
            }
        ),
    )
    return user


@pytest.fixture
def plan(service_session, user):
    return WorkoutPlanService(service_session).create_plan(
        user.id, WorkoutPlanCreate(name="WORKOUT_HISTORY_PRIVATE_CANARY")
    )


def reply(service_session, user, provider, tracer, message="What is my goal?", history=()):
    return CoachService(service_session, provider, tracer).reply(user.id, message, history)


def profile_turns():
    return (
        tool_turn(call("get_user_profile")),
        respond_turn("Your goal is muscle gain.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
    )


# one trace per request, with its outcome


def test_a_request_is_one_trace_ending_with_its_status(service_session, user):
    tracer, backend = recording()

    answer = reply(service_session, user, fake_provider(*profile_turns()), tracer)

    assert answer == "Your goal is muscle gain."
    root = backend.root
    assert root.name == "coach_request"
    assert root.metadata["user_id"] == str(user.id)
    assert len(root.metadata["request_id"]) == 32
    assert root.status_message == "success" and root.level is None
    assert root.metadata | {"request_id": None} == root.metadata | {
        "status": "success",
        "intent": "PROFILE",
        "decision": "RETRIEVE_THEN_ANSWER",
        "safety_category": "SAFE",
        "tools_used": ["get_user_profile"],
        "termination": "decision_accepted",
        "model_requests": 2,
        "tool_calls_requested": 1,
        "tool_calls_executed": 1,
        "iterations": 1,
        "compactions": 0,
        "request_id": None,
    }
    assert all(node.ended for node in backend.nodes)


def test_each_request_has_its_own_trace_and_id(service_session, user):
    ids = []
    for _ in range(2):
        tracer, backend = recording()
        reply(service_session, user, fake_provider(respond_turn("Hi.")), tracer)
        ids.append(backend.root.metadata["request_id"])

    assert ids[0] != ids[1]


def test_the_request_id_is_in_the_log_and_the_trace(service_session, user, caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("app.services.coach_service"), "disabled", False)
    tracer, backend = recording()

    with caplog.at_level(logging.INFO, logger="app.services.coach_service"):
        reply(service_session, user, fake_provider(respond_turn("Hi.")), tracer)

    request_id = backend.root.metadata["request_id"]
    assert f"Coach request {request_id} ended: status=success" in caplog.text


@pytest.mark.parametrize(
    ("message", "turns", "status", "level"),
    [
        ("Overload?", [respond_turn("Add load.")], "success", None),
        ("Make it harder.", [respond_turn("How?", "AMBIGUOUS", "ASK_CLARIFICATION")], "clarification", None),
        ("What is my goal?", [respond_turn("No.", "PROFILE", "CANNOT_ANSWER")], "cannot_answer", "WARNING"),
        (
            "I have sharp knee pain.",
            [respond_turn("See a physio.", "SAFETY_SENSITIVE", "SAFE_REDIRECT")],
            "safety_redirect",
            "WARNING",
        ),
        (
            "I have sharp knee pain.",
            [respond_turn("Push through.", "GENERAL_FITNESS", "ANSWER")],
            "safety_redirect",
            "WARNING",
        ),
    ],
    ids=["answer", "question", "cannot answer", "model redirect", "fixed safe reply"],
)
def test_the_status_follows_the_validated_outcome(service_session, user, message, turns, status, level):
    tracer, backend = recording()

    reply(service_session, user, fake_provider(*turns), tracer, message)

    assert (backend.root.metadata["status"], backend.root.level) == (status, level)


def test_a_fixed_safe_reply_is_never_traced_as_a_model_success(service_session, user):
    tracer, backend = recording()

    answer = reply(
        service_session,
        user,
        fake_provider(respond_turn("Push through.", "GENERAL_FITNESS", "ANSWER")),
        tracer,
        "I have sharp knee pain.",
    )

    assert answer == SAFETY_POLICY[SafetyCategory.PAIN_OR_INJURY].fallback_reply
    root = backend.root.metadata
    assert root["status"] == "safety_redirect"
    assert root["safety_path"] == "fixed_safe_response"
    assert root["decision"] == "SAFE_REDIRECT"


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (httpx.ReadTimeout("timed out"), "provider_timeout"),
        (errors.ServerError(504, {"error": {"code": 504, "message": "X", "status": "X"}}), "provider_timeout"),
        (errors.ClientError(429, {"error": {"code": 429, "message": "X", "status": "X"}}), "rate_limit"),
        (errors.ServerError(503, {"error": {"code": 503, "message": "X", "status": "X"}}), "provider_error"),
        (ConnectionError("reset"), "provider_error"),
    ],
    ids=["timeout", "504", "rate limit", "503", "network"],
)
def test_a_provider_failure_ends_the_trace_with_its_category(service_session, user, failure, status):
    tracer, backend = recording()
    with patch("app.ai.gemini.genai.Client") as client_class:
        client_class.return_value.models.generate_content.side_effect = failure
        provider = GeminiProvider(API_KEY, "gemini-3.8-flash", timeout_seconds=30)

        with pytest.raises(AIProviderError):
            reply(service_session, user, provider, tracer, "Overload?")

    assert (backend.root.metadata["status"], backend.root.level) == (status, "ERROR")
    (generation,) = backend.named("model_request")
    assert generation.model == "gemini-3.8-flash"
    assert generation.status_message == status
    assert API_KEY not in backend.everything()


def test_an_unconfigured_provider_and_an_unknown_user_are_traced(service_session, user):
    tracer, backend = recording()
    with pytest.raises(AIProviderError):
        reply(service_session, user, GeminiProvider(None, "gemini-3.8-flash", timeout_seconds=30), tracer)
    assert backend.root.metadata["status"] == "provider_not_configured"

    tracer, backend = recording()
    with pytest.raises(Exception, match="does not exist"):
        CoachService(service_session, fake_provider(), tracer).reply(2_147_483_647, "Hi")
    assert backend.root.metadata["status"] == "user_not_found"


# the real Langfuse SDK


@pytest.fixture
def exported():
    """A Langfuse tracer that exports to memory, as it would to Langfuse. Its own
    public key: the SDK shares one client, and its exporter, per key."""
    exporter = InMemorySpanExporter()
    tracer = create_tracer(
        enabled=True,
        public_key=f"pk-lf-{uuid.uuid4().hex}",
        secret_key="sk-lf-test",
        base_url="http://127.0.0.1:9",
        environment="test",
        timeout_seconds=1,
        span_exporter=exporter,
    )
    assert tracer.enabled
    yield tracer, exporter
    tracer.backend.client.flush()


def spans(tracer, exporter):
    tracer.backend.client.flush()
    return exporter.get_finished_spans()


def test_langfuse_receives_the_trajectory_as_one_trace(service_session, user, exported):
    tracer, exporter = exported

    reply(service_session, user, fake_provider(*profile_turns()), tracer)

    sent = spans(tracer, exporter)
    by_name = {span.name: span for span in sent}
    assert {"coach_request", "safety_check", "model_turn", "model_request", "tool_calls", "get_user_profile"} <= set(by_name)
    root = by_name["coach_request"]
    assert {span.context.trace_id for span in sent} == {root.context.trace_id}
    request_id = root.attributes["langfuse.observation.metadata.request_id"]
    assert f"{root.context.trace_id:032x}" == Langfuse.create_trace_id(seed=request_id)
    assert by_name["model_request"].attributes["langfuse.observation.type"] == "generation"
    assert by_name["get_user_profile"].attributes["langfuse.observation.type"] == "tool"
    assert by_name["get_user_profile"].parent.span_id == by_name["tool_calls"].context.span_id
    for span in sent:
        assert span.attributes["user.id"] == str(user.id)
        assert span.attributes["langfuse.trace.name"] == "coach_request"
    assert root.attributes["langfuse.observation.metadata.status"] == "success"


def test_nothing_private_reaches_langfuse(service_session, user, plan, exported, monkeypatch):
    from app.agent import graph

    tracer, exporter = exported
    monkeypatch.setattr(
        graph, "COACH_INSTRUCTIONS", graph.COACH_INSTRUCTIONS + " SECRET_SYSTEM_PROMPT_CANARY"
    )
    with patch("app.ai.gemini.genai.Client") as client_class:
        from google.genai import types

        def response(*parts):
            return types.GenerateContentResponse(
                candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))]
            )

        client_class.return_value.models.generate_content.side_effect = [
            response(
                types.Part(text="CHAIN_OF_THOUGHT_CANARY", thought=True),
                types.Part(function_call=types.FunctionCall(name="get_user_profile", args={})),
                types.Part(
                    function_call=types.FunctionCall(
                        name="get_workout_plan", args={"plan_id": plan.id}
                    )
                ),
            ),
            response(
                types.Part(
                    function_call=types.FunctionCall(
                        name="respond",
                        args={
                            "intent": "ADAPTATION",
                            "decision": "RETRIEVE_THEN_ANSWER",
                            "reply": "Your plan suits you.",
                        },
                    )
                )
            ),
        ]
        provider = GeminiProvider(API_KEY, "gemini-3.8-flash", timeout_seconds=30)

        answer = reply(
            service_session,
            user,
            provider,
            tracer,
            f"USER_MESSAGE_CANARY: does plan {plan.id} suit me?",
            [],
        )

    assert answer == "Your plan suits you."
    exported_spans = spans(tracer, exporter)
    # the whole request was exported, so the checks below look at it
    assert {"coach_request", "model_request", "get_user_profile"} <= {
        span.name for span in exported_spans
    }
    sent = json.dumps(
        [{"name": span.name, **dict(span.attributes)} for span in exported_spans],
        default=str,
    )
    for canary in CANARIES:
        assert canary not in sent
    assert "muscle_gain" not in sent
    assert "Your plan suits you" not in sent
    assert "langfuse.observation.input" not in sent
    assert "langfuse.observation.output" not in sent


def test_langfuse_receives_gemini_token_counts_as_the_usage_types_it_prices(
    service_session, user, exported
):
    tracer, exporter = exported
    with patch("app.ai.gemini.genai.Client") as client_class:
        from google.genai import types

        def response(name, args, **usage):
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            role="model",
                            parts=[
                                types.Part(
                                    function_call=types.FunctionCall(name=name, args=args)
                                )
                            ],
                        )
                    )
                ],
                usage_metadata=types.GenerateContentResponseUsageMetadata(**usage),
            )

        client_class.return_value.models.generate_content.side_effect = [
            # Gemini's input includes its cached part; its output excludes the thinking
            response(
                "get_user_profile",
                {},
                prompt_token_count=5000,
                cached_content_token_count=4000,
                candidates_token_count=20,
                thoughts_token_count=80,
                total_token_count=5100,
            ),
            response(
                "respond",
                {
                    "intent": "PROFILE",
                    "decision": "RETRIEVE_THEN_ANSWER",
                    "reply": "Your goal is muscle gain.",
                },
                prompt_token_count=5300,
                candidates_token_count=40,
                total_token_count=5340,
            ),
        ]
        provider = GeminiProvider(API_KEY, "gemini-3.8-flash", timeout_seconds=30)

        assert reply(service_session, user, provider, tracer) == "Your goal is muscle gain."

    generations = [span for span in spans(tracer, exporter) if span.name == "model_request"]
    # each token in one usage type, so Langfuse's total and cost count it once
    assert [
        json.loads(span.attributes["langfuse.observation.usage_details"]) for span in generations
    ] == [
        {
            "input": 1000,
            "input_cached_tokens": 4000,
            "output": 20,
            "output_reasoning_tokens": 80,
            "total": 5100,
        },
        {"input": 5300, "output": 40, "total": 5340},
    ]
    assert {span.attributes["langfuse.observation.model.name"] for span in generations} == {
        "gemini-3.8-flash"
    }


def test_with_content_captured_langfuse_receives_the_conversation(service_session, user):
    exporter = InMemorySpanExporter()
    tracer = create_tracer(
        enabled=True,
        public_key=f"pk-lf-{uuid.uuid4().hex}",
        secret_key="sk-lf-test",
        base_url="http://127.0.0.1:9",
        environment="test",
        timeout_seconds=1,
        capture_content=True,
        span_exporter=exporter,
    )
    history = [ConversationTurn("user", "Hi"), ConversationTurn("coach", "Hello!")]

    answer = reply(
        service_session, user, fake_provider(*profile_turns()), tracer, "My goal?", history
    )

    assert answer == "Your goal is muscle gain."
    by_name = {span.name: span.attributes for span in spans(tracer, exporter)}
    # the trace's input and output: the conversation, then the reply
    assert json.loads(by_name["coach_request"]["langfuse.observation.input"]) == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "My goal?"},
    ]
    assert json.loads(by_name["coach_request"]["langfuse.observation.output"]) == {
        "role": "assistant",
        "content": "Your goal is muscle gain.",
    }
    # the data the tools read, and what each model request was sent
    assert "muscle_gain" in by_name["get_user_profile"]["langfuse.observation.output"]
    assert "muscle_gain" in by_name["model_request"]["langfuse.observation.input"]
    # the metadata stays as safe as without content
    assert by_name["coach_request"]["langfuse.observation.metadata.status"] == "success"


# content capture is for development and the tests only

SECRETS = {
    "gemini_api_key": "GEMINI_KEY_CANARY",
    "langfuse_secret_key": "sk-lf-SECRET_KEY_CANARY",
    "auth_jwt_secret": "JWT_SECRET_CANARY_" + "x" * 32,
}


def configured(**values):
    """Settings as the application loads them, with Langfuse configured and
    secrets set."""
    return Settings(
        _env_file=None,
        **{
            "database_url": "postgresql+psycopg://formiq:DB_PASSWORD_CANARY@localhost/formiq",
            "langfuse_tracing_enabled": True,
            "langfuse_public_key": "pk-lf-public",
            **SECRETS,
            **values,
        },
    )


@pytest.fixture
def tracer_of(monkeypatch):
    """The tracer the application builds from these settings (get_tracer), and
    the Langfuse client's mock, which holds what it was started with."""

    def build(settings):
        monkeypatch.setattr(dependencies, "settings", settings)
        get_tracer.cache_clear()
        with patch("app.observability.langfuse_backend.Langfuse") as client:
            return get_tracer(), client

    yield build
    get_tracer.cache_clear()


@pytest.mark.parametrize("app_env", ["production", "Production", "prod", "staging"])
def test_production_settings_refuse_content_capture(app_env):
    """Not turned off quietly: the settings do not load, so the application does
    not start. Any environment but development and the tests counts as
    production. The error names no other setting's value."""
    with pytest.raises(ValidationError) as refused:
        configured(app_env=app_env, langfuse_capture_content=True)

    assert [error["loc"] for error in refused.value.errors()] == [("langfuse_capture_content",)]
    message = str(refused.value)
    assert (
        "LANGFUSE_CAPTURE_CONTENT sends the users' conversations and data to Langfuse, so it "
        f"is for development only, not APP_ENV={app_env!r}"
    ) in message
    assert [value for value in [*SECRETS.values(), "DB_PASSWORD_CANARY"] if value in message] == []


def test_production_traces_metadata_only(tracer_of):
    tracer, client = tracer_of(configured(app_env="production"))

    assert tracer.enabled and not tracer.capture_content
    # the privacy mask applies to whatever the SDK sends
    assert client.call_args.kwargs["mask"] is mask
    assert client.call_args.kwargs["environment"] == "production"


@pytest.mark.parametrize("app_env", ["development", "test"])
def test_development_captures_content_only_when_configured_to(tracer_of, app_env):
    tracer, client = tracer_of(configured(app_env=app_env))
    assert not tracer.capture_content
    assert client.call_args.kwargs["mask"] is mask

    tracer, client = tracer_of(configured(app_env=app_env, langfuse_capture_content=True))
    assert tracer.capture_content
    assert client.call_args.kwargs["mask"] is None


@pytest.mark.parametrize("enabled", [True, False])
def test_production_settings_changed_after_loading_still_capture_nothing(monkeypatch, enabled):
    """Settings changed once loaded are not validated again: the application
    still refuses to build a tracer that captures content in production, so
    Langfuse never starts there without the privacy mask."""
    changed = configured(app_env="production", langfuse_tracing_enabled=enabled).model_copy(
        update={"langfuse_capture_content": True}
    )
    monkeypatch.setattr(dependencies, "settings", changed)
    get_tracer.cache_clear()
    try:
        with (
            patch("app.observability.langfuse_backend.Langfuse") as client,
            pytest.raises(ValueError, match="for development only, not APP_ENV='production'"),
        ):
            get_tracer()
    finally:
        get_tracer.cache_clear()

    client.assert_not_called()


# tracing never changes the request


def test_tracing_is_off_unless_enabled_and_configured(tracer_of, monkeypatch):
    """The application's tracer, from settings this test gives: whatever the
    developer's .env or environment configures does not decide it."""
    for name in ("LANGFUSE_TRACING_ENABLED", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    unset = Settings(_env_file=None, database_url=configured().database_url)
    for settings in (
        unset,
        configured(langfuse_tracing_enabled=False),
        configured(langfuse_secret_key=None),
        configured(langfuse_public_key=None),
    ):
        tracer, client = tracer_of(settings)
        assert tracer is TRACING_OFF
        client.assert_not_called()

    off = {
        "public_key": "pk",
        "secret_key": "sk",
        "base_url": "http://127.0.0.1:9",
        "environment": "test",
        "timeout_seconds": 1,
    }
    assert create_tracer(enabled=False, **off) is TRACING_OFF
    assert create_tracer(enabled=True, **{**off, "secret_key": None}) is TRACING_OFF


def test_the_tests_send_no_trace_unless_they_say_so(client, user, use):
    """backend/.env may enable Langfuse for development: the tests' shared
    configuration (tests/conftest.py) turns the application's tracer off, so a
    request through the API starts no Langfuse client and sends nothing."""
    get_tracer.cache_clear()
    use(get_ai_provider, fake_provider(*profile_turns()))
    with patch("app.observability.langfuse_backend.Langfuse") as langfuse:
        response = client.post(
            "/coach/message", headers=bearer(user.id), json={"message": "What is my goal?"}
        )

    assert response.status_code == 200
    assert get_tracer() is TRACING_OFF
    langfuse.assert_not_called()


def test_langfuse_failing_to_start_leaves_tracing_off(caplog, monkeypatch):
    # Alembic's logging setup disables existing loggers once the migrations ran
    monkeypatch.setattr(logging.getLogger("app.observability.langfuse_backend"), "disabled", False)
    with (
        caplog.at_level(logging.WARNING, logger="app.observability.langfuse_backend"),
        patch("app.observability.langfuse_backend.Langfuse", side_effect=RuntimeError(API_KEY)),
    ):
        tracer = create_tracer(
            enabled=True, public_key="pk", secret_key="sk", base_url="http://x", environment="t", timeout_seconds=1
        )

    assert tracer is TRACING_OFF
    assert "Langfuse could not start (RuntimeError); tracing is off" in caplog.text
    assert API_KEY not in caplog.text


@pytest.fixture
def use(client):
    def override(dependency, value):
        app.dependency_overrides[dependency] = lambda: value

    try:
        yield override
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("error", [RuntimeError, TimeoutError, ConnectionError])
def test_a_failing_tracer_never_changes_the_api_response(client, user, use, error):
    message = {"message": "What is my goal?"}
    use(get_ai_provider, fake_provider(*profile_turns()))
    use(get_tracer, TRACING_OFF)
    expected = client.post("/coach/message", headers=bearer(user.id), json=message)

    use(get_ai_provider, fake_provider(*profile_turns()))
    use(get_tracer, Tracer(FailingBackend(error)))
    response = client.post("/coach/message", headers=bearer(user.id), json=message)

    assert (response.status_code, response.json()) == (expected.status_code, expected.json())
    assert response.json() == {"reply": "Your goal is muscle gain."}


def test_a_failing_tracer_never_changes_an_error_response(client, user, use):
    use(get_tracer, Tracer(FailingBackend()))
    provider = fake_provider()
    provider.generate_turn.side_effect = AIProviderError("failed")
    use(get_ai_provider, provider)

    response = client.post("/coach/message", headers=bearer(user.id), json={"message": "Hi"})

    assert response.status_code == 502


def test_an_unreachable_langfuse_does_not_slow_the_request(service_session, user):
    # the real SDK exporting over HTTP to a closed local port, in the background
    tracer = create_tracer(
        enabled=True,
        public_key=f"pk-lf-{uuid.uuid4().hex}",
        secret_key="sk-lf-test",
        base_url="http://127.0.0.1:9",
        environment="test",
        timeout_seconds=1,
    )
    untraced_start = time.perf_counter()
    reply(service_session, user, fake_provider(*profile_turns()), TRACING_OFF)
    untraced = time.perf_counter() - untraced_start

    start = time.perf_counter()
    answer = reply(service_session, user, fake_provider(*profile_turns()), tracer)
    traced = time.perf_counter() - start

    assert answer == "Your goal is muscle gain."
    # no request waits on the export; the bound is generous for slow machines
    assert traced < untraced + 0.5
    tracer.backend.client.shutdown()
