"""An accepted proposal is not lost when only the model's reply to it is refused
(live Gemini QA of 2026-10-17: 3 of 30 accepted proposals).

Formiq accepted the proposal (the tools built it and every check passed), the
model then worded its reply as a change ("I've updated your workout ..."), the
reply check refused that in every round, and the turn ended at its limit with
the generic "could not answer" reply: the user never saw the proposal Formiq had
accepted, and the QA could not tell the loss from a refusal. Nothing false
reached the user, but the work was dropped for the words.

Now, when the turn ends at its limit with a proposal Formiq accepted, and the
last decision the model gave passed the decision policy and was an answer, and
only its reply was refused, the decision stands and the reply is Formiq's own,
worked out from the card. Everything else ends as before: a refused proposal,
a refused decision, a decision that is no answer and a card without its
figures never show a card.

The model and the tools are scripted: these tests prove what Formiq enforces,
not how Gemini words a reply.
"""

import re

import pytest

from app.agent import CANNOT_ANSWER_REPLY, MAX_TOOL_ITERATIONS
from app.agent.graph import (
    CARD_REPLY_INCOMPLETE,
    CARD_REPLY_REVISION,
    PROPOSAL_NOT_MADE_REPLY,
    PROPOSAL_RETRY_ROUNDS,
    card_reply,
    proposal_card_reply,
    proposed,
)
from app.agent.policy import Respond, proposal_length
from app.agent.trust import (
    REPLY_CLAIMS_CHANGE,
    REPLY_MISSTATES_DURATION,
    REPLY_PROBLEMS,
    is_reply_problem,
    reply_problem,
)
from app.ai import ToolCall, ToolResult
from tests.coach import call, fake_provider, respond_turn, tool_turn
from tests.unit.test_coach_injection import COACH_INSTRUCTIONS, TOOL_NAMES
from tests.unit.test_coach_proposal_budget import (
    ACCEPTED,
    MISSING_CORE,
    READS,
    propose,
    proposal_tools,
    run,
)
from tests.unit.test_coach_reply_duration import MESSAGE, PROPOSED_26, T0_REPLY, made
from tests.unit.test_coach_trajectory import drive, summary_of
from tests.unit.test_coach_unsupported_updates import refusals

# the most model requests a turn may make
MOST_REQUESTS = MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 1
# the wording of the live loss: a change, said of a proposal that saves nothing
CLAIM = "I've updated your workout and swapped in a new squat variation."
CARD = PROPOSED_26["output"]


def result(name, body):
    return ToolResult(call=ToolCall(name=name, arguments={}, id="r"), result=body)


def until_the_limit(reply, intent="WORKOUT_PLAN", decision="RETRIEVE_THEN_ANSWER", turns=6):
    """The turn of the live loss: the reads, the proposal Formiq accepts, then
    the same reply in every round."""
    return fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(propose(10, 11)),
        *(respond_turn(reply, intent, decision) for _ in range(turns)),
    )


# --- a: the accepted proposal is shown, with a reply worked out from its card ---


def test_an_accepted_proposal_whose_change_claim_is_refused_until_the_limit_is_shown():
    provider = until_the_limit(CLAIM)
    tools = proposal_tools(PROPOSED_26)

    state = run(provider, tools, MESSAGE)

    # the claim was refused in every round it was made, and nothing false was ever the answer
    assert reply_problem(CLAIM, COACH_INSTRUCTIONS, TOOL_NAMES, proposed=True) == REPLY_CLAIMS_CHANGE
    assert len(refusals(state)) == MOST_REQUESTS - 3
    assert provider.generate_turn.call_count <= MOST_REQUESTS  # the fallback costs no request
    # Formiq accepted the proposal, which is what is shown: the turn ends as an answer
    assert proposed([m for m in state["messages"] if isinstance(m, ToolResult)])
    assert sum(names.count("propose_workout_plan") for names in tools.runs) == 1
    assert state["final_response"] == card_reply(CARD)
    assert state["final_response"] != CANNOT_ANSWER_REPLY
    decision = state["decision"]
    assert (decision.intent, decision.decision) == ("WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER")
    assert "propose_workout_plan" in decision.tools_used and decision.safety == "SAFE"


