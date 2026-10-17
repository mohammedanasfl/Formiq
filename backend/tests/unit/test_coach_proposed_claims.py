"""A reply that says the coach proposed a new or updated workout, in a turn that
proposed none (live Gemini QA of 2026-10-17, after the B2 to B5 fixes).

The user, with a proposal awaiting approval, asked "Can you put Easy Rowing in my
main workout?". The coach read what it needed, tried to propose a workout twice,
Formiq refused both, and the coach answered "However, I have proposed an updated
full-body workout that adds the One-Arm Dumbbell Row ... You can review and
approve it in Formiq." The reply guard accepted it, and Formiq showed the
unchanged pending proposal beside it, which has no such exercise.

The facts were right: `proposed` (a proposal call Formiq accepted) was false, and
a read of the pending proposal is no such call. The words were the hole: the
guard reads the coach's claims by the verbs of making and changing a workout
(app.agent.trust MAKING_VERBS, CHANGING_VERBS), and "propose", the coach's own
verb for the one thing it does, was in neither. So "I have proposed ..." matched
no claim pattern, in the check of a turn that tried to propose and in the check
of one that only explained.

These tests are scripted: they prove what Formiq enforces, not how Gemini words
a reply. The live reply below is verbatim from the pass.
"""

import pytest

from app.agent import MAX_TOOL_ITERATIONS
from app.agent.graph import PROPOSAL_NOT_MADE_REPLY, PROPOSAL_RETRY_ROUNDS, proposed
from app.agent.trust import (
    MAKING_VERBS,
    REPLY_CLAIMS_CREATION,
    REPLY_CLAIMS_NEW_PROPOSAL,
    REPLY_CLAIMS_PROPOSAL,
    reply_problem,
    verb_forms,
)
from app.ai import ToolCall, ToolResult
from tests.coach import call, fake_provider, respond_turn, tool_turn
from tests.unit.test_coach_injection import COACH_INSTRUCTIONS, TOOL_NAMES
from tests.unit.test_coach_proposal_budget import ACCEPTED, MISSING_CORE, READS, propose, run
from tests.unit.test_coach_recovery import tools_where
from tests.unit.test_coach_unsupported_updates import (
    FRESH,
    read_then_reply,
    refusals,
)

LIVE_MESSAGE = "Can you put Easy Rowing in my main workout?"
LIVE_REPLY = (
    "Formiq's catalog has Easy Rowing only for warm-ups and cool-downs, not for the main "
    "workout. However, I have proposed an updated full-body workout that adds the One-Arm "
    "Dumbbell Row to cover your upper-body pull. You can review and approve it in Formiq."
)
# what the coach should say: Easy Rowing is for warm-ups and cool-downs; the proposal is as it was
HONEST = (
    "Formiq's catalog has Easy Rowing only for warm-ups and cool-downs, not for the main "
    "workout, so your proposal is as it was. Tell me what you'd like different and I can "
    "propose a new version."
)

# "propose" said as the coach's own doing: each is a claim that a proposal was made
PROPOSED_CLAIMS = [
    "I have proposed a new workout that adds the One-Arm Dumbbell Row.",
    "I've proposed a new workout for you: squats, rows and planks.",
    "I proposed an updated workout that leaves out the bench exercises.",
    "I have now proposed a replacement workout that drops the lunges.",
    "I've gone ahead and proposed a revised plan with a shorter warm-up.",
    "We've proposed a different version of your workout.",
    "I just proposed another workout for you.",
    "I have proposed a lighter routine that fits your 20 minutes.",
    "A new workout has been proposed for you.",
    "An updated full-body workout has now been proposed.",
    "Your replacement plan has just been proposed.",
]


def check(reply, *, proposed=False, awaiting=True, explaining=False):
    """What the reply guard says of a reply in a turn: `proposed` is what Formiq's own
    tools did (a proposal accepted), `awaiting` its records of a proposal of the
    user's awaiting approval, `explaining` the turn's reading of the user's message."""
    return reply_problem(
        reply,
        COACH_INSTRUCTIONS,
        TOOL_NAMES,
        proposed=proposed,
        awaiting_approval=awaiting,
        explaining=explaining,
        recorded_changes=(),
    )


# --- A: the live reply ---


def test_the_live_reply_is_refused_when_the_turn_proposed_nothing():
    # the live turn: a proposal awaits approval; the turn tried to propose, so it is no explanation
    assert check(LIVE_REPLY) == REPLY_CLAIMS_NEW_PROPOSAL


