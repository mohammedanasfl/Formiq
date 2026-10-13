"""An opt-in live smoke test of the configured test model (GEMINI_TEST_MODEL)
through Formiq's own provider and coach. It is skipped unless asked for:

    LIVE_GEMINI_SMOKE=1 pytest tests/integration/test_gemini_live.py -s

It needs GEMINI_API_KEY and GEMINI_TEST_MODEL, and uses that model only: it
never falls back to GEMINI_MODEL or any other model. It calls Gemini (a few
requests, which use quota), and requires the local PostgreSQL container to be
running. What it checks is what Formiq enforces in code; the deterministic
tests prove the rest with scripted models.

A live request the provider could not serve (rate limit, timeout, an error) is
reported as unavailable, never as a pass.
"""

import os

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import RESPOND, Intent
from app.agent.policy import Respond
from app.ai import AIProviderError, GeminiProvider
from app.ai.gemini import conversation
from app.api.dependencies import PROPOSAL_TTL, utc_now
from app.approvals import ProposalTerms
from app.core.config import settings
from app.models import Exercise, WorkoutPlan, WorkoutPlanProposal
from app.observability import Tracer
from app.observability.memory import MemoryBackend
from app.services import CoachService
from tests.integration.test_coach_daily import create_user

LIVE = os.environ.get("LIVE_GEMINI_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not LIVE, reason="the live Gemini smoke test is opt-in: set LIVE_GEMINI_SMOKE=1"
)


@pytest.fixture(scope="module")
def provider():
    if settings.gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY is not set")
    if not settings.gemini_test_model:
        pytest.skip("GEMINI_TEST_MODEL is not set; the smoke test uses no other model")
    model = settings.gemini_test_model
    print(f"\nlive model: {model}")
    return GeminiProvider(
        settings.gemini_api_key.get_secret_value(),
        model,
        timeout_seconds=settings.gemini_timeout_seconds,
    )


def unavailable(error: AIProviderError):
    pytest.fail(f"the provider could not serve the live request: {error.__cause__!r}")


def test_the_model_answers_through_formiqs_provider(provider):
    try:
        reply = provider.generate("Reply with the single word: ready", instructions="Be brief.")
    except AIProviderError as error:
        unavailable(error)

    assert reply.strip()


def test_the_model_makes_a_valid_respond_call_when_one_is_required(provider):
    try:
        turn = provider.generate_turn(
            conversation("How many rest days a week suit a beginner?", []),
            instructions=(
                "You are a fitness coach. Answer with the respond tool: intent "
                "GENERAL_FITNESS, decision ANSWER, and a one-sentence reply."
            ),
            tools=[RESPOND],
            required_tool_names=[RESPOND.name],
        )
    except AIProviderError as error:
        unavailable(error)

    (call,) = turn.tool_calls
    assert call.name == RESPOND.name
    # the arguments pass the same strict schema the graph checks them with
    decision = Respond.model_validate(call.arguments)
    assert decision.intent is Intent.GENERAL_FITNESS
    assert decision.reply.strip()


def test_the_coach_reads_before_it_recommends_and_any_proposal_is_valid(
    provider, service_session, profile_fields, test_engine
):
    user_id = create_user(service_session, "live-smoke@example.com", profile_fields)
    backend = MemoryBackend()

    try:
        answer = CoachService(
            service_session,
            provider,
            Tracer(backend),
            ProposalTerms(clock=utc_now, ttl=PROPOSAL_TTL),
        ).answer(user_id, "What should I do today? I have 30 minutes and no equipment.")
    except AIProviderError as error:
        unavailable(error)

    root = backend.nodes[0].metadata
    print(
        f"status={root.get('status')} decision={root.get('decision')} "
        f"tools={root.get('tools_used')} model_requests={root.get('model_requests')} "
        f"proposal={answer.proposal is not None}"
    )
    assert answer.reply.strip()
    assert root["status"] in {"success", "clarification", "cannot_answer"}
    with Session(test_engine) as session:
        # the coach saves no plan, whatever it proposed
        assert (
            session.scalars(select(WorkoutPlan).where(WorkoutPlan.user_id == user_id)).all() == []
        )
        stored = session.scalars(
            select(WorkoutPlanProposal).where(WorkoutPlanProposal.user_id == user_id)
        ).all()
        if answer.proposal is None:
            assert stored == []
            return
        # a proposal is only made after the day's reads, from catalog exercises
        # that suit their section and need no equipment, and is kept PENDING
        assert {"get_user_profile", "get_current_workout_plan"} <= set(root["tools_used"])
        proposal, shown = answer.proposal
        assert [(row.proposal_id, row.status) for row in stored] == [
            (proposal.proposal_id, "PENDING")
        ]
        for item in shown.exercises:
            exercise = session.get(Exercise, item.exercise_id)
            assert exercise is not None and exercise.is_active
            assert item.section in exercise.uses
        assert shown.estimated_minutes <= 30
