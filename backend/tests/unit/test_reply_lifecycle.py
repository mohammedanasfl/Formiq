"""The reply check holds a coach reply to where the user's workouts stand (Phase 2.5).

Until then it matched a few wordings of "I changed your workout", looked at whether a proposal
call happened, and let the rest through: "Here is a slightly harder version of this workout.
Review it and apply it when ready" after a refused proposal, "I've applied your plan",
"Your workout is saved" after a proposal that only awaited approval, and "you don't have a
proposal awaiting approval" while another plan's did (the Phase 2.4 live pass). It is now given
the state (app.agent.trust.Lifecycle): whether the turn's proposal was refused, how many other
proposals await approval, the saved plans the turn read, and the plans an approval saved. These
tests give reply_problem() that state directly, so what they pin is the rule, whatever model
wrote the words. No model, no database.
"""

import pytest

from app.agent.graph import COACH_INSTRUCTIONS, saved_plans_read
from app.agent.trust import (
    REPLY_CLAIMS_APPLIED,
    REPLY_CLAIMS_CHANGE,
    REPLY_CLAIMS_CREATION,
    REPLY_DENIES_PENDING,
    REPLY_DENIES_PENDING_ELSEWHERE,
    REPLY_PRESENTS_REFUSED,
    Lifecycle,
    is_reply_problem,
    reply_problem,
)
from app.ai import ToolCall, ToolResult

NAMES = ("propose_workout_plan", "get_pending_proposal")


def check(reply, lifecycle=None, **facts):
    return reply_problem(
        reply, COACH_INSTRUCTIONS, NAMES, lifecycle=lifecycle or Lifecycle(), **facts
    )


# --- a workout is never said to be saved, applied or updated by what only awaited approval ---


@pytest.mark.parametrize(
    "reply",
    [
        "Your workout is saved.",
        "Your updated workout is saved for Friday.",
        "The new version is now saved.",
        "Your plan has been applied.",
        "The revised plan is all set and applied.",
        "Your changes are applied.",
        "Changes applied.",
        "The update has been made.",
        "Your plan was updated to 4 sets.",
        "Your workout has been adjusted.",
        "The workout is confirmed.",
        "Your plan is locked in.",
        "Your workout has been scheduled.",
        "It's saved.",
        "Done! Your workout is ready.",
    ],
)
def test_a_proposal_the_turn_made_is_never_said_to_be_saved_or_applied(reply):
    assert check(reply, proposed=True) == REPLY_CLAIMS_APPLIED


@pytest.mark.parametrize(
    "reply",
    [
        "I've applied your plan.",
        "I applied the changes to your workout.",
        "I've adjusted your workout.",
        "I have revised your plan.",
        "I've confirmed your workout.",
        "I've finalized your plan.",
        "I've booked your workout.",
        "I've moved your workout to Friday.",
        "I rescheduled your plan for tomorrow.",
        "I've added it to your schedule.",
        "I saved your plan.",
    ],
)
def test_the_coach_never_did_any_of_it_itself(reply):
    # whatever happened in the turn: even after a genuine approval, the coach did not do it
    lifecycle = Lifecycle(plans_read=frozenset({5}), approved_plans=frozenset({5}))

    assert check(reply, lifecycle, proposed=True) == REPLY_CLAIMS_CHANGE
    assert check(reply, lifecycle) == REPLY_CLAIMS_CHANGE


@pytest.mark.parametrize(
    "reply",
    [
        "Your workout is saved.",
        "Your workout has been updated.",
        "Your plan is applied.",
    ],
)
def test_a_pending_proposal_is_not_a_saved_plan_even_when_a_saved_plan_was_read(reply):
    # the proposal awaits approval; the plan the turn read is the original, not an approved one
    lifecycle = Lifecycle(plans_read=frozenset({5}))

    assert check(reply, lifecycle, awaiting_approval=True) == REPLY_CLAIMS_APPLIED
    assert check(reply, Lifecycle(plans_read=frozenset({5}), others_awaiting=1)) == (
        REPLY_CLAIMS_APPLIED
    )


def test_without_a_saved_plan_read_nothing_may_be_said_saved():
    assert check("Your workout is saved for Friday.") == REPLY_CLAIMS_APPLIED
    assert check("Your plan has been updated.", Lifecycle(refused=True)) == REPLY_CLAIMS_APPLIED


