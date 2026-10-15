"""How a turn spends its rounds of tool calls on a proposal (app.agent.graph).

The live QA (2026-10-15) saw proposal turns end with nothing: the reads, then
the searches one round at a time, a proposal refused for something it lacked,
one more search for it, and no round left to propose the corrected workout.
These tests script that turn and its variations: a refused proposal that
proposing again can correct gets one more round, which only proposes or
decides; anything else ends at the limit, saying nothing was proposed. A turn
accepts one proposal, never repeats a search or a proposal word for word, and
may use the catalog exercises Formiq suggests in a refusal.

The model and the tools are scripted: they prove what Formiq enforces, not how
Gemini behaves.
"""

from itertools import count
from unittest.mock import Mock

import pytest

from app.agent import CANNOT_ANSWER_REPLY, MAX_TOOL_ITERATIONS, CoachContext, coach_graph
from app.agent import graph as coach_graph_module
from app.agent.graph import (
    PROPOSAL_NOT_MADE_REPLY,
    PROPOSAL_RETRY_ROUNDS,
    PendingProposal,
    coach_instructions,
    pending_note,
)
from app.agent.state import initial_state
from app.ai import AIProviderError, GeminiProvider, ToolCall
from app.tools import TOOL_DECLARATIONS
from tests.coach import call, fake_provider, respond_turn, sent_contents, tool_responses, tool_turn

USER = 7
READS = ("get_user_profile", "get_current_workout_plan", "get_latest_workout_session")
MESSAGE = "Can you rewrite this plan with different ab exercises?"
REPLY = "Here is a different core workout to review and approve in Formiq."


class ScriptedTools:
    """Formiq's tool declarations, with scripted results: each call's result is
    answer(call), and every call is recorded."""

    declarations = TOOL_DECLARATIONS

    def __init__(self, answer):
        self.answer = answer
        self.runs = []

    def run(self, calls, *, user_id):
        self.runs.append([item.name for item in calls])
        return [self.answer(item) for item in calls]


FOUND = {
    "output": {
        "exercises": [{"exercise_id": n, "name": f"Exercise {n}"} for n in range(10, 16)]
    }
}
ACCEPTED = {"output": {"status": "awaiting_user_approval", "exercises": [{"exercise_id": 10}]}}
MISSING_CORE = {
    "error": {
        "code": "INVALID_INPUT",
        "message": "the main workout trains no core: add a main exercise for it",
        "suggestions": [{"exercise_id": 41, "name": "Dead Bug", "for": "the core"}],
    }
}


def proposal_tools(*proposal_results):
    """Reads and searches that return data, and proposals answered in turn by
    proposal_results."""
    answers = iter(proposal_results)

    def answer(item):
        if item.name == "propose_workout_plan":
            return next(answers)
        if item.name == "search_exercises":
            return FOUND
        return {"output": {"tool": item.name}}

    return ScriptedTools(answer)


_proposals = count(1)


def propose(*ids):
    """The model's proposal of these main exercises. (call() would take its
    name argument for the tool's.)"""
    return ToolCall(
        name="propose_workout_plan",
        arguments={
            "name": "Core",
            "exercises": [{"exercise_id": n, "sets": 3, "reps": 10} for n in ids],
        },
        id=f"proposal-{next(_proposals)}",
    )


def run(provider, tools, message=MESSAGE, **context):
    return coach_graph.invoke(
        initial_state(message),
        context=CoachContext(user_id=USER, provider=provider, tools=tools, **context),
    )


def offered(provider):
    """The tools each model request required, in order."""
    return [
        request.kwargs["required_tool_names"] for request in provider.generate_turn.call_args_list
    ]


