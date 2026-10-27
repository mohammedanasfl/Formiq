"""How a proposal recovers inside a turn (app.agent.graph, app.agent.policy).

The live regression pass of 2026-10-15 found proposal turns ending with nothing
because a proposal that Formiq had refused before it ran (an id nobody had given
yet, a read not made yet) was refused again, as a duplicate, once the cause was
gone: the word-for-word rule counted the refusal as a result the model had.
These tests script those turns:

- a call is a duplicate only when an earlier identical call ran and returned a
  result; a call Formiq refused before it ran is not one;
- a proposal made before its reads gets them loaded by Formiq, which hands them
  to the model with the refusal, and the corrected proposal has a round;
- a call whose evidence did not change is still refused, and nothing here
  widens the turn's limits.

The model and the tools are scripted: they prove what Formiq enforces, not how
Gemini behaves.
"""

import pytest

from app.agent.graph import (
    CONTEXT_MISSING,
    DUPLICATE_CALL,
    ID_NOT_GROUNDED,
    MAX_TOOL_ITERATIONS,
    PROPOSAL_NOT_MADE_REPLY,
    PROPOSAL_REFUSED,
    PROPOSAL_RETRY_ROUNDS,
)
from app.agent.policy import PROPOSAL_CONTEXT
from tests.coach import call, fake_provider, respond_turn, tool_turn
from tests.unit.test_coach_injection import results_sent
from tests.unit.test_coach_proposal_budget import (
    ACCEPTED,
    FOUND,
    MISSING_CORE,
    READS,
    REPLY,
    USER,
    ScriptedTools,
    offered,
    propose,
    proposal_tools,
    run,
)

DECIDE = respond_turn(REPLY, "ADAPTATION", "RETRIEVE_THEN_ANSWER")


def error_codes(provider, request):
    """The error codes of the results sent to the model in its request-th
    request (from 1: the first request carries no result)."""
    return [
        item["error"]["code"]
        for item in results_sent(provider, request)
        if isinstance(item, dict) and "error" in item
    ]


def executed(tools):
    return [name for batch in tools.runs for name in batch]


# --- a refusal before the call ran is not a result the model has ---


def test_a_proposal_refused_for_ids_nobody_gave_runs_once_a_search_grounded_them():
    # the live QA's turn: the reads, a proposal with ids from nowhere, the
    # search that gives them, and the same proposal again
    tools = proposal_tools(ACCEPTED)
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS)),
        tool_turn(propose(10, 11, 12)),
        tool_turn(call("search_exercises", muscle="Core")),
        tool_turn(propose(10, 11, 12)),
        DECIDE,
    )

    state = run(provider, tools)

    assert error_codes(provider, 2) == [ID_NOT_GROUNDED]
    assert error_codes(provider, 4) == []  # the same proposal ran and was accepted
    assert executed(tools).count("propose_workout_plan") == 1
    assert state["final_response"] == REPLY


# --- a proposal before its reads: Formiq loads them, for the request's user ---


class RecordingTools(ScriptedTools):
    """The scripted tools, which also record whose data each run was for."""

    def __init__(self, answer):
        super().__init__(answer)
        self.users = []

    def run(self, calls, *, user_id):
        self.users.append(user_id)
        return super().run(calls, user_id=user_id)


def tools_where(reads=None, *proposals):
    """Reads answered from reads (a tool's name to its result, or a list of
    results given in turn); a search with FOUND; proposals in turn."""
    answers = iter(proposals)
    reads = {name: iter(value) if isinstance(value, list) else value for name, value in (reads or {}).items()}

    def answer(item):
        if item.name == "propose_workout_plan":
            return next(answers)
        if item.name == "search_exercises":
            return FOUND
        result = reads.get(item.name, {"output": {"tool": item.name}})
        return next(result) if hasattr(result, "__next__") else result

    return RecordingTools(answer)