def test_a_saved_plan_the_turn_read_may_be_called_saved_or_scheduled():
    read = Lifecycle(plans_read=frozenset({5}))

    assert check("Your workout is saved for Friday, with four exercises.", read) is None
    assert check("Your plan is scheduled for Friday.", read) is None
    # but not applied, updated or approved: nothing shows an approval saved it
    assert check("Your plan has been updated for Friday.", read) == REPLY_CLAIMS_APPLIED
    assert check("Your plan is approved.", read) == REPLY_CLAIMS_APPLIED


def test_a_plan_an_approval_saved_may_be_called_applied_and_updated():
    approved = Lifecycle(plans_read=frozenset({5}), approved_plans=frozenset({5, 3}))

    assert check("Yes, your workout has been updated and is saved for Friday.", approved) is None
    assert check("The changes are applied: the new plan is on Friday.", approved) is None
    # a plan the turn did not read, or one no approval saved, backs nothing
    assert check("Your plan has been applied.", Lifecycle(approved_plans=frozenset({5}))) == (
        REPLY_CLAIMS_APPLIED
    )
    assert check(
        "Your plan has been applied.",
        Lifecycle(plans_read=frozenset({6}), approved_plans=frozenset({5})),
    ) == REPLY_CLAIMS_APPLIED


def test_an_unqualified_update_needs_one_unambiguous_approved_target():
    multiple = Lifecycle(plans_read=frozenset({5, 6}), approved_plans=frozenset({5}))

    assert check("My workout was updated.", multiple) == REPLY_CLAIMS_APPLIED
    assert (
        check(
            "My workout was updated.",
            Lifecycle(
                plans_read=frozenset({5, 6}), approved_plans=frozenset({5}), target_plan_id=5
            ),
        )
        is None
    )
    assert (
        check(
            "My workout was updated.",
            Lifecycle(
                plans_read=frozenset({5, 6}), approved_plans=frozenset({5}), target_plan_id=6
            ),
        )
        == REPLY_CLAIMS_APPLIED
    )


def test_a_proposal_made_in_the_turn_is_not_saved_whatever_an_earlier_approval_says():
    approved = Lifecycle(plans_read=frozenset({5}), approved_plans=frozenset({5}))

    assert check("Your workout is saved.", approved, proposed=True) == REPLY_CLAIMS_APPLIED


@pytest.mark.parametrize(
    "reply",
    [
        "Once you approve it in Formiq, your workout is saved.",
        "It is not saved yet: it waits for your approval.",
        "Your workout is not saved until you approve it.",
        "If you approve it, your plan will be updated.",
        "Your plan hasn't been updated; it only changes when you approve the proposal.",
        "Nothing is saved yet.",
        "Approving it saves it as your plan for Friday.",
    ],
)
def test_what_says_nothing_was_done_is_not_a_claim_that_it_was(reply):
    assert check(reply, proposed=True) is None


# --- a refused proposal is no proposal ---


@pytest.mark.parametrize(
    "reply",
    [
        "Here is a slightly harder version of this workout. Review it and apply it when ready.",
        "Here's another version of the workout for you to look at.",
        "Here are the changes I made.",
        "The updated workout is below.",
        "Take a look at the card.",
        "Approve it in Formiq when you're ready.",
        "I made it harder, so review it and save it.",
        "It awaits your approval in Formiq.",
    ],
)
def test_after_a_refused_proposal_no_workout_is_presented_or_offered_for_approval(reply):
    problem = check(reply, Lifecycle(refused=True))

    assert is_reply_problem(problem)
    assert problem in {
        REPLY_PRESENTS_REFUSED,
        REPLY_CLAIMS_CREATION,
        # the older checks name some of these first, and are kept
        *{p for p in (problem,) if p and "proposal" in p},
    }


def test_the_phase_2_4_wording_is_caught_by_the_refusal_not_by_luck():
    reply = "Here is a slightly harder version of this workout. Review it and apply it when ready."

    # no refusal in the records: the older wording list never matched it
    assert check(reply) is None
    assert check(reply, Lifecycle(refused=True)) == REPLY_PRESENTS_REFUSED


@pytest.mark.parametrize(
    "reply",
    [
        "I couldn't change it: Formiq refused that version. Tell me what you'd like different.",
        "I can't choose a weight for you. How many kg would you like for the woodchop?",
        "It is already planned for that day, so there is nothing to move.",
        "I couldn't make that change this time. Which day would you like?",
    ],
)
def test_after_a_refused_proposal_saying_so_is_fine(reply):
    assert check(reply, Lifecycle(refused=True)) is None


