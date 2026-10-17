"""A coach turn's trajectory, end to end: the API, the service, the real tools
and the test database, with a scripted model.

What a trace and the log say of a turn must come from Formiq's own state, not
the model's word: a proposal is "created" only once it is kept in PostgreSQL
for the user's approval, an approval is an event only once it saved a plan, and
the reads Formiq loads for a proposal are the request's user's, never another's.

They require the local PostgreSQL container to be running. No test calls Gemini
or Langfuse.
"""

import json
import logging

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import AIProviderError
from app.api.dependencies import get_tracer
from app.main import app
from app.models import WorkoutPlanProposal
from tests.auth import bearer
from tests.coach import call, respond_turn, tool_turn
from tests.integration.test_coach_daily import add_plan, add_workout, create_user, received
from tests.integration.test_plan_proposals import (  # noqa: F401 - fixtures of the proposal tests
    approve,
    ask,
    bodyweight,
    clock,
    ids,
    plans_of,
    proposal,
    proposing,
    terms,
    today,
    use_provider,
    use_terms,
    users,
)
from tests.observability import recording


@pytest.fixture(autouse=True)
def trajectory_log(monkeypatch):
    """The trajectory's log is readable: Alembic's fileConfig, run in this process
    by the migration tests, disables the loggers that exist by then."""
    monkeypatch.setattr(logging.getLogger("app.observability.trajectory"), "disabled", False)


@pytest.fixture
def traced():
    """The application's tracer, replaced by one that records in memory."""
    tracer, backend = recording()
    app.dependency_overrides[get_tracer] = lambda: tracer
    try:
        yield backend
    finally:
        app.dependency_overrides.pop(get_tracer, None)


def summaries(caplog):
    return [
        json.loads(record.message.removeprefix("coach_turn_summary "))
        for record in caplog.records
        if record.message.startswith("coach_turn_summary ")
    ]


def events(caplog):
    return [
        json.loads(record.message.removeprefix("coach_event "))
        for record in caplog.records
        if record.message.startswith("coach_event ")
    ]


def kept(test_engine, user_id):
    with Session(test_engine) as session:
        return session.scalar(
            select(func.count()).select_from(WorkoutPlanProposal).where(WorkoutPlanProposal.user_id == user_id)
        )


def test_a_created_proposal_is_one_kept_for_the_users_approval_and_is_then_an_approval_event(
    client, use_provider, users, ids, test_engine, traced, caplog
):
    caplog.set_level(logging.INFO)
    me, _ = users

    body, _ = ask(client, use_provider, me, *proposing(ids))

    shown = body["proposal"]
    (summary,) = summaries(caplog)
    assert summary["proposal"]["outcome"] == "created"
    assert summary["proposal"]["proposal_ref"] == shown["proposal_id"][:8]
    assert summary["proposal"]["complete"] is shown["coverage"]["complete"]
    assert summary["request_completed"] is True and summary["status"] == "success"
    assert kept(test_engine, me) == 1  # one proposal kept, none twice
    # the trace's root carries the same aggregates, with the events as short codes
    root = traced.root.metadata
    assert root["proposal_outcome"] == "created" and root["proposal_attempts"] == 1
    assert root["tool_calls_requested"] == summary["tool_calls"]["requested"]
    assert root["tool_calls_blocked"] == 0 and root["tool_calls_failed"] == 0
    # a user with no plan or workout yet: those reads found none, which is an answer
    assert root["tool_calls_empty"] == 2 and summary["failure_reasons"] == []
    assert root["tokens_source"] == "unavailable"  # a scripted model reports none
    assert any(code.endswith(":prop_created") or ":prop_created:" in code for code in root["trajectory"])
    assert events(caplog) == []  # nothing is approved by being proposed

    assert approve(client, me, shown).status_code == 201
    (approved,) = events(caplog)
    assert approved["type"] == "proposal_approved" and approved["proposal_ref"] == shown["proposal_id"][:8]

    # a second approval is refused, and is no approval event
    assert approve(client, me, shown).status_code == 409
    assert len(events(caplog)) == 1