NONE_YET = {"error": {"code": "RESOURCE_NOT_FOUND", "message": "the user has no such record"}}
NO_PROFILE = {"error": {"code": "PROFILE_NOT_FOUND", "message": "no fitness profile"}}
BROKEN = {"error": {"code": "TOOL_ERROR", "message": "the data could not be read"}}
FIRST_ROUND = tool_turn(call("get_user_profile"), call("search_exercises", muscle="Core"))


def loaded_by_formiq(provider, request):
    """The reads Formiq handed the model with a refusal, by tool name."""
    (refusal,) = [
        item["error"]
        for item in results_sent(provider, request)
        if isinstance(item, dict) and "error" in item and "loaded" in item["error"]
    ]
    return {entry["tool"]: entry["result"] for entry in refusal["loaded"]}


def test_a_proposal_before_its_reads_gets_them_loaded_and_runs_when_proposed_again():
    # the live QA's E2 and R1: the profile, a search, then a proposal; the plan
    # and the last workout were never read
    tools = tools_where(None, ACCEPTED)
    provider = fake_provider(
        FIRST_ROUND, tool_turn(propose(10, 11, 12)), tool_turn(propose(10, 11, 12)), DECIDE
    )

    state = run(provider, tools)

    assert error_codes(provider, 2) == [CONTEXT_MISSING]
    assert list(loaded_by_formiq(provider, 2)) == ["get_current_workout_plan", "get_latest_workout_session"]
    assert error_codes(provider, 3) == []
    assert tools.runs == [
        ["get_user_profile", "search_exercises"],
        ["get_current_workout_plan", "get_latest_workout_session"],  # Formiq's own run
        ["propose_workout_plan"],
    ]
    assert tools.users == [USER] * 3
    assert state["final_response"] == REPLY


@pytest.mark.parametrize("missing", PROPOSAL_CONTEXT)
def test_only_the_read_that_was_not_made_is_loaded(missing):
    first = tool_turn(
        *(call(name) for name in PROPOSAL_CONTEXT if name != missing),
        call("search_exercises", muscle="Core"),
    )
    tools = tools_where(None, ACCEPTED)
    provider = fake_provider(first, tool_turn(propose(10, 11)), tool_turn(propose(10, 11)), DECIDE)

    run(provider, tools)

    assert tools.runs[1] == [missing]
    assert list(loaded_by_formiq(provider, 2)) == [missing]


def test_nothing_is_loaded_when_every_read_was_made():
    tools = tools_where(None, ACCEPTED)
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", muscle="Core")),
        tool_turn(propose(10, 11)),
        DECIDE,
    )

    run(provider, tools)

    assert [name for batch in tools.runs for name in batch].count("get_user_profile") == 1
    assert len(tools.runs) == 2  # the reads and search, then the proposal: nothing to load


@pytest.mark.parametrize("empty", ["get_current_workout_plan", "get_latest_workout_session"])
def test_a_user_with_no_plan_or_no_workout_yet_is_checked_not_refused(empty):
    # a first-time user: the read finds none, which is a check like any other
    tools = tools_where({empty: NONE_YET}, ACCEPTED)
    provider = fake_provider(
        FIRST_ROUND, tool_turn(propose(10, 11)), tool_turn(propose(10, 11)), DECIDE
    )

    state = run(provider, tools)

    assert loaded_by_formiq(provider, 2)[empty] == NONE_YET
    assert error_codes(provider, 3) == []
    assert state["final_response"] == REPLY


def test_a_read_that_failed_is_not_a_check_and_nothing_is_assumed_of_the_data():
    tools = tools_where({"get_current_workout_plan": BROKEN}, ACCEPTED)
    provider = fake_provider(
        FIRST_ROUND,
        tool_turn(propose(10, 11)),
        tool_turn(propose(10, 11)),
        respond_turn("I could not check your plan.", "ADAPTATION", "CANNOT_ANSWER"),
    )

    run(provider, tools)

    (refusal,) = [item["error"] for item in results_sent(provider, 2) if "error" in item]
    assert refusal["code"] == PROPOSAL_REFUSED  # not CONTEXT_MISSING: proposing again cannot fix it
    assert "get_current_workout_plan failed" in refusal["message"]
    assert loaded_by_formiq(provider, 2)["get_current_workout_plan"] == BROKEN
    assert "propose_workout_plan" not in [n for batch in tools.runs for n in batch]
    # Formiq tried the failed read once, in the turn: it does not loop on it
    assert [n for batch in tools.runs for n in batch].count("get_current_workout_plan") == 1


