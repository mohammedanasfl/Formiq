"""The reply guard, fed by Formiq's real records (Phase 2.7).

The rule-level tests (tests/unit/test_reply_guard_hardening.py) give the guard its facts
directly. These make the facts come from the real backend: proposals pending, rejected, expired,
superseded and approved in PostgreSQL, saved plans the turn reads, the request's target, and the
names of the workouts in the tool results, through the real graph. The model is scripted and says
the false thing on purpose, so what they show is that Formiq REJECTS it (and what the user is
finally told), and that a truthful reply costs no extra model request. They do not show what
Gemini writes; only a live pass does. They require the local PostgreSQL container to be running.
"""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.models import WorkoutPlan
from tests.auth import bearer
from tests.coach import call, respond_turn, tool_turn
from tests.integration.test_coach_daily import received, recommend
from tests.integration.test_coach_target import ask, later_id, reads, revising  # noqa: F401
from tests.integration.test_plan_proposals import approve, proposal
from tests.integration.test_plan_revisions import (  # noqa: F401 (fixtures)
    CORE_PLAN,
    clock,
    ids,
    me,
    plan_id,
    revision_of,
    terms,
    today,
    tools,
    use_provider,
    use_terms,
    users,
)
from tests.integration.test_proposal_lifecycle import reject
from tests.integration.test_reply_lifecycle import pending_for, pending_ids, rejection, says

WAITING = "It is still waiting for your approval in Formiq."


def read_pending(reply, *more):
    """A model that reads the proposal awaiting approval, then says `reply` (and then `more`)."""
    return (
        tool_turn(call("get_pending_proposal")),
        says(reply, "RETRIEVE_THEN_ANSWER"),
        *(says(text, "RETRIEVE_THEN_ANSWER") for text in more),
    )


def more_sets_arguments(ids, plan, sets=4):
    """A revision of the plan that differs in one thing: one more set on each main exercise (the
    saved plan has 3 sets of 12 reps with 90 s rest), so the record can call it harder."""
    arguments = revision_of(plan, "ADJUST", ids, *CORE_PLAN, sets=sets)
    arguments["exercises"] = [{**item, "reps": 12, "rest_seconds": 90} for item in arguments["exercises"]]
    return arguments


def harder_than_saved(client, use_provider, me, ids, plan, sets=4):
    """A proposal that revises the plan with more sets on each main exercise: what the record
    can call harder. Its card."""
    response, _ = ask(
        client,
        use_provider,
        me,
        reads(),
        tool_turn(proposal(**more_sets_arguments(ids, plan, sets))),
        recommend("I have proposed one more set on each exercise. It awaits your approval in Formiq."),
        workout_plan_id=plan,
    )
    assert response.status_code == 200, response.json()
    return response.json()["proposal"]


# --- a truthful statement about the pending proposal costs no retry ---


@pytest.mark.parametrize(
    "truth",
    [
        "No, it hasn't saved yet. The harder version I proposed is currently awaiting your approval. "
        "You can review and approve it directly in Formiq to update your saved plan.",
        "No, it has not been saved yet. The harder version of your Core & Abs Focus workout is "
        "waiting for your approval in Formiq.",
        'The updated "Core & Abs Focus (Alternative)" workout is pending your approval.',
    ],
)
def test_a_truthful_pending_statement_is_accepted_at_the_first_request(
    client, use_provider, me, ids, plan_id, truth
):
    shown = harder_than_saved(client, use_provider, me, ids, plan_id)

    response, provider = ask(
        client, use_provider, me, *read_pending(truth),
        message="Did that save?", workout_plan_id=plan_id,
    )  # fmt: skip

    assert response.status_code == 200, response.json()
    # one request to read it, one to answer: the answer was right the first time
    assert provider.generate_turn.call_count == 2
    assert response.json()["reply"] == truth
    # and the proposal is shown again, as it is kept
    assert response.json()["proposal"]["proposal_id"] == shown["proposal_id"]


def test_the_same_words_about_a_proposal_that_is_not_harder_cost_a_retry(
    client, use_provider, me, ids, plan_id
):
    """The record says what the proposal is: a revision with a different prescription, not an
    easier one. "The easier version ... awaiting approval" is the model's own word."""
    harder_than_saved(client, use_provider, me, ids, plan_id)
    lie = "The easier version I proposed is currently awaiting your approval."

    response, provider = ask(
        client, use_provider, me, *read_pending(lie, WAITING),
        message="Did that save?", workout_plan_id=plan_id,
    )  # fmt: skip

    assert provider.generate_turn.call_count == 3
    assert "new or changed proposal" in rejection(provider, 2) or "presents a new" in rejection(provider, 2)
    assert response.json()["reply"] == WAITING


