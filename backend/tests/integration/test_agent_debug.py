"""AGENT_DEBUG through the API, against PostgreSQL (the test database, never the dev
one): the coach answers exactly as it does without the debug output, the proposal it
keeps is the same, the user's approval of it works as before, and what is printed
never holds the proposal's id or its binding.

The flow is the live QA's loss, through the API: Formiq accepts a proposal, the model
words its reply as a change in every round, and the proposal is shown with Formiq's
own reply (the card fallback). The model is scripted: no test calls Gemini. They
require the local PostgreSQL container to be running.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_tracer
from app.main import app
from app.models import WorkoutPlan, WorkoutPlanProposal
from app.observability import Tracer
from tests.integration.test_coach_accepted_proposal_fallback import (
    MESSAGE,
    claiming,
    workout_of,
)
from tests.integration.test_coach_follow_ups import ask
from tests.integration.test_coach_unsupported_updates import kept
from tests.integration.test_plan_proposals import approve, proposing
from tests.integration.test_plan_revisions import (  # noqa: F401 (fixtures)
    CORE_PLAN,
    REWRITE,
    clock,
    core_plan,
    ids,
    me,
    plan_id,
    rewriting,
    stored_plans,
    terms,
    today,
    tools,
    use_provider,
    use_terms,
    users,
)
from tests.observability import debugging, labelled, parse

# what differs between two proposals of the same workout: its identity and its clock
VARYING = {"proposal_id", "binding", "expires_at"}


def ask_with(tracer, client, use_provider, user, ids):
    """The card-fallback flow for this user, with this tracer as the application's."""
    app.dependency_overrides[get_tracer] = lambda: tracer
    try:
        return ask(client, use_provider, user, *claiming(proposing(ids)[:-1]), message=MESSAGE)
    finally:
        app.dependency_overrides.pop(get_tracer, None)


def shape(card):
    return {key: value for key, value in card.items() if key not in VARYING}


@pytest.mark.parametrize("level", ["events", "content"])
def test_the_api_answers_the_same_and_keeps_the_same_proposal_with_the_debug_output_on(
    level, client, use_provider, users, ids, test_engine
):
    plain_user, shown_user = users
    debugger = debugging(level)

    plain, plain_provider = ask_with(Tracer(), client, use_provider, plain_user, ids)
    shown, shown_provider = ask_with(debugger.tracer, client, use_provider, shown_user, ids)

    # the response: the same reply, and the same proposal apart from its identity and clock
    assert shown["reply"] == plain["reply"]
    assert shape(shown["proposal"]) == shape(plain["proposal"])
    assert set(shown) == set(plain) and set(shown["proposal"]) == set(plain["proposal"])
    # what the model was sent: the same instructions, tools and tool configuration
    sent = lambda provider: [  # noqa: E731
        (call.kwargs["instructions"], repr(call.kwargs["tools"]), call.kwargs["required_tool_names"])
        for call in provider.generate_turn.call_args_list
    ]
    assert sent(shown_provider) == sent(plain_provider)
    # what was kept: one PENDING proposal for each user, the same workout, with nothing saved
    (kept_plain,) = kept(test_engine, plain_user)
    (kept_shown,) = kept(test_engine, shown_user)
    assert kept_shown[0] == shown["proposal"]["proposal_id"]
    assert kept_shown[1]["name"] == kept_plain[1]["name"]
    with Session(test_engine) as session:
        rows = session.scalars(select(WorkoutPlanProposal).order_by(WorkoutPlanProposal.user_id)).all()
        assert [(row.user_id, row.status) for row in rows] == [(plain_user, "PENDING"), (shown_user, "PENDING")]
        assert session.scalars(select(WorkoutPlan)).all() == []
    assert debugger.stream.getvalue()  # and it printed


def test_the_proposal_made_under_debugging_is_approved_once_by_its_user_only(
    client, use_provider, users, ids, test_engine
):
    me, other = users
    debugger = debugging("content")
    body, _ = ask_with(debugger.tracer, client, use_provider, me, ids)
    card = body["proposal"]

    assert approve(client, other, card).status_code == 404  # not found for another user
    assert approve(client, me, card, binding="0" * len(card["binding"])).status_code in (400, 409, 422)
    first = approve(client, me, card)
    again = approve(client, me, card)

    assert (first.status_code, again.status_code) == (201, 409)
    saved = first.json()
    assert (saved["name"], saved["status"]) == (card["name"], "PLANNED")
    assert [
        (e["exercise_id"], e["section"], e["sets"], e["reps"], e["duration_seconds"])
        for e in saved["exercises"]
    ] == workout_of(card)
    with Session(test_engine) as session:
        assert len(session.scalars(select(WorkoutPlan).where(WorkoutPlan.user_id == me)).all()) == 1


def test_the_debug_output_names_the_turns_proposal_by_its_short_reference_never_its_id_or_binding(
    client, use_provider, users, ids
):
    me, _ = users
    debugger = debugging("content")

    body, _ = ask_with(debugger.tracer, client, use_provider, me, ids)

    card = body["proposal"]
    output = debugger.stream.getvalue()
    lines = parse(output)
    # the turn, from the service's input to its summary, and who wrote the reply the user got
    for label in ("input", "request", "response", "response_source", "turn_completed", "summary", "end"):
        assert labelled(lines, label), label
    (source,) = labelled(lines, "response_source")
    assert source.fields.startswith("source=card_fallback detail=accepted_proposal")
    (created,) = labelled(lines, "proposal_created")
    assert f"proposal_ref={card['proposal_id'][:8]}" in created.fields
    assert f"proposal_ref={card['proposal_id'][:8]}" in labelled(lines, "summary")[0].fields
    # never what enables access to it: not its id, its binding, nor the user's own words
    assert card["proposal_id"] not in output and card["binding"] not in output
    assert "Build me an upper-body" not in output
    assert f"| user {me} | AGENT_DEBUG=content ===" in output.splitlines()[0]