def the_qa_turn(*after):
    """The live QA's turn: the reads, the searches one round at a time, a
    proposal refused for the core it lacked, one more search for it; then
    after."""
    return (
        tool_turn(*(call(name) for name in READS)),
        tool_turn(call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(
            call("search_exercises", use="WARM_UP"), call("search_exercises", use="COOL_DOWN")
        ),
        tool_turn(propose(10, 11)),
        tool_turn(call("search_exercises", use="MAIN_WORKOUT", muscle="Core")),
        *after,
    )


# --- one more round to correct a refused proposal ---


def test_a_proposal_refused_late_gets_one_more_round_to_be_corrected():
    tools = proposal_tools(MISSING_CORE, ACCEPTED)
    provider = fake_provider(
        *the_qa_turn(
            tool_turn(propose(10, 11, 41)),
            respond_turn(REPLY, "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
        )
    )

    state = run(provider, tools)

    assert state["final_response"] == REPLY
    assert state["decision"].decision == "RETRIEVE_THEN_ANSWER"
    # the five rounds, then one round that may only propose or decide, then the decision
    every_tool = [tool.name for tool in TOOL_DECLARATIONS] + ["respond"]
    assert offered(provider) == [every_tool] * MAX_TOOL_ITERATIONS + [
        ["propose_workout_plan", "respond"],
        ["respond"],
    ]
    assert state["iteration_count"] == MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS
    assert [names for names in tools.runs if "propose_workout_plan" in names] == [
        ["propose_workout_plan"],
        ["propose_workout_plan"],
    ]


def test_without_that_round_the_same_turn_proposes_nothing(monkeypatch):
    # the turn the live QA saw: the corrected proposal has no round left
    monkeypatch.setattr(coach_graph_module, "PROPOSAL_RETRY_ROUNDS", 0)
    tools = proposal_tools(MISSING_CORE, ACCEPTED)
    provider = fake_provider(
        *the_qa_turn(respond_turn(REPLY, "ADAPTATION", "RETRIEVE_THEN_ANSWER"))
    )

    state = run(provider, tools)

    # the reply claimed a proposal that was never made: Formiq says so instead
    assert state["final_response"] == PROPOSAL_NOT_MADE_REPLY
    assert state["decision"].decision == "CANNOT_ANSWER"
    assert provider.generate_turn.call_count == MAX_TOOL_ITERATIONS + 1


def test_a_proposal_refused_again_in_that_round_ends_saying_nothing_was_proposed():
    tools = proposal_tools(MISSING_CORE, MISSING_CORE)
    provider = fake_provider(
        *the_qa_turn(
            tool_turn(propose(10, 12, 41)),
            # the decision round: a reply claiming a proposal is rejected
            respond_turn(REPLY, "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
        )
    )

    state = run(provider, tools)

    assert state["final_response"] == PROPOSAL_NOT_MADE_REPLY
    assert state["decision"].decision == "CANNOT_ANSWER"
    # one round more, at most: the turn ends after MAX_TOOL_ITERATIONS + 2 requests
    assert provider.generate_turn.call_count == MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 1


@pytest.mark.parametrize(
    "refusal",
    [
        # the reads were not done: proposing again cannot fix that
        {"error": {"code": "PROPOSAL_REFUSED", "message": "check get_user_profile first"}},
        # another user's plan, or a missing one
        {"error": {"code": "RESOURCE_NOT_FOUND", "message": "the user has no workout plan 9"}},
        {"error": {"code": "TOOL_ERROR", "message": "the data could not be read"}},
    ],
    ids=["missing_reads", "not_found", "tool_error"],
)
def test_a_refusal_proposing_again_cannot_fix_gets_no_more_rounds(refusal):
    tools = proposal_tools(refusal)
    provider = fake_provider(
        *the_qa_turn(respond_turn("I could not build it.", "ADAPTATION", "CANNOT_ANSWER"))
    )

    state = run(provider, tools)

    assert offered(provider)[-1] == ["respond"]
    assert provider.generate_turn.call_count == MAX_TOOL_ITERATIONS + 1
    assert state["final_response"] == "I could not build it."


def test_a_model_that_does_anything_but_propose_in_that_round_is_stopped():
    # the provider is told to call only these; a model that calls another
    # anyway ends the turn, as past the limit
    tools = proposal_tools(MISSING_CORE)
    provider = fake_provider(
        *the_qa_turn(tool_turn(call("search_exercises", use="MAIN_WORKOUT", muscle="Obliques")))
    )

    with pytest.raises(AIProviderError, match="after the tool limit"):
        run(provider, tools)


def test_a_turn_that_never_tried_to_propose_ends_with_the_usual_reply():
    provider = Mock(spec=GeminiProvider)
    provider.generate_turn.side_effect = lambda *a, **k: respond_turn(
        "Your goal is fat loss.", "PROFILE", "ANSWER"
    )

    state = run(provider, proposal_tools(), "What is my goal?")

    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert provider.generate_turn.call_count == MAX_TOOL_ITERATIONS + 1


# --- what a refusal gives to correct it ---


def test_the_ids_formiq_suggests_in_a_refusal_may_be_used():
    tools = proposal_tools(MISSING_CORE, ACCEPTED)
    provider = fake_provider(
        tool_turn(
            *(call(name) for name in READS),
            call("search_exercises", use="MAIN_WORKOUT"),
            call("search_exercises", use="WARM_UP"),
            call("search_exercises", use="COOL_DOWN"),
        ),
        tool_turn(propose(10, 11)),
        # 41 was never in a search: Formiq suggested it
        tool_turn(propose(10, 11, 41)),
        respond_turn(REPLY, "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools)

    assert state["final_response"] == REPLY
    (accepted,) = tool_responses(sent_contents(provider, 3)[-1])
    assert accepted.response == ACCEPTED
    # the reads and every search, in one round of 6 calls
    assert tools.runs[0] == [*READS, "search_exercises", "search_exercises", "search_exercises"]


def test_an_id_no_tool_gave_is_still_refused():
    tools = proposal_tools(MISSING_CORE, ACCEPTED)
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(propose(10, 11)),
        tool_turn(propose(10, 11, 99)),
        respond_turn("I could not build it.", "ADAPTATION", "CANNOT_ANSWER"),
    )

    run(provider, tools)

    (refused,) = tool_responses(sent_contents(provider, 3)[-1])
    assert refused.response["error"]["code"] == "ID_NOT_GROUNDED"


# --- one proposal a turn, and no call twice ---


def test_a_turn_accepts_one_proposal():
    tools = proposal_tools(ACCEPTED, ACCEPTED)
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(propose(10, 11)),
        tool_turn(propose(10, 12)),
        respond_turn(REPLY, "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools)

    (second,) = tool_responses(sent_contents(provider, 3)[-1])
    assert second.response["error"]["code"] == "PROPOSAL_REFUSED"
    assert "already accepted a proposal in this turn" in second.response["error"]["message"]
    assert sum(names.count("propose_workout_plan") for names in tools.runs) == 1
    assert state["final_response"] == REPLY


def test_two_proposals_in_one_round_run_one():
    tools = proposal_tools(ACCEPTED, ACCEPTED)
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(propose(10, 11), propose(10, 12)),
        respond_turn(REPLY, "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
    )

    run(provider, tools)

    first, second = tool_responses(sent_contents(provider, 2)[-1])
    assert first.response == ACCEPTED
    assert second.response["error"] == {
        "code": "PROPOSAL_REFUSED",
        "message": "propose one workout at a time",
    }


@pytest.mark.parametrize(
    "repeated",
    [
        call("search_exercises", use="MAIN_WORKOUT", muscle="Core"),
        call("get_exercise", exercise_id=10),
        propose(10, 11),
    ],
    ids=["search", "lookup", "proposal"],
)
def test_a_search_lookup_or_proposal_is_never_run_twice(repeated):
    tools = proposal_tools(MISSING_CORE, MISSING_CORE)
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(repeated),
        tool_turn(type(repeated)(repeated.name, dict(repeated.arguments), "again")),
        respond_turn("I could not build it.", "ADAPTATION", "CANNOT_ANSWER"),
    )

    run(provider, tools)

    (again,) = tool_responses(sent_contents(provider, 3)[-1])
    assert again.response["error"]["code"] == "DUPLICATE_CALL"
    assert sum(names.count(repeated.name) for names in tools.runs) == 1 + (
        repeated.name == "search_exercises"
    )


def test_a_repeated_proposal_earns_no_extra_round():
    # the same refused proposal again is not run, and is no correction to give
    # a round for: past the limit, only the decision is left
    tools = proposal_tools(MISSING_CORE)
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS)),
        tool_turn(call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(call("search_exercises", use="WARM_UP")),
        tool_turn(propose(10, 11)),
        tool_turn(propose(10, 11)),
        respond_turn("I could not build it.", "ADAPTATION", "CANNOT_ANSWER"),
    )

    state = run(provider, tools)

    (again,) = tool_responses(sent_contents(provider, 5)[-1])
    assert again.response["error"]["code"] == "DUPLICATE_CALL"
    assert offered(provider)[-1] == ["respond"]
    assert provider.generate_turn.call_count == MAX_TOOL_ITERATIONS + 1
    assert state["final_response"] == "I could not build it."


# --- the proposal awaiting approval ---


def test_the_model_is_told_of_a_proposal_awaiting_approval_by_numbers_only():
    provider = fake_provider(respond_turn("Hi!"))
    pending = PendingProposal(expires_in_minutes=23, revises_plan_id=6)

    run(provider, proposal_tools(), "Hi", proposal_awaiting_approval=True, pending_proposal=pending)

    instructions = provider.generate_turn.call_args.kwargs["instructions"]
    assert instructions.endswith(pending_note(pending))
    assert "for 23 more minutes; approving it would replace their saved plan 6" in instructions
    assert "Read it with get_pending_proposal" in instructions


def test_without_one_the_instructions_say_nothing_of_it():
    provider = fake_provider(respond_turn("Hi!"))

    run(provider, proposal_tools(), "Hi")

    context = CoachContext(user_id=USER, provider=provider, tools=proposal_tools())
    assert provider.generate_turn.call_args.kwargs["instructions"] == coach_instructions(context)
    assert "get_pending_proposal before saying" not in coach_instructions(context)