def test_a_first_person_made_it_is_refused_even_beside_a_true_pending_statement(
    client, use_provider, me, ids, plan_id
):
    harder_than_saved(client, use_provider, me, ids, plan_id)

    response, provider = ask(
        client, use_provider, me,
        *read_pending("I've created a new harder version that is awaiting your approval.", WAITING),
        message="Did that save?", workout_plan_id=plan_id,
    )  # fmt: skip

    assert provider.generate_turn.call_count == 3
    assert response.json()["reply"] == WAITING


# --- a name's quoting never hides a claim ---


@pytest.mark.parametrize(
    "lie",
    [
        'I have adjusted your "Core & Abs Focus" workout to set the Cable Woodchop to 20 kg.',
        "I have adjusted your Core & Abs Focus (Alternative) workout to set it to 20 kg.",
        "I've updated “Core & Abs Focus” so the Cable Woodchop is 20 kg.",
        "I have changed your Core Abs Focus workout.",
    ],
)
def test_a_change_claim_about_a_named_workout_is_refused_in_a_turn_that_proposed(
    client, use_provider, me, ids, plan_id, lie
):
    truth = "I have proposed one more set on each exercise. It awaits your approval in Formiq."

    response, provider = ask(
        client, use_provider, me,
        reads(),
        tool_turn(proposal(**more_sets_arguments(ids, plan_id))),
        recommend(lie),
        recommend(truth),
        message="Make it a little harder.", workout_plan_id=plan_id,
    )  # fmt: skip

    assert response.status_code == 200, response.json()
    assert "you can only read it" in rejection(provider, 3)
    assert response.json()["reply"] == truth
    assert response.json()["proposal"]["revision"]["replaces_plan_id"] == plan_id


# --- what became of a proposal: rejected, expired, replaced ---


def lapse_script(plan):
    return {
        "lie": "Your proposal is still awaiting your approval in Formiq. Review and approve it there.",
        "truth": "No proposal is waiting for approval for this workout.",
    }


def test_a_proposal_the_user_rejected_is_not_presented_as_awaiting_approval(
    client, use_provider, me, ids, plan_id
):
    shown = harder_than_saved(client, use_provider, me, ids, plan_id)
    assert reject(client, me, shown).status_code == 204
    words = lapse_script(plan_id)

    response, provider = ask(
        client, use_provider, me,
        tool_turn(call("get_pending_proposal")),
        says(words["lie"], "CANNOT_ANSWER"),
        says(words["truth"], "CANNOT_ANSWER"),
        message="Is it still waiting?", workout_plan_id=plan_id,
    )  # fmt: skip

    assert "none of theirs awaits approval" in rejection(provider, 2)
    assert response.json() == {"reply": words["truth"]}


def test_a_proposal_that_expired_is_not_presented_as_awaiting_approval(
    client, use_provider, me, ids, plan_id, clock
):
    harder_than_saved(client, use_provider, me, ids, plan_id)
    clock.now += timedelta(minutes=31)
    words = lapse_script(plan_id)

    response, provider = ask(
        client, use_provider, me,
        tool_turn(call("get_pending_proposal")),
        says(words["lie"], "CANNOT_ANSWER"),
        says(words["truth"], "CANNOT_ANSWER"),
        message="Is it still waiting?", workout_plan_id=plan_id,
    )  # fmt: skip

    assert "none of theirs awaits approval" in rejection(provider, 2)
    assert response.json() == {"reply": words["truth"]}


def test_a_truthful_it_expired_is_not_refused_when_nothing_awaits(
    client, use_provider, me, ids, plan_id, clock
):
    harder_than_saved(client, use_provider, me, ids, plan_id)
    clock.now += timedelta(minutes=31)
    truth = "That proposal has expired. Shall I make a new one?"

    response, provider = ask(
        client, use_provider, me,
        tool_turn(call("get_pending_proposal")), says(truth, "CANNOT_ANSWER"),
        message="Can I still approve it?", workout_plan_id=plan_id,
    )  # fmt: skip

    assert provider.generate_turn.call_count == 2
    assert response.json() == {"reply": truth}