def test_a_proposal_before_its_reads_is_recovered_and_still_kept_once(
    client, use_provider, users, ids, test_engine, traced, caplog
):
    caplog.set_level(logging.INFO)
    me, _ = users
    workout = bodyweight(ids)
    searches = tool_turn(
        call("get_user_profile"),
        call("search_exercises", movement_pattern="HORIZONTAL_PUSH"),
        call("search_exercises", movement_pattern="LUNGE"),
        call("search_exercises", movement_pattern="HORIZONTAL_PULL"),
        call("search_exercises", movement_pattern="ROTATION"),
        call("search_exercises", movement_pattern="MOBILITY"),
        call("search_exercises", movement_pattern="STRETCH"),
    )
    propose_now = tool_turn(proposal(**workout, max_minutes=30, unavailable_equipment=["Dumbbell"]))

    body, provider = ask(
        client, use_provider, me, searches, propose_now,
        tool_turn(proposal(**workout, max_minutes=30, unavailable_equipment=["Dumbbell"])),
        respond_turn("Here is a short bodyweight workout. Review it, and approve it to save it.", "DAILY_WORKOUT", "RETRIEVE_THEN_ANSWER"),
    )  # fmt: skip

    assert body["proposal"] is not None
    (summary,) = summaries(caplog)
    assert summary["proposal"]["missing_prerequisites"] == 1
    assert summary["tool_calls"]["formiq_loaded"] == 2  # the plan and the last workout
    assert summary["proposal"]["outcome"] == "created"
    assert kept(test_engine, me) == 1


