"""The coach says only what the records back about where a workout stands (Phase 2.5).

Adversarial regressions for the three replies the Phase 2.4 live pass caught: a reply that
presented a workout after Formiq refused the proposal, one that said a plan was "updated" or
"adjusted" when it only awaited approval, and one that said the user had no proposal awaiting
approval while another plan's did. Formiq now holds the reply to the state of things: whether the
turn's proposal was refused (a refused call is no proposal), the proposals awaiting approval that
the request does not read, the saved plans the turn read, and the plans an approval saved
(app.agent.trust.Lifecycle).

The model is scripted, and each test makes it say the false thing on purpose: they show that
Formiq REJECTS the reply, whatever the wording a real model would use, and what the user is
finally told. They do not show what Gemini does; only a live pass does. They require the local
PostgreSQL container to be running.
"""

import pytest
from sqlalchemy.orm import Session

from app.ai.exceptions import AIProviderError
from tests.auth import bearer
from tests.coach import call, respond_turn, tool_turn
from tests.integration.test_coach_daily import received, recommend
from tests.integration.test_coach_target import ask, reads, revising, stored_proposals
from tests.integration.test_coach_target import later_id  # noqa: F401 (fixture)
from tests.integration.test_plan_proposals import approve, proposal
from tests.integration.test_plan_revisions import (  # noqa: F401 (fixtures)
    CORE_PLAN,
    clock,
    ids,
    me,
    plan_id,
    revision_of,
    saved_as_proposed,
    terms,
    today,
    tools,
    use_provider,
    use_terms,
    users,
)

HONEST_REFUSAL = (
    "I couldn't make that change: it would leave your workout exactly as it is. "
    "Tell me what you'd like different."
)


def says(reply, decision="CANNOT_ANSWER", intent="WORKOUT_PLAN"):
    return respond_turn(reply, intent, decision)


def rejection(provider, request):
    """What the model was told when its reply was refused, in its request-th request."""
    return received(provider, request)["respond"]["error"]["message"]


@pytest.fixture
def unchanged_plan_id(me, ids, test_engine):
    """A PLANNED plan for today that a revision with nothing changed would equal exactly."""
    with Session(test_engine) as session:
        plan = saved_as_proposed(session, me, revision_of(None, "ADJUST", ids, *CORE_PLAN))
        session.commit()
        return plan.id


def nothing_changed(ids, plan):
    """A revision that prescribes what the plan does: Formiq refuses it as unchanged."""
    return (
        reads(),
        tool_turn(proposal(**{**revision_of(None, "ADJUST", ids, *CORE_PLAN), "revises_plan_id": plan})),
    )


def pending_for(client, use_provider, user, ids, plan):
    """A proposal that revises this plan, awaiting the user's approval: its card."""
    response, _ = ask(client, use_provider, user, *revising(ids, plan), workout_plan_id=plan)
    assert response.status_code == 200, response.json()
    return response.json()["proposal"]


def pending_ids(client, user):
    listed = client.get("/coach/proposals/pending", headers=bearer(user)).json()["proposals"]
    return [item["proposal_id"] for item in listed]


# --- 1. a refused proposal, then a reply that presents a workout ---


@pytest.mark.parametrize(
    ("claim", "told"),
    [
        # the wording the older list caught
        ("Here is the updated workout.", "made no proposal in this turn"),
        # the wording of the Phase 2.4 live pass, which it did not
        (
            "Here is a slightly harder version of this workout. Review it and apply it when ready.",
            "Formiq refused your proposal in this turn",
        ),
        # the older check for a reply that asks for an approval with nothing to approve
        ("I made it harder. Approve it in Formiq when you're ready.", "none was made in this turn"),
    ],
)
def test_a_refused_proposal_is_never_followed_by_a_presented_workout(
    client, use_provider, me, ids, test_engine, unchanged_plan_id, claim, told
):
    response, provider = ask(
        client,
        use_provider,
        me,
        *nothing_changed(ids, unchanged_plan_id),
        says(claim, "RETRIEVE_THEN_ANSWER"),
        says(HONEST_REFUSAL),
        message="Make it a little harder.",
        workout_plan_id=unchanged_plan_id,
    )

    assert response.status_code == 200, response.json()
    # the model was told it, and only its honest reply reached the user: no proposal either
    assert told in rejection(provider, 3)
    assert response.json() == {"reply": HONEST_REFUSAL}
    assert stored_proposals(test_engine, me) == []
    assert pending_ids(client, me) == []


# --- 2. a proposal awaiting approval, then "I've applied your plan" ---


def test_a_pending_proposal_is_never_said_to_be_applied(
    client, use_provider, me, ids, test_engine, plan_id
):
    shown = pending_for(client, use_provider, me, ids, plan_id)

    response, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_pending_proposal")),
        says("I've applied your plan.", "RETRIEVE_THEN_ANSWER"),
        says("It is still waiting for your approval in Formiq.", "RETRIEVE_THEN_ANSWER"),
        message="Did it go through?",
        workout_plan_id=plan_id,
    )

    assert response.status_code == 200, response.json()
    assert "you can only read it" in rejection(provider, 2)
    assert response.json()["reply"] == "It is still waiting for your approval in Formiq."
    # nothing was approved by saying so: the proposal still waits, and the saved plan is as it was
    assert pending_ids(client, me) == [shown["proposal_id"]]
    saved = client.get(f"/users/{me}/workout-plans/{plan_id}").json()
    assert saved["status"] == "PLANNED"


