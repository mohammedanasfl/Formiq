"""Follow-ups to the coach's proposals and the user's saved plans, from
Formiq's records: what the live QA (2026-10-15) saw the coach get wrong.

- The proposal awaiting the user's approval is read back for the signed-in
  user only (get_pending_proposal): what it holds, its coverage, what it
  changes; the model is told it exists, by numbers only; the user is shown it
  again, as kept, and approves it once. The same workout is never proposed
  again while it waits.
- The user's saved plans are listed (list_workout_plans): none, one or many,
  and only theirs. Two plans are compared by Formiq (compare_with_plan_id).
- A revision is of a plan the conversation makes clear: with several PLANNED
  plans and nothing to tell them apart, Formiq refuses it, so the coach asks.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import ToolCall
from app.api.dependencies import PROPOSAL_TTL
from app.models import WorkoutPlan, WorkoutPlanProposal
from tests.auth import bearer
from tests.coach import call, respond_turn, tool_turn
from tests.integration.test_coach_daily import TODAY, received
from tests.integration.test_plan_proposals import approve, problem, proposing
from tests.integration.test_plan_revisions import (  # noqa: F401 (fixtures)
    CORE_PLAN,
    REWRITE,
    clock,
    core_plan,
    ids,
    me,
    plan_id,
    revision_of,
    rewriting,
    terms,
    today,
    tools,
    use_provider,
    use_terms,
    users,
)
from tests.integration.workout_plans import add_user

ABOUT_IT = "What did you propose?"


def ask(client, use_provider, user_id, *turns, message=ABOUT_IT, history=()):
    provider = use_provider(*turns)
    response = client.post(
        "/coach/message",
        headers=bearer(user_id),
        json={
            "message": message,
            "history": [{"role": role, "text": text} for role, text in history],
        },
    )
    assert response.status_code == 200, response.json()
    return response.json(), provider


def reading_it(
    reply="It is a full-body bodyweight workout: Push-Up, Walking Lunge, a band row and Bird Dog.",
    decision="RETRIEVE_THEN_ANSWER",
):
    """A model that reads the proposal awaiting approval, then answers; with
    none, an answer from data is refused, so it says there is none."""
    return (
        tool_turn(call("get_pending_proposal")),
        respond_turn(reply, "WORKOUT_PLAN", decision),
    )


def none_waiting(reply="No workout of yours is waiting for approval."):
    return reading_it(reply, decision="CANNOT_ANSWER")


def instructions_of(provider, request=0):
    return provider.generate_turn.call_args_list[request].kwargs["instructions"]


# --- the proposal awaiting approval ---


def test_the_proposal_awaiting_approval_is_read_back_and_shown_again(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    first, _ = ask(client, use_provider, me, *proposing(ids), message="What should I do today?")
    shown = first["proposal"]

    body, provider = ask(client, use_provider, me, *reading_it())

    # the model was told it exists, by numbers only, before any tool
    assert "a workout you proposed to the user earlier awaits their approval (for 30 more " \
        "minutes)" in instructions_of(provider)  # fmt: skip
    read = received(provider, 1)["get_pending_proposal"]["output"]
    assert read["status"] == "awaiting_user_approval"
    assert [item["exercise_name"] for item in read["exercises"]] == [
        item["exercise_name"] for item in shown["exercises"]
    ]
    assert [item["sets"] for item in read["exercises"]] == [
        item["sets"] for item in shown["exercises"]
    ]
    assert read["coverage"] == shown["coverage"]
    assert (read["name"], read["estimated_minutes"]) == (shown["name"], shown["estimated_minutes"])
    assert read["expires_in_minutes"] == 30
    assert (read["revision"], read["changes"], read["earlier_proposals_awaiting_approval"]) == (
        None,
        None,
        0,
    )
    # the model never gets the proposal's id; the user is shown it again, as kept
    assert shown["proposal_id"] not in str(read)
    again = body["proposal"]
    assert (again["proposal_id"], again["binding"]) == (shown["proposal_id"], shown["binding"])
    assert again["exercises"] == shown["exercises"]
    # nothing new was kept for it
    with Session(test_engine) as session:
        assert session.scalar(select(WorkoutPlanProposal.proposal_id).where(
            WorkoutPlanProposal.user_id == me
        )) == shown["proposal_id"]  # fmt: skip

    # approved once, from either card: then it awaits nothing
    assert approve(client, me, again).status_code == 201
    assert approve(client, me, shown).status_code == 409
    after, provider = ask(client, use_provider, me, *none_waiting())
    assert "get_pending_proposal before saying" not in instructions_of(provider)
    assert received(provider, 1)["get_pending_proposal"]["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert "proposal" not in after


def test_another_users_proposal_is_never_read(client, use_provider, users, ids):
    me, them = users
    ask(client, use_provider, me, *proposing(ids), message="What should I do today?")

    body, provider = ask(client, use_provider, them, *none_waiting())

    assert "get_pending_proposal before saying" not in instructions_of(provider)
    assert received(provider, 1)["get_pending_proposal"]["error"] == {
        "code": "RESOURCE_NOT_FOUND",
        "message": "the user has no workout proposal awaiting approval: none was made, or it "
        "was approved or expired; there is no id to ask for",
    }
    assert "proposal" not in body


def test_an_expired_proposal_awaits_nothing(client, use_provider, users, ids, clock):
    me, _ = users
    ask(client, use_provider, me, *proposing(ids), message="What should I do today?")
    clock.now += PROPOSAL_TTL

    body, provider = ask(client, use_provider, me, *none_waiting())

    assert "get_pending_proposal before saying" not in instructions_of(provider)
    assert received(provider, 1)["get_pending_proposal"]["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert "proposal" not in body


def test_the_latest_proposal_is_the_one_read(client, use_provider, users, ids, clock):
    me, _ = users
    ask(client, use_provider, me, *proposing(ids), message="What should I do today?")
    clock.now += timedelta(minutes=10)
    latest, _ = ask(
        client, use_provider, me, *proposing(ids, push_up_sets=2), message="A shorter one?"
    )

    _, provider = ask(client, use_provider, me, *reading_it())

    read = received(provider, 1)["get_pending_proposal"]["output"]
    assert read["exercises"][2]["sets"] == 2
    assert read["earlier_proposals_awaiting_approval"] == 1
    assert "for 30 more minutes" in instructions_of(provider)
    assert latest["proposal"]["exercises"][2]["sets"] == 2


def test_the_same_workout_is_not_proposed_again_while_it_waits(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    ask(client, use_provider, me, *proposing(ids), message="What should I do today?")

    # "show me the final proposal": the model proposes the same workout again
    *before, _ = proposing(ids)
    body, provider = ask(
        client,
        use_provider,
        me,
        *before,
        respond_turn(
            "Your proposal is still waiting for you to review and approve in Formiq.",
            "WORKOUT_PLAN",
            "CANNOT_ANSWER",
        ),
        message="Show me the final proposal.",
    )

    refused = received(provider, 3)["propose_workout_plan"]["error"]
    assert refused["code"] == "INVALID_INPUT"
    assert refused["message"].startswith(
        "this workout is the one already awaiting the user's approval, unchanged"
    )
    assert "proposal" not in body
    with Session(test_engine) as session:
        assert len(session.scalars(select(WorkoutPlanProposal).where(
            WorkoutPlanProposal.user_id == me
        )).all()) == 1  # fmt: skip


def test_a_revision_awaiting_approval_says_what_it_changes(
    client, use_provider, me, plan_id, ids, test_engine
):
    ask(client, use_provider, me, *rewriting(ids, plan_id, *CORE_PLAN), message=REWRITE)

    _, provider = ask(client, use_provider, me, *reading_it("It changes the sets."))

    assert f"approving it would replace their saved plan {plan_id}" in instructions_of(provider)
    read = received(provider, 1)["get_pending_proposal"]["output"]
    assert read["revision"] == {
        "replaces_plan_id": plan_id,
        "replaces_plan_name": "Core & Abs Focus",
        "kind": "ALTERNATIVE",
        "kept_exercises": list(CORE_PLAN),
    }
    assert read["replaced_plan_unchanged"] is True
    changes = read["changes"]
    assert changes["compared_with_plan_id"] == plan_id
    # the plan's three exercises, 3 sets of 12 then; 4 sets of 10 now
    assert [
        (item["exercise_name"], item["before"], item["after"]) for item in changes["changed"]
    ] == [
        (name, "3 sets of 12 reps, 90 s rest", "4 sets of 10 reps, 60 s rest")
        for name in CORE_PLAN
    ]
    assert [item["exercise_name"] for item in changes["added"]] == ["Brisk Walk", "Brisk Walk"]
    assert (changes["removed"], changes["unchanged"], changes["identical"]) == ([], [], False)
    assert read["coverage"]["focus"] == "CORE"

    # the plan changed since: the proposal says its approval would fail
    with Session(test_engine) as session:
        session.get(WorkoutPlan, plan_id).name = "Renamed"
        session.commit()
    _, provider = ask(client, use_provider, me, *reading_it("It changes the sets."))
    read = received(provider, 1)["get_pending_proposal"]["output"]
    assert read["replaced_plan_unchanged"] is False


def test_what_a_proposal_is_for_is_kept_with_it(
    client, use_provider, me, plan_id, ids, test_engine
):
    body, _ = ask(
        client, use_provider, me, *rewriting(ids, plan_id, *CORE_PLAN), message=REWRITE
    )

    with Session(test_engine) as session:
        stored = session.get(WorkoutPlanProposal, body["proposal"]["proposal_id"])
        values = stored.parameters
    assert (values["focus"], values["revision"], values["replaces_plan_id"]) == (
        "CORE",
        "ALTERNATIVE",
        plan_id,
    )
    # and the binding still covers it all: the approval saves it
    assert approve(client, me, body["proposal"]).status_code == 201


# --- the saved plans ---


def run(tools, user, name, **arguments):
    (result,) = tools.run([ToolCall(name=name, arguments=arguments)], user_id=user.id)
    return result


def summaries(result):
    return [
        (item["name"], item["status"], item["is_current"]) for item in result["output"]["plans"]
    ]


def test_none_one_or_many_saved_plans_are_listed(tools, db_session, ids):
    user = add_user(db_session, "plans@example.com")
    them = add_user(db_session, "plans-them@example.com")
    core_plan(db_session, them.id, ids)

    none = run(tools, user, "list_workout_plans")["output"]
    assert (none["plans"], none["count"], none["total"], none["planned"]) == ([], 0, 0, 0)

    today = core_plan(db_session, user.id, ids)
    one = run(tools, user, "list_workout_plans")
    assert summaries(one) == [("Core & Abs Focus", "PLANNED", True)]
    assert one["output"]["plans"][0]["main_exercises"] == list(CORE_PLAN)
    assert one["output"]["plans"][0]["days_from_today"] == 0

    def plan(name, days, status="PLANNED"):
        added = core_plan(db_session, user.id, ids, status=status)
        added.name, added.scheduled_date = name, TODAY + timedelta(days=days)
        db_session.flush()
        return added

    plan("Last Week", -7)
    plan("Next Week", 7)
    plan("Tomorrow", 1)
    plan("Old Draft", 3, status="DRAFT")
    plan("Dropped", 2, status="CANCELLED")

    many = run(tools, user, "list_workout_plans")
    # PLANNED first, the next one first, then the past ones; then the others
    assert summaries(many) == [
        ("Core & Abs Focus", "PLANNED", True),
        ("Tomorrow", "PLANNED", False),
        ("Next Week", "PLANNED", False),
        ("Last Week", "PLANNED", False),
        ("Old Draft", "DRAFT", False),
        ("Dropped", "CANCELLED", False),
    ]
    assert (many["output"]["count"], many["output"]["planned"]) == (6, 4)
    planned = run(tools, user, "list_workout_plans", status="PLANNED")
    assert [name for name, _, _ in summaries(planned)] == [
        "Core & Abs Focus", "Tomorrow", "Next Week", "Last Week",
    ]  # fmt: skip
    # never another user's
    assert today.id in {item["plan_id"] for item in many["output"]["plans"]}
    assert run(tools, them, "list_workout_plans")["output"]["count"] == 1


def test_two_plans_are_compared_by_formiq(tools, db_session, ids):
    user = add_user(db_session, "compare@example.com")
    before = core_plan(db_session, user.id, ids)
    after = core_plan(db_session, user.id, ids, "Bird Dog", "Band Pallof Press", "Glute Bridge")
    after.exercises[0].sets = 4
    after.name = "Core & Abs Focus (Alternative)"
    db_session.flush()

    result = run(tools, user, "get_workout_plan", plan_id=after.id, compare_with_plan_id=before.id)

    assert result["output"]["changes"] == {
        "compared_with_plan_id": before.id,
        "compared_with_plan_name": "Core & Abs Focus",
        "added": [
            {
                "section": "MAIN_WORKOUT",
                "exercise_name": "Glute Bridge",
                "before": None,
                "after": "3 sets of 12 reps, 90 s rest",
            }
        ],
        "removed": [
            {
                "section": "MAIN_WORKOUT",
                "exercise_name": "Cable Woodchop",
                "before": "3 sets of 12 reps, 90 s rest",
                "after": None,
            }
        ],
        "changed": [
            {
                "section": "MAIN_WORKOUT",
                "exercise_name": "Bird Dog",
                "before": "3 sets of 12 reps, 90 s rest",
                "after": "4 sets of 12 reps, 90 s rest",
            }
        ],
        "unchanged": ["Band Pallof Press"],
        "name_changed": True,
        "scheduled_date_changed": False,
        "identical": False,
    }
    same = run(tools, user, "get_workout_plan", plan_id=before.id, compare_with_plan_id=before.id)
    assert same["output"]["changes"]["identical"] is True
    # never with another user's plan
    them = add_user(db_session, "compare-them@example.com")
    theirs = core_plan(db_session, them.id, ids)
    other = run(tools, user, "get_workout_plan", plan_id=before.id, compare_with_plan_id=theirs.id)
    assert other["error"] == {
        "code": "RESOURCE_NOT_FOUND",
        "message": f"the user has no workout plan {theirs.id}",
    }


# --- which plan to change ---


@pytest.fixture
def two_plans(db_session, ids):
    """A user with two PLANNED plans: today's core plan, and a later one."""
    user = add_user(db_session, "which@example.com")
    today = core_plan(db_session, user.id, ids)
    later = core_plan(db_session, user.id, ids)
    later.name, later.scheduled_date = "Saturday Core", TODAY + timedelta(days=4)
    db_session.flush()
    return user, today, later