def test_the_live_reply_is_refused_in_an_explanation_too():
    assert check(LIVE_REPLY, explaining=True) == REPLY_CLAIMS_NEW_PROPOSAL


def test_the_live_reply_is_refused_when_nothing_awaits_approval():
    assert check(LIVE_REPLY, awaiting=False) == REPLY_CLAIMS_PROPOSAL


def test_the_live_claim_is_refused_without_its_invitation_to_approve():
    claim = LIVE_REPLY.removesuffix(" You can review and approve it in Formiq.")

    # nothing to approve is asked, so only the claim itself can be read: it is a claim of making one
    assert check(claim) == REPLY_CLAIMS_CREATION
    assert check(claim, explaining=True) == REPLY_CLAIMS_NEW_PROPOSAL
    assert check(claim, awaiting=False) == REPLY_CLAIMS_CREATION


# --- B: the wording of the claim ---


@pytest.mark.parametrize("claim", PROPOSED_CLAIMS)
@pytest.mark.parametrize("explaining", [False, True])
@pytest.mark.parametrize("awaiting", [False, True])
def test_no_wording_of_a_proposal_that_was_not_made_reaches_the_user(claim, explaining, awaiting):
    assert check(claim, awaiting=awaiting, explaining=explaining) is not None


@pytest.mark.parametrize("claim", PROPOSED_CLAIMS)
def test_with_a_proposal_awaiting_the_claim_is_a_new_one_not_the_awaiting_one(claim):
    assert check(claim) in (REPLY_CLAIMS_NEW_PROPOSAL, REPLY_CLAIMS_CREATION)


def test_propose_is_a_verb_of_making_a_workout_like_the_rest():
    assert "propose" in MAKING_VERBS
    assert verb_forms("propose") == ("proposed",)


# --- C: a proposal Formiq accepted in the turn backs the claim ---


@pytest.mark.parametrize("reply", [LIVE_REPLY, *PROPOSED_CLAIMS])
@pytest.mark.parametrize("awaiting", [False, True])
def test_a_proposal_the_turn_made_backs_the_claim_that_it_was_made(reply, awaiting):
    # `proposed` is Formiq's own record: the claim is then true
    assert check(reply, proposed=True, awaiting=awaiting) is None


# --- D: what is no claim of a proposal made ---

# offers, plans and negations, and an honest account of a refusal: in any turn
NO_CLAIM = [
    "I can propose a new version if you tell me what to change.",
    "Would you like me to propose an updated workout?",
    "I'll propose an updated workout as soon as you pick the exercises.",
    "I haven't proposed anything new: your proposal is as it was.",
    "I have not proposed a new workout, so the one you have is unchanged.",
    "I couldn't propose a new workout this time.",
    "I tried to propose a workout with the One-Arm Dumbbell Row, but Formiq refused it, so "
    "your proposal is as it was.",
    HONEST,
]
# what describes the proposal the user is shown, in a turn that only explained it
EXPLANATIONS = [
    "I proposed this workout around your goal and the 40 minutes you have.",
    "The workout I proposed has Bodyweight Squat and Push-Up in the main part.",
    "I proposed these exercises because none of them needs a bench.",
    "I have proposed this lower-body workout to fit the equipment you said you have.",
]


@pytest.mark.parametrize("reply", NO_CLAIM)
@pytest.mark.parametrize("explaining", [False, True])
def test_an_offer_a_negation_or_an_honest_refusal_claims_no_proposal(reply, explaining):
    assert check(reply, explaining=explaining) is None


@pytest.mark.parametrize("reply", EXPLANATIONS)
def test_a_description_of_the_proposal_the_user_is_shown_is_no_claim_of_a_new_one(reply):
    assert check(reply, explaining=True) is None


def test_the_same_description_is_held_to_the_strict_check_when_the_turn_was_no_explanation():
    # a turn that tried to propose, or a user who asked for a change, shows the proposal
    # as it was: "I proposed this workout" then says what the turn did not do
    assert check(EXPLANATIONS[0], explaining=False) is not None


# --- E: the facts: a read of the pending proposal, or a refused proposal, is no proposal made ---


def result(name, body, id_="r"):
    return ToolResult(call=ToolCall(name=name, arguments={}, id=id_), result=body)


def test_only_a_proposal_formiq_accepted_is_a_proposal_made():
    reading = result("get_pending_proposal", FRESH)
    refused = result("propose_workout_plan", MISSING_CORE)
    accepted = result("propose_workout_plan", ACCEPTED)

    assert not proposed([reading])
    assert not proposed([reading, refused])
    assert not proposed([reading, refused, refused])
    assert proposed([reading, refused, accepted])