@pytest.mark.parametrize(
    "claim",
    ["Your workout has been updated.", "Your plan is applied.", "The changes were adjusted."],
)
def test_a_pending_proposal_is_not_a_saved_plan_in_the_passive_either(
    client, use_provider, me, ids, test_engine, plan_id, claim
):
    pending_for(client, use_provider, me, ids, plan_id)

    response, provider = ask(
        client,
        use_provider,
        me,
        # the turn reads the saved plan too, which is still the original
        tool_turn(call("get_pending_proposal"), call("get_workout_plan", plan_id=plan_id)),
        says(claim, "RETRIEVE_THEN_ANSWER"),
        says("It is still waiting for your approval in Formiq.", "RETRIEVE_THEN_ANSWER"),
        message="Did it go through?",
        workout_plan_id=plan_id,
    )

    assert "nothing is saved until the user approves" in rejection(provider, 2)
    assert response.json()["reply"] == "It is still waiting for your approval in Formiq."


# --- 3. a proposal made but not approved, then "your workout is saved" ---


@pytest.mark.parametrize(
    "claim", ["Your workout is saved.", "Your updated plan has been saved and is ready to go."]
)
def test_a_proposal_that_only_awaits_approval_is_never_said_to_be_saved(
    client, use_provider, me, ids, test_engine, plan_id, claim
):
    honest = "Here is a harder version of your workout. Review it and approve it in Formiq to save it."

    response, provider = ask(
        client,
        use_provider,
        me,
        reads(),
        tool_turn(proposal(**revision_of(plan_id, "ALTERNATIVE", ids, *CORE_PLAN, sets=4))),
        recommend(claim),
        recommend(honest),
        message="Make it a little harder.",
        workout_plan_id=plan_id,
    )

    assert response.status_code == 200, response.json()
    assert "nothing is saved until the user approves" in rejection(provider, 3)
    body = response.json()
    assert body["reply"] == honest
    # what was shown is a proposal: waiting, with the plan it would replace still saved
    assert pending_ids(client, me) == [body["proposal"]["proposal_id"]]
    assert client.get(f"/users/{me}/workout-plans/{plan_id}").json()["status"] == "PLANNED"
    assert len(client.get(f"/users/{me}/workout-plans?status=PLANNED").json()) == 1


# --- 4. plan A is the target, and only plan B has a pending proposal ---


def test_a_pending_proposal_for_another_plan_is_not_a_blanket_denial(
    client, use_provider, me, ids, test_engine, plan_id, later_id
):
    other = pending_for(client, use_provider, me, ids, later_id)
    blanket = "You don't currently have a workout proposal awaiting approval."
    specific = (
        "There is no proposal awaiting approval for this workout: I haven't made a change to "
        "it. Tell me what you would like to change."
    )

    response, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_pending_proposal")),
        says(blanket),
        says(specific),
        message="Is anything waiting for me to approve?",
        workout_plan_id=plan_id,
    )

    assert response.status_code == 200, response.json()
    # the read says what it does not show: another workout's proposal exists
    read = received(provider, 1)["get_pending_proposal"]["error"]["message"]
    assert "for workout plan" in read and "1 other workout proposal awaiting approval" in read
    assert "other proposals awaiting approval for other workouts" in rejection(provider, 2)
    assert response.json() == {"reply": specific}
    # and the other plan's proposal was neither shown nor touched
    assert pending_ids(client, me) == [other["proposal_id"]]


def test_a_pending_proposal_for_this_plan_is_never_denied(
    client, use_provider, me, ids, test_engine, plan_id
):
    shown = pending_for(client, use_provider, me, ids, plan_id)

    response, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_pending_proposal")),
        says("You have no proposal awaiting approval.", "RETRIEVE_THEN_ANSWER"),
        says("Yes: the workout I proposed is waiting for your approval on the card.", "RETRIEVE_THEN_ANSWER"),
        message="Is anything waiting for me to approve?",
        workout_plan_id=plan_id,
    )

    assert "read it with get_pending_proposal and point to it" in rejection(provider, 2)
    assert response.json()["reply"].startswith("Yes: the workout I proposed")
    assert response.json()["proposal"]["proposal_id"] == shown["proposal_id"]


# --- 5. a genuine approval, then a confirmation ---


def test_a_confirmation_after_a_genuine_approval_is_accepted(
    client, use_provider, me, ids, test_engine, plan_id
):
    shown = pending_for(client, use_provider, me, ids, plan_id)
    approved = approve(client, me, shown)
    assert approved.status_code == 201, approved.json()

    confirmation = "Yes, your workout has been updated and is saved for today."
    response, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_current_workout_plan")),
        says(confirmation, "RETRIEVE_THEN_ANSWER"),
        message="Did that save?",
    )

    assert response.status_code == 200, response.json()
    # no refusal: the turn read the plan that the user's approval saved
    assert provider.generate_turn.call_count == 2
    assert response.json() == {"reply": confirmation}
    read = received(provider, 1)["get_current_workout_plan"]["output"]
    assert read["plan_id"] == approved.json()["id"]


