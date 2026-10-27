"""A coach request that names the saved plan the user is changing
(`workout_plan_id`): checked before the model is asked anything, told to the
model by its number, and the only plan a proposal of the request may revise.

The plan must be the user's own and PLANNED (404 for another user's, like a
missing one; 409 for a DRAFT or CANCELLED one). A proposal that revises another
plan, or none, is refused by the tools, so the coach corrects it within the turn
or proposes nothing; the conversation no longer has to name the plan. A request
without the field is as it always was.

The model is scripted: no test calls Gemini, so none of this shows how a real
model behaves, only what Formiq enforces whatever it does. They require the
local PostgreSQL container to be running.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.graph import target_note
from app.models import WorkoutPlanProposal
from tests.auth import bearer
from tests.coach import call, respond_turn, tool_turn
from tests.integration.test_coach_daily import TODAY, daily_reads, received, recommend
from tests.integration.test_coach_follow_ups import (  # noqa: F401 (fixtures)
    instructions_of,
    revise,
    tools_in,
    two_plans,
)
from tests.integration.test_plan_proposals import problem, proposal
from tests.integration.test_plan_revisions import (  # noqa: F401 (fixtures)
    CORE_PLAN,
    clock,
    core_plan,
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

CHANGE = "Make it a little harder."


def new_workout(ids):
    """The core workout of revision_of, proposed as a new one: it revises no plan."""
    return {
        key: value
        for key, value in revision_of(0, "ALTERNATIVE", ids, *CORE_PLAN).items()
        if key not in ("revises_plan_id", "revision")
    }


def ask(client, use_provider, user_id, *turns, message=CHANGE, **body):
    provider = use_provider(*turns)
    response = client.post(
        "/coach/message", headers=bearer(user_id), json={"message": message, **body}
    )
    return response, provider


@pytest.fixture
def later_id(me, ids, test_engine, plan_id):
    """Another PLANNED plan of the user's, three days after today's (plan_id)."""
    with Session(test_engine) as session:
        later = core_plan(session, me, ids)
        later.name = "Saturday Core"
        later.scheduled_date = TODAY + timedelta(days=3)
        session.commit()
        return later.id


def reads(*extra):
    """A model's first turn: what today needs (the plan among it), and the core and warm-up
    exercises its proposal is made of (their ids are the ones a proposal may use)."""
    return daily_reads(
        call("search_exercises", use="MAIN_WORKOUT", muscle="Core"),
        call("search_exercises", use="WARM_UP"),
        *extra,
    )


def revising(ids, plan, *, sets=4):
    """A model that reads, proposes a revision of plan, then replies."""
    return (
        reads(),
        tool_turn(proposal(**revision_of(plan, "ALTERNATIVE", ids, *CORE_PLAN, sets=sets))),
        recommend("Here is another version of your core workout. Approving it replaces the plan."),
    )


def stored_proposals(test_engine, user_id):
    with Session(test_engine) as session:
        return session.scalars(
            select(WorkoutPlanProposal.parameters).where(WorkoutPlanProposal.user_id == user_id)
        ).all()


# --- the tools: a proposal revises the plan the request names ---


def test_a_proposal_revises_the_plan_the_request_names(tools, ids, two_plans):
    user, today_plan, later = two_plans
    # nothing in the conversation tells the two plans apart
    tools_in(tools, ("user", "Change my workout."))
    tools.target_plan_id = later.id

    result = revise(tools, user, later, ids)

    assert result["output"]["revision"]["replaces_plan_id"] == later.id


def test_the_same_proposal_without_the_plan_named_is_not_made_clear(tools, ids, two_plans):
    user, _, later = two_plans
    tools_in(tools, ("user", "Change my workout."))

    assert "has not made clear which one" in problem(revise(tools, user, later, ids))


def test_a_proposal_that_revises_another_plan_is_refused(tools, ids, two_plans):
    user, today_plan, later = two_plans
    # the user even named the later plan in words: the request's plan is the one
    tools_in(tools, ("user", "Rewrite Saturday Core, please."))
    tools.target_plan_id = today_plan.id

    result = revise(tools, user, later, ids)

    assert problem(result).startswith(f"the user is changing workout plan {today_plan.id}: ")
    assert f"revises_plan_id {today_plan.id}" in problem(result)
    assert tools.proposals == []


def test_a_proposal_that_revises_nothing_is_refused(tools, ids, two_plans):
    user, today_plan, _ = two_plans
    tools_in(tools, ("user", "Give me something else."))
    tools.target_plan_id = today_plan.id
    (result,) = tools.run([proposal(**new_workout(ids))], user_id=user.id)

    assert problem(result).startswith(f"the user is changing workout plan {today_plan.id}: ")
    assert tools.proposals == []


def test_a_request_that_names_no_plan_may_propose_a_new_workout(tools, ids, two_plans):
    user, _, _ = two_plans
    tools_in(tools, ("user", "Give me something else."))
    (result,) = tools.run([proposal(**new_workout(ids))], user_id=user.id)

    assert "output" in result, result
    assert result["output"].get("revision") is None


# --- the coach: the request's plan is the plan revised ---


def test_the_coach_revises_the_named_plan_though_nothing_names_it(
    client, use_provider, me, plan_id, later_id, ids, test_engine
):
    # the later plan is in no tool result of the turn and not in the message: only the request names it
    response, provider = ask(
        client, use_provider, me, *revising(ids, later_id), workout_plan_id=later_id
    )

    assert response.status_code == 200, response.json()
    shown = response.json()["proposal"]
    assert shown["revision"]["replaces_plan_id"] == later_id
    assert shown["revision"]["replaces_plan_name"] == "Saturday Core"
    (stored,) = stored_proposals(test_engine, me)
    assert stored["replaces_plan_id"] == later_id
    assert "output" in received(provider, 2)["propose_workout_plan"]


def test_without_the_field_the_same_turn_is_refused_as_before(
    client, use_provider, me, plan_id, later_id, ids, test_engine
):
    response, provider = ask(
        client,
        use_provider,
        me,
        reads(),
        tool_turn(proposal(**revision_of(later_id, "ALTERNATIVE", ids, *CORE_PLAN, sets=4))),
        respond_turn("I could not change that workout.", "WORKOUT_PLAN", "CANNOT_ANSWER"),
    )

    assert response.status_code == 200
    # an id nobody gave: the later plan was read by no tool, and the user did not write it
    assert received(provider, 2)["propose_workout_plan"]["error"]["code"] == "ID_NOT_GROUNDED"
    assert "proposal" not in response.json()
    assert stored_proposals(test_engine, me) == []


def test_a_model_that_proposes_another_plan_is_corrected_within_the_turn(
    client, use_provider, me, plan_id, later_id, ids, test_engine
):
    # both plans are read, so both ids are known: only the request tells which is the one
    response, provider = ask(
        client,
        use_provider,
        me,
        reads(call("list_workout_plans")),
        tool_turn(proposal(**revision_of(later_id, "ALTERNATIVE", ids, *CORE_PLAN, sets=4))),
        tool_turn(proposal(**revision_of(plan_id, "ALTERNATIVE", ids, *CORE_PLAN, sets=4))),
        recommend("Here is another version of your core workout."),
        workout_plan_id=plan_id,
    )

    assert response.status_code == 200, response.json()
    refused = received(provider, 2)["propose_workout_plan"]["error"]
    assert refused["code"] == "INVALID_INPUT"
    assert refused["message"].startswith(f"the user is changing workout plan {plan_id}: ")
    assert response.json()["proposal"]["revision"]["replaces_plan_id"] == plan_id
    (stored,) = stored_proposals(test_engine, me)
    assert stored["replaces_plan_id"] == plan_id


def test_a_model_that_never_revises_the_named_plan_proposes_nothing(
    client, use_provider, me, plan_id, later_id, ids, test_engine
):
    response, provider = ask(
        client,
        use_provider,
        me,
        reads(call("list_workout_plans")),
        tool_turn(proposal(**revision_of(later_id, "ALTERNATIVE", ids, *CORE_PLAN, sets=4))),
        respond_turn(
            "I could not change that workout.", "WORKOUT_PLAN", "CANNOT_ANSWER"
        ),
        workout_plan_id=plan_id,
    )

    assert response.status_code == 200
    assert "proposal" not in response.json()
    assert stored_proposals(test_engine, me) == []


def test_a_new_workout_is_refused_for_a_request_that_names_a_plan(
    client, use_provider, me, plan_id, ids, test_engine
):
    new = new_workout(ids)
    response, provider = ask(
        client,
        use_provider,
        me,
        reads(),
        tool_turn(proposal(**new)),
        tool_turn(proposal(**revision_of(plan_id, "ADJUST", ids, *CORE_PLAN, sets=4))),
        recommend("Here is your core workout with an extra set. Approving it replaces the plan."),
        workout_plan_id=plan_id,
    )

    assert response.status_code == 200, response.json()
    assert received(provider, 2)["propose_workout_plan"]["error"]["code"] == "INVALID_INPUT"
    assert response.json()["proposal"]["revision"]["replaces_plan_id"] == plan_id
    assert len(stored_proposals(test_engine, me)) == 1


def test_the_model_is_told_of_the_plan_by_its_number_never_its_name(
    client, use_provider, me, plan_id, later_id, ids
):
    response, provider = ask(
        client, use_provider, me, *revising(ids, later_id), workout_plan_id=later_id
    )

    instructions = instructions_of(provider)
    assert target_note(later_id) in instructions
    assert "Saturday Core" not in instructions
    assert "Core & Abs Focus" not in instructions
    # a request that names none is told nothing of one
    _, other = ask(client, use_provider, me, respond_turn("Fine."))
    assert "opened their saved workout plan" not in instructions_of(other)


# --- before the model: the plan must be the user's own and PLANNED ---


@pytest.mark.parametrize("status", ["CANCELLED", "DRAFT"])
def test_a_plan_that_is_not_planned_is_refused_before_the_model(
    client, use_provider, me, ids, test_engine, status
):
    with Session(test_engine) as session:
        plan = core_plan(session, me, ids, status=status)
        session.commit()
        unfit = plan.id

    response, provider = ask(client, use_provider, me, respond_turn("x"), workout_plan_id=unfit)

    assert response.status_code == 409
    assert response.json() == {
        "detail": f"workout plan {unfit} is {status}: only a PLANNED workout plan can be changed "
        "with the coach"
    }
    provider.generate_turn.assert_not_called()
    assert stored_proposals(test_engine, me) == []


def test_another_users_plan_is_not_told_apart_from_a_missing_one(
    client, use_provider, users, ids, test_engine
):
    me, them = users
    with Session(test_engine) as session:
        theirs = core_plan(session, them, ids).id
        session.commit()
    missing = theirs + 100_000

    stranger, provider = ask(client, use_provider, me, respond_turn("x"), workout_plan_id=theirs)
    nobody, _ = ask(client, use_provider, me, respond_turn("x"), workout_plan_id=missing)

    assert stranger.status_code == nobody.status_code == 404
    assert stranger.json() == {"detail": f"user {me} has no workout plan {theirs}"}
    assert nobody.json() == {"detail": f"user {me} has no workout plan {missing}"}
    provider.generate_turn.assert_not_called()
    # theirs is untouched, and nothing was proposed to either
    assert stored_proposals(test_engine, them) == stored_proposals(test_engine, me) == []


@pytest.mark.parametrize(
    "plan",
    [0, -1, "7", "seven", 7.5, 7.0, True, 2**31, [7], {"id": 7}],
    ids=["zero", "negative", "text number", "word", "float", "whole float", "bool", "too big", "list", "object"],
)
def test_a_plan_id_that_is_not_a_positive_integer_is_refused(
    client, use_provider, me, plan_id, plan
):
    response, provider = ask(client, use_provider, me, respond_turn("x"), workout_plan_id=plan)

    assert response.status_code == 422
    provider.generate_turn.assert_not_called()


def test_a_null_plan_is_no_plan(client, use_provider, me, plan_id):
    response, provider = ask(
        client, use_provider, me, respond_turn("Start with three sets."), workout_plan_id=None
    )

    assert (response.status_code, response.json()) == (200, {"reply": "Start with three sets."})
    assert "opened their saved workout plan" not in instructions_of(provider)


def test_the_plan_is_checked_for_the_user_of_the_token(client, use_provider, users, ids, test_engine):
    me, them = users
    with Session(test_engine) as session:
        mine = core_plan(session, me, ids).id
        session.commit()

    # the plan is mine: they get a 404, I get an answer
    stranger, _ = ask(client, use_provider, them, respond_turn("x"), workout_plan_id=mine)
    owner, _ = ask(client, use_provider, me, respond_turn("Fine."), workout_plan_id=mine)

    assert (stranger.status_code, owner.status_code) == (404, 200)


# --- what the field never changes ---


def test_a_flagged_request_for_a_named_plan_is_answered_with_the_safe_redirect(
    client, use_provider, me, plan_id
):
    redirect = "I can't advise on that. Please see a physiotherapist; gentle walking is fine."
    response, provider = ask(
        client,
        use_provider,
        me,
        respond_turn(redirect, "SAFETY_SENSITIVE", "SAFE_REDIRECT"),
        message="I have sharp knee pain, make this workout easier",
        workout_plan_id=plan_id,
    )

    assert (response.status_code, response.json()) == (200, {"reply": redirect})
    # read nothing, and not told of the plan
    assert "opened their saved workout plan" not in instructions_of(provider)
    assert [tool.name for tool in provider.generate_turn.call_args_list[0].kwargs["tools"]] == [
        "respond"
    ]


def test_a_flagged_request_still_cannot_name_a_plan_it_may_not_change(
    client, use_provider, users, ids, test_engine
):
    me, them = users
    with Session(test_engine) as session:
        theirs = core_plan(session, them, ids).id
        session.commit()

    response, provider = ask(
        client,
        use_provider,
        me,
        respond_turn("x"),
        message="I have sharp knee pain, make this workout easier",
        workout_plan_id=theirs,
    )

    assert response.status_code == 404
    provider.generate_turn.assert_not_called()


def test_a_named_plan_does_not_authorize_anything(
    client, use_provider, me, plan_id, ids, test_engine
):
    """The proposal is only a proposal: the plan is replaced by the user's approval."""
    response, _ = ask(client, use_provider, me, *revising(ids, plan_id), workout_plan_id=plan_id)

    assert response.status_code == 200
    assert stored_plans_of(test_engine, me) == [(plan_id, "PLANNED")]


def stored_plans_of(test_engine, user_id):
    from tests.integration.test_plan_revisions import stored_plans

    return stored_plans(test_engine, user_id)


def test_the_coach_with_a_named_plan_still_asks_nothing_of_the_provider_it_would_not(
    client, use_provider, me, plan_id
):
    """The request sends the model one more note, nothing else: the tools it may call are the same."""
    _, plain = ask(client, use_provider, me, respond_turn("Fine."))
    _, named = ask(client, use_provider, me, respond_turn("Fine."), workout_plan_id=plan_id)

    first = {
        name: [tool.name for tool in provider.generate_turn.call_args_list[0].kwargs["tools"]]
        for name, provider in (("plain", plain), ("named", named))
    }
    assert first["plain"] == first["named"]
