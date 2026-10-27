"""A proposal never silently drops a saved weight, and never chooses one (Phase 2.5).

A saved plan may carry a weight on an exercise, but a proposal could set none, so every
revision dropped the plan's weights (the Phase 2.4 live pass): Key Changes showed "15 kg to no
weight" and the saved plan lost them, and the coach sometimes promised to "update the weight"
it could not represent. Now:

- a revision carries on the weight the saved plan has for the same exercise (section and
  name), whatever the model left out;
- the model may set a weight only when it rests on the user's words (a figure of theirs in kg
  or lb, or the plan's own weight moved by one), and take one off only when they asked for
  none (app.tools.weights): "make it heavier" gets a question, never a number a model chose;
- the proposal, its comparison (Key Changes), the stored proposal, the pending list and the
  plan an approval saves all carry the same weights.

No migration: workout_plan_exercises.weight_kg already holds it.

The model is scripted: no test calls Gemini, so none of this shows what a real model does, only
what Formiq enforces whatever it does. They require the local PostgreSQL container to be
running.
"""

import pytest
from sqlalchemy.orm import Session

from app.models import WorkoutPlan
from tests.auth import bearer
from tests.coach import call, respond_turn, tool_turn
from tests.integration.test_coach_daily import received, recommend
from tests.integration.test_coach_follow_ups import tools_in
from tests.integration.test_coach_target import ask, reads, stored_proposals
from tests.integration.test_plan_proposals import approve, problem, proposal, propose
from tests.integration.test_plan_revisions import (  # noqa: F401 (fixtures)
    CORE_PLAN,
    clock,
    ids,
    me,
    more_core,
    revision_of,
    saved_as_proposed,
    terms,
    today,
    tools,
    use_provider,
    use_terms,
    users,
)
from tests.integration.workout_plans import add_user

REPLY = "Here is another version of your core workout. Approving it in Formiq replaces the plan."


def weighted_plan(session, user_id, ids, **kilos):
    """A PLANNED plan holding exactly the workout revision_of describes, each named main
    exercise (keyword, underscores for spaces) lifting that many kg."""
    as_saved = revision_of(None, "ADJUST", ids, *CORE_PLAN)
    plan = saved_as_proposed(session, user_id, as_saved)
    by_id = {ids[name.replace("_", " ")]: kg for name, kg in kilos.items()}
    for item in plan.exercises:
        if item.section == "MAIN_WORKOUT" and item.exercise_id in by_id:
            item.weight_kg = by_id[item.exercise_id]
    session.flush()
    return plan, {**as_saved, "revises_plan_id": plan.id}


def main_weights(output):
    return [item["weight_kg"] for item in output["exercises"] if item["section"] == "MAIN_WORKOUT"]


def stored_weights(kept):
    """The weights as kept for the approval: a weight only where there is one."""
    return {
        item["exercise_id"]: item.get("weight_kg") for item in kept.values()["exercises"]
    }


# --- the proposal tool: a weight is carried on, never lost by omission ---


def test_a_revision_carries_on_the_weights_the_plan_has(tools, db_session, ids):
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids, Cable_Woodchop=15.0, Bird_Dog=8.0)
    tools_in(tools, ("user", "Make it a little harder."))
    harder = revision_of(plan.id, "ADJUST", ids, *CORE_PLAN, sets=4)

    result = propose(tools, user, **harder)

    # the model left every weight out: the plan's own are kept, and none is added
    assert main_weights(result["output"]) == [8.0, None, 15.0]
    (kept, _) = tools.proposals[0]
    assert stored_weights(kept) == {
        ids["Brisk Walk"]: None,
        ids["Bird Dog"]: 8.0,
        ids["Band Pallof Press"]: None,
        ids["Cable Woodchop"]: 15.0,
    }
    # a weight that is none is not stored at all
    assert all("weight_kg" not in item or item["weight_kg"] for item in kept.values()["exercises"])


def test_a_proposal_that_only_omits_the_weights_is_unchanged_not_a_weight_loss(
    tools, db_session, ids
):
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids, Cable_Woodchop=15.0)
    tools_in(tools, ("user", "Make it a little harder."))

    refused = propose(tools, user, **same)

    assert "unchanged" in problem(refused)
    assert tools.proposals == []