def test_the_same_confirmation_without_an_approval_is_refused(
    client, use_provider, me, ids, test_engine, plan_id
):
    """The turn reads a saved plan, but it is the original: no approval saved it, so it was not
    updated."""
    honest = "Your current plan is Core & Abs Focus, planned for today."

    response, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_current_workout_plan")),
        says("Yes, your workout has been updated and is saved for today.", "RETRIEVE_THEN_ANSWER"),
        says(honest, "RETRIEVE_THEN_ANSWER"),
        message="Did that save?",
    )

    assert "nothing is saved until the user approves" in rejection(provider, 2)
    assert response.json() == {"reply": honest}


def test_a_saved_plan_may_be_called_saved_when_the_turn_read_it(
    client, use_provider, me, ids, test_engine, plan_id
):
    reply = "Your workout is saved for today: Core & Abs Focus."

    response, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_current_workout_plan")),
        says(reply, "RETRIEVE_THEN_ANSWER"),
        message="What is my plan for today?",
    )

    assert provider.generate_turn.call_count == 2
    assert response.json() == {"reply": reply}


# --- 6. the provider fails after an unsupported claim ---


def test_a_provider_failure_after_an_unsupported_success_claim_leaves_nothing_and_says_nothing(
    client, use_provider, me, ids, test_engine, plan_id
):
    provider = use_provider(
        reads(),
        tool_turn(proposal(**revision_of(plan_id, "ALTERNATIVE", ids, *CORE_PLAN, sets=4))),
        recommend("I've applied your plan."),
        AIProviderError("the model request failed"),
    )

    response = client.post(
        "/coach/message",
        headers=bearer(me),
        json={"message": "Make it a little harder.", "workout_plan_id": plan_id},
    )

    # the honest failure, not the claim: the user is shown no proposal and none is kept
    assert (response.status_code, response.json()) == (
        502,
        {"detail": "the AI coach could not answer; try again later"},
    )
    assert "applied" not in response.text
    assert "you can only read it" in rejection(provider, 3)
    assert stored_proposals(test_engine, me) == []
    assert pending_ids(client, me) == []
    assert client.get(f"/users/{me}/workout-plans/{plan_id}").json()["status"] == "PLANNED"


# --- 7. nothing pending anywhere, against a pending proposal for another target ---


@pytest.mark.parametrize("targeted", [True, False], ids=["about a plan", "about nothing in particular"])
def test_nothing_pending_anywhere_may_be_said_plainly(
    client, use_provider, me, ids, test_engine, plan_id, targeted
):
    reply = "You don't have a workout proposal awaiting approval."

    response, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_pending_proposal")),
        says(reply, "CANNOT_ANSWER"),
        message="Is anything waiting for me to approve?",
        **({"workout_plan_id": plan_id} if targeted else {}),
    )

    assert response.status_code == 200, response.json()
    assert provider.generate_turn.call_count == 2
    assert response.json() == {"reply": reply}
    # and the read did not mention other proposals, since there are none
    assert "other workout proposal" not in received(provider, 1)["get_pending_proposal"]["error"]["message"]


def test_another_plans_pending_proposal_changes_what_may_be_said_about_none(
    client, use_provider, me, ids, test_engine, plan_id, later_id
):
    pending_for(client, use_provider, me, ids, later_id)
    reply = "You don't have a workout proposal awaiting approval."

    response, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_pending_proposal")),
        says(reply, "CANNOT_ANSWER"),
        says("Nothing is waiting for approval for this workout.", "CANNOT_ANSWER"),
        message="Is anything waiting for me to approve?",
        workout_plan_id=plan_id,
    )

    # the same words, said while another plan's proposal waits, are refused; about this one, not
    assert "for other workouts" in rejection(provider, 2)
    assert response.json() == {"reply": "Nothing is waiting for approval for this workout."}


# --- what the lifecycle facts rest on ---


def test_a_proposal_the_user_rejected_or_that_was_never_approved_backs_no_confirmation(
    client, use_provider, me, ids, test_engine, plan_id
):
    shown = pending_for(client, use_provider, me, ids, plan_id)
    rejected = client.post(
        f"/coach/proposals/{shown['proposal_id']}/reject",
        headers=bearer(me),
        json={"binding": shown["binding"]},
    )
    assert rejected.status_code == 204

    response, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_current_workout_plan")),
        says("Your workout has been updated.", "RETRIEVE_THEN_ANSWER"),
        says("Your plan is exactly as it was before.", "RETRIEVE_THEN_ANSWER"),
        message="Did that save?",
    )

    assert "nothing is saved until the user approves" in rejection(provider, 2)
    assert response.json()["reply"] == "Your plan is exactly as it was before."