def test_after_a_refused_proposal_an_earlier_proposal_may_still_be_pointed_to():
    lifecycle = Lifecycle(refused=True)

    pointing = "Your earlier proposal is still waiting for your approval in Formiq."
    assert check(pointing, lifecycle, awaiting_approval=True) is None
    # but nothing is presented as made, and with none waiting nothing is offered for approval
    assert (
        check("Here is the updated version.", lifecycle, awaiting_approval=True) is not None
    )
    assert check("Approve it in Formiq.", lifecycle) is not None


def test_a_refusal_that_a_proposal_followed_is_no_refusal():
    # a refused call and then an accepted one: the turn proposed, and the reply may say so
    reply = "Here is a harder version of this workout. Review it and approve it in Formiq."

    assert check(reply, Lifecycle(refused=False), proposed=True) is None


# --- "no proposal is awaiting approval" is said only when none is ---


@pytest.mark.parametrize(
    "reply",
    [
        "You don't currently have a workout proposal awaiting approval.",
        "There is no proposal awaiting your approval.",
        "You have no pending proposals.",
        "Nothing is pending right now.",
        "You don't have any proposals waiting for approval.",
        "I don't see a workout waiting for your approval.",
    ],
)
def test_one_that_awaits_approval_is_never_denied(reply):
    assert check(reply, awaiting_approval=True) == REPLY_DENIES_PENDING


@pytest.mark.parametrize(
    "reply",
    [
        "You don't currently have a workout proposal awaiting approval.",
        "There is no proposal awaiting your approval.",
        "You have no pending proposals.",
        "Nothing is pending right now.",
    ],
)
def test_other_proposals_awaiting_approval_make_a_blanket_denial_false(reply):
    assert check(reply, Lifecycle(others_awaiting=1)) == REPLY_DENIES_PENDING_ELSEWHERE


@pytest.mark.parametrize(
    "reply",
    [
        "There is no proposal awaiting approval for this workout.",
        "I don't see a proposal awaiting approval for this plan; the other one is a different "
        "workout.",
        "None was made for this one, and nothing is waiting for approval for it.",
        "There is no proposal awaiting approval for plan 12.",
    ],
)
def test_a_denial_about_this_workout_alone_is_true_while_others_await(reply):
    assert check(reply, Lifecycle(others_awaiting=2)) is None


@pytest.mark.parametrize(
    "reply",
    [
        "You don't currently have a workout proposal awaiting approval.",
        "There is no proposal awaiting your approval.",
        "Nothing is pending right now.",
    ],
)
def test_when_nothing_awaits_approval_anywhere_saying_so_is_true(reply):
    assert check(reply, Lifecycle(others_awaiting=0)) is None


def test_a_denial_is_judged_a_sentence_at_a_time():
    reply = (
        "There is no proposal awaiting approval for this workout. "
        "You have no pending proposals at all."
    )

    assert check(reply, Lifecycle(others_awaiting=1)) == REPLY_DENIES_PENDING_ELSEWHERE


# --- the records the check is given ---


def plan_read(name, output):
    return ToolResult(ToolCall(name=name, arguments={}), {"output": output})


def test_the_saved_plans_a_turn_read_are_its_planned_plans_only():
    results = [
        plan_read("get_workout_plan", {"plan_id": 4, "status": "PLANNED"}),
        plan_read("get_workout_plan", {"plan_id": 5, "status": "CANCELLED"}),
        plan_read("get_current_workout_plan", {"plan_id": 6, "status": "PLANNED"}),
        plan_read(
            "list_workout_plans",
            {
                "plans": [
                    {"plan_id": 7, "status": "PLANNED"},
                    {"plan_id": 8, "status": "DRAFT"},
                    {"plan_id": True, "status": "PLANNED"},
                ]
            },
        ),
        plan_read("get_pending_proposal", {"plan_id": 9, "status": "PLANNED"}),
        ToolResult(
            ToolCall(name="get_workout_plan", arguments={}),
            {"error": {"code": "RESOURCE_NOT_FOUND", "message": "x"}},
        ),
    ]

    assert saved_plans_read(results) == frozenset({4, 6, 7})