def test_a_failed_read_that_the_model_then_makes_itself_lets_the_proposal_run():
    # Formiq's load failed; the model reads the plan, and its identical proposal runs
    tools = tools_where({"get_current_workout_plan": [BROKEN, {"output": {"plan_id": 4}}]}, ACCEPTED)
    provider = fake_provider(
        FIRST_ROUND,
        tool_turn(propose(10, 11)),
        tool_turn(call("get_current_workout_plan")),
        tool_turn(propose(10, 11)),
        DECIDE,
    )

    state = run(provider, tools)

    assert error_codes(provider, 4) == []
    assert [n for batch in tools.runs for n in batch].count("propose_workout_plan") == 1
    assert state["final_response"] == REPLY


def test_no_profile_ends_the_proposal_for_good():
    tools = tools_where({"get_user_profile": NO_PROFILE}, ACCEPTED)
    provider = fake_provider(
        tool_turn(call("get_user_profile"), call("search_exercises", muscle="Core")),
        tool_turn(propose(10, 11)),
        respond_turn("Tell me your experience and equipment.", "DAILY_WORKOUT", "ASK_CLARIFICATION"),
    )

    state = run(provider, tools)

    (refusal,) = [item["error"] for item in results_sent(provider, 2) if "error" in item]
    assert refusal["code"] == PROPOSAL_REFUSED
    assert "no fitness profile" in refusal["message"]
    assert state["final_response"] == "Tell me your experience and equipment."
    assert provider.generate_turn.call_count == 3  # no retry round for it


def test_reads_in_the_same_batch_as_the_proposal_are_not_loaded_twice():
    tools = tools_where(None, ACCEPTED)
    provider = fake_provider(
        tool_turn(call("search_exercises", muscle="Core")),
        tool_turn(*(call(name) for name in READS), propose(10, 11)),
        tool_turn(propose(10, 11)),
        DECIDE,
    )

    run(provider, tools)

    assert error_codes(provider, 2) == [CONTEXT_MISSING]
    assert "same round" in results_sent(provider, 2)[-1]["error"]["message"]
    assert [n for batch in tools.runs for n in batch].count("get_user_profile") == 1


def test_the_refusal_names_ids_nobody_gave_so_one_proposal_corrects_both():
    tools = tools_where(None, ACCEPTED)
    provider = fake_provider(
        tool_turn(call("get_user_profile")),
        tool_turn(propose(77, 78)),  # no search has given these
        respond_turn("I could not.", "ADAPTATION", "CANNOT_ANSWER"),
    )

    run(provider, tools)

    message = results_sent(provider, 2)[-1]["error"]["message"]
    assert "exercise_id=77" in message and "search the catalog" in message


# --- one more round when the reads came late (the live QA's R6) ---


def test_a_proposal_before_its_reads_in_the_last_round_still_gets_the_retry_round():
    tools = tools_where(None, ACCEPTED)
    provider = fake_provider(
        tool_turn(call("get_user_profile")),
        tool_turn(call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(call("search_exercises", use="WARM_UP")),
        tool_turn(call("search_exercises", use="COOL_DOWN")),
        tool_turn(propose(10, 11)),  # the fifth round: the plan and last workout come now
        tool_turn(propose(10, 11)),  # the retry round
        DECIDE,
    )

    state = run(provider, tools)

    assert provider.generate_turn.call_count == MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 1
    assert offered(provider)[MAX_TOOL_ITERATIONS] == ["propose_workout_plan", "respond"]
    assert error_codes(provider, 6) == []
    assert state["final_response"] == REPLY


# --- what stays refused ---


def test_a_proposal_that_ran_and_was_refused_is_not_run_again_word_for_word():
    tools = tools_where(None, MISSING_CORE, ACCEPTED)
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", muscle="Core")),
        tool_turn(propose(10, 11)),
        tool_turn(propose(10, 11)),
        respond_turn("I could not.", "ADAPTATION", "CANNOT_ANSWER"),
    )

    run(provider, tools)

    assert error_codes(provider, 2) == ["INVALID_INPUT"]
    assert error_codes(provider, 3) == [DUPLICATE_CALL]
    assert [n for batch in tools.runs for n in batch].count("propose_workout_plan") == 1