def test_the_weight_of_a_warm_up_or_cool_down_activity_is_carried_on_too(tools, db_session, ids):
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids)
    for item in plan.exercises:
        if item.section == "WARM_UP":
            item.weight_kg = 2.5
    db_session.flush()
    tools_in(tools, ("user", "Make it a little harder."))

    result = propose(tools, user, **revision_of(plan.id, "ADJUST", ids, *CORE_PLAN, sets=4))

    warm_up = [item for item in result["output"]["exercises"] if item["section"] == "WARM_UP"]
    assert [item["weight_kg"] for item in warm_up] == [2.5]


def test_a_weight_of_another_exercise_is_not_carried_to_one_that_replaced_it(
    tools, db_session, ids, more_core
):
    ids = more_core
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids, Cable_Woodchop=15.0, Bird_Dog=8.0)
    tools_in(tools, ("user", "Swap the woodchop for a dead bug."))
    # a core workout needs four different exercises: the side plank is a fourth, new one
    swapped = revision_of(
        plan.id, "ADJUST", ids, "Bird Dog", "Band Pallof Press", "Test Dead Bug", "Test Side Plank"
    )

    result = propose(tools, user, **swapped)

    # the bird dog keeps its weight; the dead bug takes the woodchop's place without it
    assert main_weights(result["output"]) == [8.0, None, None, None]


# --- the user's words: a weight is theirs, or it is refused ---


def test_a_weight_the_user_gave_is_set_and_is_a_change_on_its_own(tools, db_session, ids):
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids, Cable_Woodchop=15.0)
    tools_in(tools, ("user", "Make the woodchop 20 kg."))
    args = {**same, "exercises": [*same["exercises"][:2], {**same["exercises"][2], "weight_kg": 20}]}

    result = propose(tools, user, **args)

    assert main_weights(result["output"]) == [None, None, 20.0]
    assert result["output"]["revision"]["kind"] == "ADJUST"


def test_the_plans_weight_moved_by_a_figure_the_user_gave_is_theirs(tools, db_session, ids):
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids, Cable_Woodchop=15.0)
    tools_in(tools, ("user", "Add 5 kg to the woodchop."))
    args = {**same, "exercises": [*same["exercises"][:2], {**same["exercises"][2], "weight_kg": 20.0}]}

    assert main_weights(propose(tools, user, **args)["output"]) == [None, None, 20.0]


def test_a_weight_in_pounds_may_be_rounded(tools, db_session, ids):
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids)
    tools_in(tools, ("user", "Use a 45 lb weight for the woodchop."))
    lifted = lambda kg: {  # noqa: E731
        **same,
        "exercises": [*same["exercises"][:2], {**same["exercises"][2], "weight_kg": kg}],
    }

    assert main_weights(propose(tools, user, **lifted(20.4))["output"]) == [None, None, 20.4]
    assert "did not give a weight of 25 kg" in problem(propose(tools, user, **lifted(25.0)))


def test_a_weight_the_user_never_gave_is_refused_and_the_plans_is_kept(tools, db_session, ids):
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids, Cable_Woodchop=15.0)
    tools_in(tools, ("user", "Make it heavier."))
    args = {**same, "exercises": [*same["exercises"][:2], {**same["exercises"][2], "weight_kg": 20}]}

    refused = propose(tools, user, **args)

    # the weight is refused, and kept: so nothing else differs, which is said too
    assert problem(refused).startswith(
        f"exercise {ids['Cable Woodchop']} (Cable Woodchop): the user did not give a weight of "
        "20 kg, and you never choose one: leave weight_kg out and the revision keeps the plan's "
        "15 kg; when they want a heavier or lighter weight without saying which, ask them how "
        "many kg (ASK_CLARIFICATION)"
    )
    assert tools.proposals == []


def test_a_new_workout_may_not_be_given_a_weight_the_user_never_gave(tools, db_session, ids):
    user = add_user(db_session, "weights@example.com")
    tools_in(tools, ("user", "Give me a core workout."))
    as_new = {k: v for k, v in revision_of(None, "ADJUST", ids, *CORE_PLAN).items() if k not in ("revises_plan_id", "revision")}
    args = {**as_new, "exercises": [{**as_new["exercises"][0], "weight_kg": 10}, *as_new["exercises"][1:]]}

    assert "did not give a weight of 10 kg" in problem(propose(tools, user, **args))
    tools_in(tools, ("user", "Give me a core workout with a 10 kg weight on the first one."))
    assert main_weights(propose(tools, user, **args)["output"]) == [10.0, None, None]