def test_the_reply_is_formiqs_and_says_nothing_the_model_wrote():
    state = run(until_the_limit(CLAIM), proposal_tools(PROPOSED_26), MESSAGE)

    reply = state["final_response"]
    assert "updated" not in reply and "swapped" not in reply and "squat" not in reply
    # what it says is the card's: its minutes as Formiq worked them out, and its main exercises
    assert reply.startswith(
        "Here is the workout Formiq built for you: about 26 minutes in all (3 minutes of "
        "warm-up, 18 of main work and 5 of cool-down), with 3 main exercises."
    )
    # and it says the proposal is waiting, not saved
    assert "not saved yet and waits for your approval" in reply


@pytest.mark.parametrize(
    "reply",
    [
        CLAIM,
        "I've saved the workout to your plan, so it is ready.",
        "I approved the plan for you, so it is ready.",
        "The intent is WORKOUT_PLAN and the decision is RETRIEVE_THEN_ANSWER.",
        T0_REPLY,  # a 40-minute workout beside a 26-minute card
    ],
)
def test_whatever_reply_check_refused_the_reply_the_accepted_proposal_is_shown(reply):
    length = proposal_length([result("propose_workout_plan", PROPOSED_26)], [])
    assert (
        reply_problem(reply, COACH_INSTRUCTIONS, TOOL_NAMES, proposed=True, length=length)
        is not None
    )

    provider = until_the_limit(reply)
    state = run(provider, proposal_tools(PROPOSED_26), MESSAGE)

    assert state["final_response"] == card_reply(CARD)
    assert provider.generate_turn.call_count <= MOST_REQUESTS