def test_a_failed_proposal_does_not_make_a_recorded_pending_reply_cost_a_retry():
    pending = {
        "output": {
            "name": "Core & Abs Focus (Harder)",
            "coverage": {"complete": True},
            "revision": {"kind": "ADJUST", "replaces_plan_id": 5},
            "changes": {
                "changed": [
                    {
                        "exercise_name": "Bird Dog",
                        "before": "3 sets of 12 reps, 90 s rest",
                        "after": "4 sets of 12 reps, 90 s rest",
                    }
                ],
                "added": [],
                "removed": [],
            },
        }
    }

    def answer(item):
        if item.name == "get_pending_proposal":
            return pending
        if item.name == "propose_workout_plan":
            return MISSING_CORE
        return {"output": {"tool": item.name}}

    tools = ScriptedTools(answer)
    truth = "The harder version I proposed is currently awaiting your approval."
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS), call("get_pending_proposal")),
        tool_turn(propose(10, 11)),
        respond_turn(truth, "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
        # A pre-fix graph would reject the truthful reply and ask for this fourth request.
        respond_turn(truth, "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(
        provider,
        tools,
        message="Did that save?",
        proposal_awaiting_approval=True,
    )

    assert provider.generate_turn.call_count == 3
    assert state["final_response"] == truth


def test_a_search_that_returned_is_not_run_again_word_for_word():
    tools = tools_where(None)
    provider = fake_provider(
        tool_turn(call("search_exercises", muscle="Core")),
        tool_turn(call("search_exercises", muscle="Core")),
        respond_turn("Core exercises exist.", "EXERCISE", "RETRIEVE_THEN_ANSWER"),
    )

    run(provider, tools)

    assert error_codes(provider, 2) == [DUPLICATE_CALL]
    assert [n for batch in tools.runs for n in batch].count("search_exercises") == 1


def test_a_refused_call_whose_evidence_did_not_change_is_refused_again_and_never_runs():
    # the same proposal, with ids nothing grounded, round after round
    tools = tools_where(None, ACCEPTED)
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS)),
        *(tool_turn(propose(77, 78)) for _ in range(MAX_TOOL_ITERATIONS - 1)),
        tool_turn(propose(77, 78)),  # the retry round
        respond_turn("I could not.", "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools)

    assert [error_codes(provider, n) for n in range(2, 7)] == [[ID_NOT_GROUNDED]] * 5
    assert "propose_workout_plan" not in [n for batch in tools.runs for n in batch]
    assert provider.generate_turn.call_count == MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 1
    assert state["final_response"] == "I could not."


def test_repeated_proposals_never_spend_more_than_the_turns_rounds_or_load_a_read_twice():
    # Formiq's read of the plan failed, so every proposal is refused for good:
    # a different proposal each round gets the same refusal, and nothing is
    # loaded again or run
    tools = tools_where({"get_current_workout_plan": BROKEN}, ACCEPTED)
    provider = fake_provider(
        FIRST_ROUND,
        *(tool_turn(propose(10 + n, 11 + n)) for n in range(MAX_TOOL_ITERATIONS - 1)),
        respond_turn("I could not.", "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools)

    assert provider.generate_turn.call_count == MAX_TOOL_ITERATIONS + 1  # no retry round for it
    ran = [n for batch in tools.runs for n in batch]
    assert ran.count("get_current_workout_plan") == 1 and ran.count("get_latest_workout_session") == 1
    assert "propose_workout_plan" not in ran
    assert state["final_response"] == "I could not."