@pytest.mark.parametrize("given", [True, "20", 0, -5, 501, float("nan")])
def test_a_weight_that_is_not_a_plausible_number_is_refused_whatever_the_user_said(
    tools, db_session, ids, given
):
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids)
    tools_in(tools, ("user", "Make the woodchop 20 kg, or 501 kg, or 0 kg."))
    args = {**same, "exercises": [*same["exercises"][:2], {**same["exercises"][2], "weight_kg": given}]}

    assert "weight_kg" in problem(propose(tools, user, **args))
    assert tools.proposals == []


def test_a_weight_and_its_removal_together_are_refused(tools, db_session, ids):
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids, Cable_Woodchop=15.0)
    tools_in(tools, ("user", "Make the woodchop 20 kg, no weights."))
    both = {**same["exercises"][2], "weight_kg": 20, "remove_weight": True}

    assert "not both" in problem(propose(tools, user, **{**same, "exercises": [*same["exercises"][:2], both]}))


def test_without_a_conversation_no_weight_is_set_and_none_is_removed(tools, db_session, ids):
    """Fail closed, as for a day: with no words there is nothing for a weight to rest on."""
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids, Cable_Woodchop=15.0)
    tools.conversation = None
    tools.user_words = None
    heavier = {**same["exercises"][2], "weight_kg": 20}
    bare = {**same["exercises"][2], "remove_weight": True}

    assert "did not give a weight" in problem(
        propose(tools, user, **{**same, "exercises": [*same["exercises"][:2], heavier]})
    )
    assert "did not ask for no weight" in problem(
        propose(tools, user, **{**same, "exercises": [*same["exercises"][:2], bare]})
    )
    # the plan's own weight is carried on all the same
    kept = propose(
        tools, user, **revision_of(plan.id, "ADJUST", ids, *CORE_PLAN, sets=4)
    )
    assert main_weights(kept["output"]) == [None, None, 15.0]


# --- taking a weight off ---


def test_a_weight_is_taken_off_only_when_the_user_asked_for_none(tools, db_session, ids):
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids, Cable_Woodchop=15.0)
    bare = {**same, "exercises": [*same["exercises"][:2], {**same["exercises"][2], "remove_weight": True}]}

    tools_in(tools, ("user", "Make it a little harder."))
    refused = propose(tools, user, **bare)
    tools_in(tools, ("user", "Do the woodchop without the weight."))
    removed = propose(tools, user, **bare)

    assert problem(refused).startswith(
        f"exercise {ids['Cable Woodchop']} (Cable Woodchop): the user did not ask for no weight, "
        "and the plan has 15 kg for it: leave remove_weight out and the revision keeps the weight"
    )
    # the removal is the revision: nothing else differs, and it is not "unchanged"
    assert main_weights(removed["output"]) == [None, None, None]


def test_removing_a_weight_the_plan_does_not_have_is_harmless(tools, db_session, ids):
    user = add_user(db_session, "weights@example.com")
    plan, same = weighted_plan(db_session, user.id, ids, Cable_Woodchop=15.0)
    tools_in(tools, ("user", "No weights, and make it harder."))
    bare = {**same["exercises"][0], "remove_weight": True}
    args = {**revision_of(plan.id, "ADJUST", ids, *CORE_PLAN, sets=4)}
    args["exercises"] = [{**bare, "sets": 4}, *args["exercises"][1:]]

    assert main_weights(propose(tools, user, **args)["output"])[0] is None


# --- through the API: shown, compared, pending and saved agree ---


def moving_weight(ids, plan_id, **item):
    """A model that reads, proposes the plan's own workout with this change to the
    woodchop (its third main exercise), and replies."""
    args = revision_of(plan_id, "ADJUST", ids, *CORE_PLAN)
    args["exercises"] = [*args["exercises"][:2], {**args["exercises"][2], **item}]
    return reads(), tool_turn(proposal(**args)), recommend(REPLY)


@pytest.fixture
def weighted_plan_id(me, ids, test_engine):
    with Session(test_engine) as session:
        plan, _ = weighted_plan(session, me, ids, Cable_Woodchop=15.0, Bird_Dog=8.0)
        session.commit()
        return plan.id