def test_the_reads_formiq_loads_for_a_proposal_are_the_request_users_never_anothers(
    client, use_provider, test_engine, profile_fields, ids
):
    bench = ids["Barbell Bench Press"]
    with Session(test_engine) as session:
        mine = create_user(session, "loaded-me@example.com", {**profile_fields, "first_name": "Mine"})
        theirs = create_user(
            session, "loaded-them@example.com", {**profile_fields, "first_name": "THEIRS-NAME"}
        )
        add_plan(session, theirs, 0, (bench, 5, 5, 100.0), name="THEIR-PLAN")
        add_workout(session, theirs, -1, bench, [(5, 100.0, 9.0, True)])
    workout = bodyweight(ids)

    # the model reads nothing: Formiq loads all three for the proposal, for the request's user
    _, provider = ask(
        client, use_provider, mine,
        tool_turn(call("search_exercises", movement_pattern="HORIZONTAL_PUSH")),
        tool_turn(proposal(**workout)),
        respond_turn("I could not build it.", "DAILY_WORKOUT", "CANNOT_ANSWER"),
    )  # fmt: skip

    refusal = received(provider, 2)["propose_workout_plan"]["error"]
    loaded = {item["tool"]: item["result"] for item in refusal["loaded"]}
    assert list(loaded) == ["get_user_profile", "get_current_workout_plan", "get_latest_workout_session"]
    # the profile is the signed-in user's own; the plan and workout the other user has are
    # missing for this one, as if they did not exist
    assert loaded["get_user_profile"]["output"]["user_id"] == mine
    assert loaded["get_user_profile"]["output"]["profile"]["first_name"] == "Mine"
    assert loaded["get_current_workout_plan"]["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert loaded["get_latest_workout_session"]["error"]["code"] == "RESOURCE_NOT_FOUND"
    everything = json.dumps(refusal)
    assert "THEIRS-NAME" not in everything and "THEIR-PLAN" not in everything


def test_a_proposal_accepted_in_a_turn_that_does_not_answer_is_discarded_not_kept(
    client, use_provider, users, ids, test_engine, traced, caplog
):
    caplog.set_level(logging.INFO)
    me, _ = users
    turns = list(proposing(ids))
    turns[-1] = respond_turn("I am not sure that suits you.", "DAILY_WORKOUT", "ASK_CLARIFICATION")

    body, _ = ask(client, use_provider, me, *turns)

    assert "proposal" not in body
    (summary,) = summaries(caplog)
    assert summary["proposal"]["outcome"] == "discarded"
    assert kept(test_engine, me) == 0 and plans_of(test_engine, me) == []


def test_the_proposal_awaiting_approval_shown_again_is_not_a_new_proposal(
    client, use_provider, users, ids, test_engine, traced, caplog
):
    me, _ = users
    body, _ = ask(client, use_provider, me, *proposing(ids))
    pending = body["proposal"]
    caplog.set_level(logging.INFO)
    caplog.clear()

    again, _ = ask(
        client, use_provider, me,
        tool_turn(call("get_pending_proposal")),
        respond_turn("The proposal is below: review it and approve it in Formiq.", "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
    )  # fmt: skip

    assert again["proposal"]["proposal_id"] == pending["proposal_id"]
    (summary,) = summaries(caplog)
    assert summary["proposal"]["outcome"] == "shown_pending"
    assert summary["model_requests"] == 2  # the read, then the answer: no wasted request
    assert kept(test_engine, me) == 1


def test_a_provider_failure_ends_the_trace_with_its_category(
    client, use_provider, users, traced, caplog
):
    caplog.set_level(logging.INFO)
    me, _ = users
    provider = use_provider(tool_turn(call("get_user_profile")))
    provider.generate_turn.side_effect = [tool_turn(call("get_user_profile")), AIProviderError("down")]

    response = client.post("/coach/message", headers=bearer(me), json={"message": "What is my goal?"})

    assert response.status_code == 502
    (summary,) = summaries(caplog)
    assert summary["status"] == "provider_error" and summary["request_completed"] is False
    assert "provider_error" in summary["failure_reasons"]
    assert traced.root.metadata["status"] == "provider_error"
    assert "down" not in json.dumps(summary)  # the error's own text is never recorded


# --- the real Gemini SDK types, and the real Langfuse export ---


def langfuse_value(span, key):
    value = span.attributes[f"langfuse.observation.metadata.{key}"]
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def test_langfuse_receives_the_providers_usage_and_the_turns_aggregates(
    service_session, profile_fields
):
    import uuid
    from unittest.mock import patch

    from google.genai import types
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from app.ai import GeminiProvider
    from app.observability.langfuse_backend import create_tracer
    from app.services import CoachService

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
    user_id = create_user(service_session, "usage@example.com", profile_fields)

    def response(part, usage, served):
        return types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))],
            usage_metadata=types.GenerateContentResponseUsageMetadata(**usage),
            model_version=served,
        )

    with patch("app.ai.gemini.genai.Client") as client_class:
        client_class.return_value.models.generate_content.side_effect = [
            response(
                types.Part(function_call=types.FunctionCall(name="get_user_profile", args={})),
                dict(prompt_token_count=800, cached_content_token_count=300,
                     candidates_token_count=20, thoughts_token_count=100, total_token_count=920),
                "gemini-served-001",
            ),
            response(
                types.Part(
                    function_call=types.FunctionCall(
                        name="respond",
                        args={"intent": "PROFILE", "decision": "RETRIEVE_THEN_ANSWER",
                              "reply": "Your goal is muscle gain."},
                    )
                ),
                dict(prompt_token_count=900, candidates_token_count=30, total_token_count=930),
                "gemini-served-001",
            ),
        ]  # fmt: skip
        provider = GeminiProvider("API_KEY_CANARY", "gemini-asked", timeout_seconds=30)

        answer = CoachService(service_session, provider, tracer).answer(user_id, "What is my goal?")

    tracer.backend.client.flush()
    assert answer.reply == "Your goal is muscle gain."
    sent = exporter.get_finished_spans()
    root = next(span for span in sent if span.name == "coach_request")
    assert langfuse_value(root, "tokens_total") == 920 + 930
    assert langfuse_value(root, "tokens_input") == 1700 and langfuse_value(root, "tokens_cached_input") == 300
    assert langfuse_value(root, "tokens_source") == "provider_reported"
    assert langfuse_value(root, "model") == "gemini-asked"
    assert langfuse_value(root, "models_reported") == ["gemini-served-001"]
    assert langfuse_value(root, "tool_calls_requested") == 1 and langfuse_value(root, "tool_calls_blocked") == 0
    assert langfuse_value(root, "request_completed") is True
    assert langfuse_value(root, "trajectory")[0].endswith("start")
    # each request's usage, as Langfuse prices it: the cached part taken out of the input
    usages = [
        json.loads(span.attributes["langfuse.observation.usage_details"])
        for span in sent
        if span.name == "model_request"
    ]
    assert usages[0]["input"] == 500 and usages[0]["input_cached_tokens"] == 300
    assert usages[0]["output"] == 20 and usages[0]["output_reasoning_tokens"] == 100
    assert usages[1]["total"] == 930
    assert "API_KEY_CANARY" not in json.dumps([dict(span.attributes) for span in sent], default=str)
    tracer.backend.client.flush()