def test_a_proposal_that_was_replaced_is_not_presented_as_awaiting_approval(
    client, use_provider, me, ids, plan_id, clock
):
    """Superseded by a newer version of the same workout: only the newer one waits, and the
    reply may say so; a statement that two versions wait is the model's invention, and the
    request reads one."""
    older = harder_than_saved(client, use_provider, me, ids, plan_id)
    clock.now += timedelta(minutes=2)
    newer, _ = ask(
        client, use_provider, me,
        reads(),
        tool_turn(proposal(**more_sets_arguments(ids, plan_id, 5))),
        recommend("I have proposed two more sets on each exercise. It awaits your approval in Formiq."),
        workout_plan_id=plan_id,
    )  # fmt: skip
    assert pending_ids(client, me) == [newer.json()["proposal"]["proposal_id"]]
    assert older["proposal_id"] not in pending_ids(client, me)

    response, provider = ask(
        client, use_provider, me,
        *read_pending("There are two proposals waiting for your approval.", WAITING),
        message="What is waiting?", workout_plan_id=plan_id,
    )  # fmt: skip

    assert response.json()["proposal"]["proposal_id"] == newer.json()["proposal"]["proposal_id"]
    assert response.json()["reply"] in (WAITING, "There are two proposals waiting for your approval.")


# --- several plans, several proposals ---


def test_no_proposal_for_this_workout_is_true_and_none_anywhere_is_not(
    client, use_provider, me, ids, plan_id, later_id
):
    mine = harder_than_saved(client, use_provider, me, ids, later_id)
    assert pending_ids(client, me) == [mine["proposal_id"]]

    # the request is about plan_id, which has no proposal; later_id's waits
    allowed, provider_ok = ask(
        client, use_provider, me,
        tool_turn(call("get_pending_proposal")),
        says("There is no proposal awaiting approval for this workout.", "CANNOT_ANSWER"),
        message="Is anything waiting?", workout_plan_id=plan_id,
    )  # fmt: skip
    refused, provider = ask(
        client, use_provider, me,
        tool_turn(call("get_pending_proposal")),
        says("You don't have any proposals awaiting approval.", "CANNOT_ANSWER"),
        says("There is no proposal awaiting approval for this workout.", "CANNOT_ANSWER"),
        message="Is anything waiting?", workout_plan_id=plan_id,
    )  # fmt: skip

    assert provider_ok.generate_turn.call_count == 2
    assert allowed.json() == {"reply": "There is no proposal awaiting approval for this workout."}
    assert "other proposals awaiting approval for other workouts" in rejection(provider, 2)
    assert refused.json() == {"reply": "There is no proposal awaiting approval for this workout."}


def test_an_approval_of_one_plan_backs_nothing_said_of_the_plan_whose_proposal_still_waits(
    client, use_provider, me, ids, plan_id, later_id, test_engine
):
    first = harder_than_saved(client, use_provider, me, ids, plan_id)
    second = harder_than_saved(client, use_provider, me, ids, later_id)
    saved = approve(client, me, first)
    assert saved.status_code == 201
    approved_id = saved.json()["id"]
    waiting_id = later_id
    lie = f"Plan {waiting_id} has been updated, and plan {approved_id} too."
    truth = (
        f"Plan {approved_id} is saved and updated. The change to plan {waiting_id} still "
        "awaits your approval in Formiq."
    )

    response, provider = ask(
        client, use_provider, me,
        # the ids it reads come from the listing: Formiq refuses an id nobody gave
        tool_turn(call("list_workout_plans")),
        tool_turn(
            call("get_workout_plan", plan_id=approved_id), call("get_workout_plan", plan_id=waiting_id)
        ),
        says(lie, "RETRIEVE_THEN_ANSWER"),
        says(truth, "RETRIEVE_THEN_ANSWER"),
        message="What is the state of my plans?",
    )  # fmt: skip

    assert response.status_code == 200, response.json()
    assert "nothing is saved until the user approves" in rejection(provider, 3)
    assert response.json()["reply"] == truth
    assert second["proposal_id"] in pending_ids(client, me)
    with Session(test_engine) as session:
        assert session.get(WorkoutPlan, waiting_id).status == "PLANNED"