def test_a_reply_corrected_in_time_is_the_models_and_the_fallback_is_not_used():
    right = "I put together a lower-body workout that takes about 26 minutes. Review it below."
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(propose(10, 11)),
        respond_turn(CLAIM, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        respond_turn(right, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, proposal_tools(PROPOSED_26), MESSAGE)

    assert state["final_response"] == right


def test_the_turn_is_recorded_as_having_reached_its_limit_with_its_proposal_created():
    provider = until_the_limit(CLAIM)

    state, trace, _ = drive(provider, proposal_tools(PROPOSED_26), MESSAGE)

    summary = summary_of(trace)
    assert state["final_response"] == card_reply(CARD)
    # the telemetry still says what happened: the rounds ran out, replies were refused
    assert summary["termination"] == "retry_limit_reached"
    assert summary["budget"]["exhausted"] is True
    assert summary["validation"]["reply_rejections"] >= 1
    assert summary["proposal"]["attempts"] == 1


# --- b: what the reply says is the card's, and passes the check that refused the model's ---


def revision_card():
    return {
        **CARD,
        "revision": {
            "replaces_plan_id": 3,
            "replaces_plan_name": "Core Basics",
            "kind": "ALTERNATIVE",
            "kept_exercises": [],
        },
    }


def incomplete_card():
    return {
        **CARD,
        "coverage": {
            "complete": False,
            "focus": "FULL_BODY",
            "trained_regions": ["CORE"],
            "missing_regions": ["LOWER_BODY"],
            "main_exercises_counted": 2,
            "main_exercises_required": 4,
            "limitations": [],
        },
    }


def one_exercise_card():
    return {**CARD, "exercises": [CARD["exercises"][2]]}


@pytest.mark.parametrize(
    "card", [CARD, revision_card(), incomplete_card(), one_exercise_card()], ids=str
)
def test_the_reply_passes_the_check_that_refuses_the_models_own(card):
    reply = card_reply(card)

    length = proposal_length([result("propose_workout_plan", {"output": card})], [])
    # as the reply of a turn that made a proposal: every claim in it is true
    assert reply_problem(reply, COACH_INSTRUCTIONS, TOOL_NAMES, proposed=True, length=length) is None
    # and it states no figure the card does not have: its minutes, and how many main exercises
    expected = {26, 3, 18, 5, len([e for e in card["exercises"] if e["section"] == "MAIN_WORKOUT"])}
    assert {int(n) for n in re.findall(r"\d+", reply)} == expected


def test_the_reply_states_the_cards_minutes_and_count_of_main_exercises():
    reply = card_reply({**CARD, "estimated_minutes": 31, "main_minutes": 22, "warm_up_minutes": 4,
                        "cool_down_minutes": 5})

    assert "about 31 minutes in all (4 minutes of warm-up, 22 of main work and 5 of cool-down)" in reply
    assert "with 3 main exercises." in reply
    assert "with 1 main exercise." in card_reply(one_exercise_card())


def test_a_revision_says_the_saved_workout_stays_unless_the_user_approves():
    assert CARD_REPLY_REVISION.strip() in card_reply(revision_card())
    assert "replacement" not in card_reply(CARD)
    # the name of the saved plan is data the user stored: never repeated
    assert "Core Basics" not in card_reply(revision_card())


def test_an_incomplete_card_says_so():
    assert CARD_REPLY_INCOMPLETE.strip() in card_reply(incomplete_card())
    assert "could not cover" not in card_reply(CARD)
    complete = {**incomplete_card()["coverage"], "complete": True}
    assert "could not cover" not in card_reply({**CARD, "coverage": complete})


@pytest.mark.parametrize(
    "card",
    [
        {},
        {**CARD, "estimated_minutes": "26"},  # not a number
        {**CARD, "estimated_minutes": True},
        {**CARD, "estimated_minutes": None},
        {**CARD, "main_minutes": 18.5},
        {key: value for key, value in CARD.items() if key != "cool_down_minutes"},
        {**CARD, "exercises": None},
        {**CARD, "exercises": []},  # no main exercise
        {**CARD, "exercises": [{"section": "WARM_UP"}, "x"]},
    ],
)
def test_a_card_without_a_figure_to_read_gives_no_reply(card):
    assert card_reply(card) is None


# --- c: a proposal Formiq refused is never a card ---


def refused_twice(reply=CLAIM, turns=6):
    """Reads, two proposals Formiq refuses, then the same reply in every round."""
    return fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(propose(10, 11)),
        tool_turn(propose(10, 12)),
        *(respond_turn(reply, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER") for _ in range(turns)),
    )


def test_refused_proposals_never_make_a_card_or_say_one_was_made():
    provider = refused_twice()
    tools = proposal_tools(MISSING_CORE, MISSING_CORE)

    state = run(provider, tools, MESSAGE)

    assert sum(names.count("propose_workout_plan") for names in tools.runs) == 2
    assert not proposed([m for m in state["messages"] if isinstance(m, ToolResult)])
    assert state["final_response"] == PROPOSAL_NOT_MADE_REPLY
    assert "Here is the workout" not in state["final_response"]
    assert "minutes" not in state["final_response"]
    assert state["decision"].decision == "CANNOT_ANSWER"
    assert provider.generate_turn.call_count <= MOST_REQUESTS


def test_a_refused_proposal_whose_fixed_workout_is_accepted_later_in_the_turn_is_the_card():
    # refused, then corrected and accepted: the accepted one is the card
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(propose(10, 11)),
        tool_turn(propose(10, 11, 12)),
        *(respond_turn(CLAIM, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER") for _ in range(6)),
    )
    tools = proposal_tools(MISSING_CORE, PROPOSED_26)

    state = run(provider, tools, MESSAGE)

    assert state["final_response"] == card_reply(CARD)


def test_a_pending_proposal_that_was_only_read_is_not_a_proposal_made():
    pending = {"output": {"status": "awaiting_user_approval", **{k: v for k, v in CARD.items() if k != "status"}}}
    results = [result("get_pending_proposal", pending)]
    respond = Respond(intent="WORKOUT_PLAN", decision="RETRIEVE_THEN_ANSWER", reply=CLAIM)

    assert proposal_card_reply(respond, REPLY_CLAIMS_CHANGE, results) is None
    assert proposal_card_reply(respond, REPLY_CLAIMS_CHANGE, []) is None


# --- d: what is not a refused reply is not shown as one ---


def test_a_refused_decision_with_an_accepted_proposal_still_ends_with_the_generic_reply():
    # a plan request is not answered from general knowledge: the decision is refused, whatever
    # its reply says, and a decision is not Formiq's to take for the model
    provider = until_the_limit("Here is your workout.", "WORKOUT_PLAN", "ANSWER")

    state = run(provider, proposal_tools(PROPOSED_26), MESSAGE)

    assert all("is not a decision for a WORKOUT_PLAN request" in why for why in refusals(state))
    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert state["decision"].decision == "CANNOT_ANSWER"
    assert provider.generate_turn.call_count <= MOST_REQUESTS


def test_a_decision_that_is_no_answer_shows_no_card():
    # the user is shown a proposal only with an answer
    provider = until_the_limit(CLAIM + " Which day suits you?", decision="ASK_CLARIFICATION")

    state = run(provider, proposal_tools(PROPOSED_26), MESSAGE)

    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert state["decision"].decision == "CANNOT_ANSWER"


def test_an_accepted_card_without_its_figures_ends_with_the_generic_reply():
    provider = until_the_limit(CLAIM)

    state = run(provider, proposal_tools(ACCEPTED), MESSAGE)  # exercise ids only

    assert proposed([m for m in state["messages"] if isinstance(m, ToolResult)])
    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert provider.generate_turn.call_count <= MOST_REQUESTS


def test_an_invalid_respond_call_is_not_a_refused_reply():
    # arguments that are no decision at all: nothing of it is a decision to stand
    bad = tool_turn(call("respond", intent="WORKOUT_PLAN", reply=CLAIM))
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(propose(10, 11)),
        *(bad for _ in range(6)),
    )

    state = run(provider, proposal_tools(PROPOSED_26), MESSAGE)

    assert state["final_response"] == CANNOT_ANSWER_REPLY


def test_a_model_that_never_proposes_keeps_the_bounded_generic_reply():
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS)),
        *(respond_turn(CLAIM, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER") for _ in range(8)),
    )

    state = run(provider, proposal_tools(), MESSAGE)

    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert provider.generate_turn.call_count <= MOST_REQUESTS


# --- e: the rule that tells a refused reply from a refused decision ---


@pytest.mark.parametrize("problem", list(REPLY_PROBLEMS))
def test_every_reply_problem_is_a_reply_problem(problem):
    assert is_reply_problem(problem)


def test_the_duration_problem_is_one_with_the_figures_the_model_is_told():
    told = f"{REPLY_MISSTATES_DURATION} (it takes about 26 minutes; warm-up, main workout and cool-down 3, 18, 5)"

    assert is_reply_problem(told)


@pytest.mark.parametrize(
    "rejection",
    [
        None,
        "",
        "invalid respond call: intent: Input should be a valid string",
        "WORKOUT_HISTORY is not a decision for a request; use one of: ANSWER",
        "an answer from the user's own data needs data from this turn: call get_latest_workout_session",
    ],
)
def test_a_refused_decision_or_no_refusal_is_not_a_reply_problem(rejection):
    assert not is_reply_problem(rejection)


def test_the_card_reply_needs_an_answer_and_a_refused_reply():
    cards = [result("propose_workout_plan", PROPOSED_26)]
    answer = Respond(intent="WORKOUT_PLAN", decision="RETRIEVE_THEN_ANSWER", reply=CLAIM)
    question = Respond(intent="WORKOUT_PLAN", decision="ASK_CLARIFICATION", reply=CLAIM)

    assert proposal_card_reply(answer, REPLY_CLAIMS_CHANGE, cards) == card_reply(CARD)
    assert proposal_card_reply(question, REPLY_CLAIMS_CHANGE, cards) is None
    assert proposal_card_reply(answer, None, cards) is None
    assert proposal_card_reply(answer, "a decision problem", cards) is None


def test_the_last_accepted_card_is_the_one_a_turn_shows():
    # a turn accepts one proposal (the tools refuse a second); the service shows the last
    first = result("propose_workout_plan", {"output": {**CARD, "estimated_minutes": 40}})
    last = result("propose_workout_plan", PROPOSED_26)
    answer = Respond(intent="WORKOUT_PLAN", decision="RETRIEVE_THEN_ANSWER", reply=CLAIM)

    assert proposal_card_reply(answer, REPLY_CLAIMS_CHANGE, [first, last]) == card_reply(CARD)