def test_a_weight_only_change_is_shown_as_a_change_stored_listed_and_saved_exactly(
    client, use_provider, me, ids, test_engine, weighted_plan_id
):
    response, _ = ask(
        client,
        use_provider,
        me,
        *moving_weight(ids, weighted_plan_id, weight_kg=20),
        message="Make the woodchop 20 kg.",
        workout_plan_id=weighted_plan_id,
    )

    assert response.status_code == 200, response.json()
    shown = response.json()["proposal"]
    # the proposal's exercises carry the weights it would save (always given, null for none)
    assert [(item["exercise_name"], item["weight_kg"]) for item in shown["exercises"]] == [
        ("Brisk Walk", None),
        ("Bird Dog", 8.0),
        ("Band Pallof Press", None),
        ("Cable Woodchop", 20.0),
        ("Brisk Walk", None),
    ]
    # Key Changes: the one exercise whose weight changed, with the real before and after
    changes = shown["changes"]
    (changed,) = changes["changed"]
    assert changed["exercise_name"] == "Cable Woodchop"
    assert (changed["before"]["weight_kg"], changed["after"]["weight_kg"]) == (15.0, 20.0)
    assert changed["before"]["summary"] == "3 sets of 10 reps at 15 kg, 60 s rest"
    assert changed["after"]["summary"] == "3 sets of 10 reps at 20 kg, 60 s rest"
    assert (changes["added"], changes["removed"]) == ([], [])
    assert changes["unchanged"] == ["Brisk Walk", "Bird Dog", "Band Pallof Press", "Brisk Walk"]
    assert changes["identical"] is False
    assert changes["scheduled_date_changed"] is False
    # kept for the approval, and listed after a restart, as shown
    (stored,) = stored_proposals(test_engine, me)
    assert {item["exercise_id"]: item.get("weight_kg") for item in stored["exercises"]} == {
        ids["Brisk Walk"]: None,
        ids["Bird Dog"]: 8.0,
        ids["Band Pallof Press"]: None,
        ids["Cable Woodchop"]: 20.0,
    }
    (listed,) = client.get("/coach/proposals/pending", headers=bearer(me)).json()["proposals"]
    assert listed["exercises"] == shown["exercises"]
    assert listed["changes"] == changes

    saved = approve(client, me, shown)

    # the plan saved is exactly what the proposal represents, weights included
    assert saved.status_code == 201, saved.json()
    weights = {
        (item["section"], item["exercise"]["name"]): item["weight_kg"]
        for item in saved.json()["exercises"]
    }
    assert weights == {
        ("WARM_UP", "Brisk Walk"): None,
        ("MAIN_WORKOUT", "Bird Dog"): 8.0,
        ("MAIN_WORKOUT", "Band Pallof Press"): None,
        ("MAIN_WORKOUT", "Cable Woodchop"): 20.0,
        ("COOL_DOWN", "Brisk Walk"): None,
    }
    again = approve(client, me, shown)
    assert (again.status_code, again.json()["id"]) == (200, saved.json()["id"])


def test_a_revision_that_changes_the_sets_keeps_every_weight_through_to_the_saved_plan(
    client, use_provider, me, ids, test_engine, weighted_plan_id
):
    response, _ = ask(
        client,
        use_provider,
        me,
        reads(),
        tool_turn(proposal(**revision_of(weighted_plan_id, "ADJUST", ids, *CORE_PLAN, sets=4))),
        recommend(REPLY),
        message="Make it a little harder.",
        workout_plan_id=weighted_plan_id,
    )

    shown = response.json()["proposal"]
    assert [item["weight_kg"] for item in shown["exercises"] if item["section"] == "MAIN_WORKOUT"] == [
        8.0,
        None,
        15.0,
    ]
    changed = {item["exercise_name"]: item for item in shown["changes"]["changed"]}
    # each exercise changed its sets, and none lost its weight
    assert set(changed) == set(CORE_PLAN)
    assert [
        (item["before"]["weight_kg"], item["after"]["weight_kg"])
        for item in (changed["Bird Dog"], changed["Band Pallof Press"], changed["Cable Woodchop"])
    ] == [(8.0, 8.0), (None, None), (15.0, 15.0)]

    saved = approve(client, me, shown).json()

    saved_weights = {
        item["exercise"]["name"]: item["weight_kg"]
        for item in saved["exercises"]
        if item["section"] == "MAIN_WORKOUT"
    }
    assert saved_weights == {"Bird Dog": 8.0, "Band Pallof Press": None, "Cable Woodchop": 15.0}