# --- F: the turn through the graph ---


def refused_twice(message, *replies):
    """The live turn: the model reads what a proposal rests on, the exercises and the
    proposal awaiting approval, tries to propose twice, Formiq refuses both (the
    tools, for a main workout that trains no core), and the model answers with each
    reply in turn."""
    provider = fake_provider(
        tool_turn(
            *(call(name) for name in READS),
            call("get_pending_proposal"),
            call("search_exercises", use="MAIN_WORKOUT"),
        ),
        tool_turn(propose(10, 11)),
        tool_turn(propose(10, 12)),
        *(respond_turn(reply, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER") for reply in replies),
    )
    tools = tools_where({"get_pending_proposal": FRESH}, MISSING_CORE, MISSING_CORE)
    state = run(provider, tools, message, proposal_awaiting_approval=True)
    return provider, tools, state


def test_the_live_turn_does_not_reach_the_user():
    provider, tools, state = refused_twice(LIVE_MESSAGE, LIVE_REPLY, HONEST)

    # both proposals ran and Formiq refused both: none was accepted, though the pending one was read
    assert sum(names.count("propose_workout_plan") for names in tools.runs) == 2
    attempts = [
        m
        for m in state["messages"]
        if isinstance(m, ToolResult) and m.call.name == "propose_workout_plan"
    ]
    assert [m.result["error"]["code"] for m in attempts] == ["INVALID_INPUT", "INVALID_INPUT"]
    assert not proposed([m for m in state["messages"] if isinstance(m, ToolResult)])
    assert refusals(state) == [REPLY_CLAIMS_NEW_PROPOSAL]
    assert provider.generate_turn.call_count == 5  # the reads, two proposals, the claim, the answer
    assert state["final_response"] == HONEST


@pytest.mark.parametrize("claim", PROPOSED_CLAIMS[:4])
def test_a_proposal_claimed_after_refused_proposals_is_corrected_in_the_retry(claim):
    provider, _, state = refused_twice(LIVE_MESSAGE, claim, HONEST)

    assert len(refusals(state)) == 1
    assert state["final_response"] == HONEST


def test_a_claim_repeated_until_the_limit_ends_with_formiqs_own_reply():
    provider, _, state = refused_twice(
        LIVE_MESSAGE, *(LIVE_REPLY for _ in range(MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 2))
    )

    assert state["final_response"] == PROPOSAL_NOT_MADE_REPLY
    assert "Row" not in state["final_response"]
    assert provider.generate_turn.call_count <= MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 1


@pytest.mark.parametrize("message", ["Why did you choose these?", "What is in the proposal?"])
def test_a_read_of_the_pending_proposal_does_not_back_a_new_one(message):
    # no proposal was tried: the turn explains the one awaiting approval, and the user is shown it
    # again, unchanged. "I have proposed an updated workout" says it was changed
    provider, state = read_then_reply(message, LIVE_REPLY, HONEST, intent="WORKOUT_PLAN")

    assert refusals(state) == [REPLY_CLAIMS_NEW_PROPOSAL]
    assert provider.generate_turn.call_count == 3
    assert state["final_response"] == HONEST


def test_a_truthful_description_of_the_pending_proposal_costs_no_extra_request():
    reply = (
        "I proposed this workout around your goal, and none of its exercises needs a bench. "
        "You can review and approve it in Formiq."
    )

    provider, state = read_then_reply("Why did you choose these?", reply, intent="WORKOUT_PLAN")

    assert provider.generate_turn.call_count == 2  # the read, the answer
    assert refusals(state) == []
    assert state["final_response"] == reply


def test_a_proposal_the_turn_made_backs_the_claim_through_the_graph():
    tools = tools_where({"get_pending_proposal": FRESH}, ACCEPTED)
    provider = fake_provider(
        tool_turn(
            *(call(name) for name in READS),
            call("get_pending_proposal"),
            call("search_exercises", use="MAIN_WORKOUT"),
        ),
        tool_turn(propose(10, 11)),
        respond_turn(LIVE_REPLY, "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, tools, LIVE_MESSAGE, proposal_awaiting_approval=True)

    assert provider.generate_turn.call_count == 3  # no retry: the claim is true
    assert refusals(state) == []
    assert state["final_response"] == LIVE_REPLY
    assert proposed([m for m in state["messages"] if isinstance(m, ToolResult)])