def tools_in(tools, *turns):
    """The tools of a request in this conversation: (role, text) turns, the
    user's message last."""
    tools.conversation = list(turns)
    tools.user_words = [text for role, text in turns if role == "user"]
    return tools


def revise(tools, user, plan, ids):
    (result,) = tools.run(
        [
            ToolCall(
                name="propose_workout_plan",
                arguments=revision_of(plan.id, "ALTERNATIVE", ids, *CORE_PLAN, sets=4),
            )
        ],
        user_id=user.id,
    )
    return result


@pytest.mark.parametrize("which", ["today", "later"])
def test_with_two_plans_and_nothing_to_tell_them_apart_formiq_asks(
    tools, ids, two_plans, which
):
    user, today, later = two_plans
    tools_in(tools, ("user", "Change my workout."))

    result = revise(tools, user, today if which == "today" else later, ids)

    assert problem(result) == (
        f"the user has 2 PLANNED plans (plan {today.id}, 'Core & Abs Focus', on "
        f"{TODAY.isoformat()}; plan {later.id}, 'Saturday Core', on "
        f"{(TODAY + timedelta(days=4)).isoformat()}) and has not made clear which one they "
        "want changed: do not choose one for them; ask which one, with ASK_CLARIFICATION, "
        "naming them"
    )
    assert tools.proposals == []


@pytest.mark.parametrize(
    ("turns", "which"),
    [
        # named by the user, or by the coach in the conversation
        ((("user", "Rewrite Saturday Core, please."),), "later"),
        ((("coach", "You have Core & Abs Focus today."), ("user", "Rewrite it.")), "today"),
        # by its id
        ((("user", "Rewrite plan {later}"),), "later"),
        # today's or the next workout: the current plan
        ((("user", "Make today's workout different."),), "today"),
        ((("user", "Can you change my next workout?"),), "today"),
    ],
)
def test_a_plan_the_conversation_makes_clear_is_revised(tools, ids, two_plans, turns, which):
    user, today, later = two_plans
    turns = [(role, text.format(later=later.id)) for role, text in turns]
    tools_in(tools, *turns)

    result = revise(tools, user, today if which == "today" else later, ids)

    assert "output" in result, result
    assert result["output"]["revision"]["replaces_plan_id"] == (
        today.id if which == "today" else later.id
    )


def test_one_plan_needs_no_question(tools, db_session, ids):
    user = add_user(db_session, "one-plan@example.com")
    plan = core_plan(db_session, user.id, ids)
    tools_in(tools, ("user", "Change my workout."))

    assert "output" in revise(tools, user, plan, ids)