def test_an_intentional_removal_is_shown_as_the_weight_going_and_saved_that_way(
    client, use_provider, me, ids, test_engine, weighted_plan_id
):
    response, _ = ask(
        client,
        use_provider,
        me,
        *moving_weight(ids, weighted_plan_id, remove_weight=True),
        message="Do the woodchop without the weight.",
        workout_plan_id=weighted_plan_id,
    )

    shown = response.json()["proposal"]
    (changed,) = shown["changes"]["changed"]
    assert (changed["before"]["weight_kg"], changed["after"]["weight_kg"]) == (15.0, None)
    assert changed["before"]["summary"] == "3 sets of 10 reps at 15 kg, 60 s rest"
    assert changed["after"]["summary"] == "3 sets of 10 reps, 60 s rest"
    saved = approve(client, me, shown).json()
    assert {
        item["exercise"]["name"]: item["weight_kg"]
        for item in saved["exercises"]
        if item["section"] == "MAIN_WORKOUT"
    } == {"Bird Dog": 8.0, "Band Pallof Press": None, "Cable Woodchop": None}


def test_a_request_for_a_heavier_weight_without_a_figure_is_answered_honestly_and_changes_nothing(
    client, use_provider, me, ids, test_engine, weighted_plan_id
):
    """The model chooses a weight, which Formiq refuses; it then says what it cannot do."""
    answer = (
        "I can't pick a heavier weight for you, because I don't know what you can lift. Tell me "
        "how many kg you want for the woodchop and I'll put it in a new version for you to approve."
    )
    response, provider = ask(
        client,
        use_provider,
        me,
        *moving_weight(ids, weighted_plan_id, weight_kg=25)[:2],
        respond_turn(answer, "WORKOUT_PLAN", "ASK_CLARIFICATION"),
        message="Make the woodchop heavier.",
        workout_plan_id=weighted_plan_id,
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["reply"] == answer
    assert body.get("proposal") is None
    refusal = received(provider, 2)["propose_workout_plan"]["error"]
    assert refusal["code"] == "INVALID_INPUT"
    assert "never choose one" in refusal["message"]
    # nothing proposed, nothing saved, and the saved plan is as it was
    assert stored_proposals(test_engine, me) == []
    plan = client.get(f"/users/{me}/workout-plans/{weighted_plan_id}").json()
    assert plan["status"] == "PLANNED"
    assert {
        item["exercise"]["name"]: item["weight_kg"]
        for item in plan["exercises"]
        if item["section"] == "MAIN_WORKOUT"
    } == {"Bird Dog": 8.0, "Band Pallof Press": None, "Cable Woodchop": 15.0}
    assert client.get("/coach/proposals/pending", headers=bearer(me)).json() == {"proposals": []}


def test_the_coach_reads_the_weights_of_a_pending_proposal_back(
    client, use_provider, me, ids, test_engine, weighted_plan_id
):
    ask(
        client,
        use_provider,
        me,
        *moving_weight(ids, weighted_plan_id, weight_kg=20),
        message="Make the woodchop 20 kg.",
        workout_plan_id=weighted_plan_id,
    )

    _, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_pending_proposal")),
        respond_turn("Yes: it raises the woodchop to 20 kg.", "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        message="What did you propose?",
        workout_plan_id=weighted_plan_id,
    )

    told = received(provider, 1)["get_pending_proposal"]["output"]
    assert [item["weight_kg"] for item in told["exercises"] if item["section"] == "MAIN_WORKOUT"] == [
        8.0,
        None,
        20.0,
    ]
    (changed,) = told["changes"]["changed"]
    assert changed["before"] == "3 sets of 10 reps at 15 kg, 60 s rest"
    assert changed["after"] == "3 sets of 10 reps at 20 kg, 60 s rest"


def test_a_weight_changed_after_the_proposal_makes_its_approval_fail_not_overwrite(
    client, use_provider, me, ids, test_engine, weighted_plan_id
):
    """The plan's weight is part of the plan the approval was bound to: a plan changed since the
    proposal (here, a weight) is refused rather than replaced with a stale weight."""
    shown = ask(
        client,
        use_provider,
        me,
        *moving_weight(ids, weighted_plan_id, weight_kg=20),
        message="Make the woodchop 20 kg.",
        workout_plan_id=weighted_plan_id,
    )[0].json()["proposal"]
    with Session(test_engine) as session:
        woodchop = next(
            item
            for item in session.get(WorkoutPlan, weighted_plan_id).exercises
            if item.exercise_id == ids["Cable Woodchop"]
        )
        woodchop.weight_kg = 17.5
        session.commit()

    refused = approve(client, me, shown)

    assert refused.status_code == 409
    with Session(test_engine) as session:
        assert session.get(WorkoutPlan, weighted_plan_id).status == "PLANNED"
