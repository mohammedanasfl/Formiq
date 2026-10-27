"""What a proposal that revises a saved plan changes, and how long that plan
takes: in the API's own answer (the proposal's `changes` and
`revision.replaces_plan_estimated_minutes`), worked out by Formiq from the
plan as it is now, by the one comparison the coach's tools also use.

A new workout replaces nothing, so it has neither. A plan that changed since
the proposal was made is not compared with: approving would be refused, and a
client is never shown a change the plan does not show.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

from sqlalchemy.orm import Session

from app.ai import ToolCall
from app.models import WorkoutPlan, WorkoutPlanExercise
from app.schemas.coach import ProposalChanges, ProposalRevisionResponse, WorkoutPlanProposalResponse
from app.services import PlanProposalService
from tests.integration.test_coach_daily import TODAY
from tests.integration.test_coach_follow_ups import ask as ask_the_coach
from tests.integration.test_coach_follow_ups import none_waiting, reading_it
from tests.integration.test_plan_proposals import ask, proposing
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

BRISK_WALK = {
    "sets": 1,
    "reps": None,
    "duration_seconds": 180,
    "rest_seconds": None,
    "weight_kg": None,
    "summary": "1 set of 180 s",
}


def propose_a_rewrite(client, use_provider, user, ids, plan, **options):
    body, _ = ask(
        client, use_provider, user, *rewriting(ids, plan, *CORE_PLAN, **options), message=REWRITE
    )
    return body["proposal"]


# --- what it changes ---


def test_a_revision_carries_what_it_changes_by_formiqs_own_comparison(
    client, use_provider, me, plan_id, ids
):
    shown = propose_a_rewrite(client, use_provider, me, ids, plan_id)

    changes = shown["changes"]
    assert changes["compared_with_plan_id"] == plan_id
    assert (changes["compared_with_plan_name"], changes["compared_with_scheduled_date"]) == (
        "Core & Abs Focus",
        TODAY.isoformat(),
    )
    # the plan's three exercises: 3 sets of 12 and 90 s of rest; now 4 sets of 10 and 60 s
    assert [
        (item["section"], item["exercise_name"], item["before"], item["after"])
        for item in changes["changed"]
    ] == [
        (
            "MAIN_WORKOUT",
            name,
            {
                "sets": 3,
                "reps": 12,
                "duration_seconds": None,
                "rest_seconds": 90,
                "weight_kg": None,
                "summary": "3 sets of 12 reps, 90 s rest",
            },
            {
                "sets": 4,
                "reps": 10,
                "duration_seconds": None,
                "rest_seconds": 60,
                "weight_kg": None,
                "summary": "4 sets of 10 reps, 60 s rest",
            },
        )
        for name in CORE_PLAN
    ]
    # the plan has neither a warm-up nor a cool-down: the proposal adds a walk to each
    assert [
        (item["section"], item["exercise_name"], item["before"], item["after"])
        for item in changes["added"]
    ] == [
        ("WARM_UP", "Brisk Walk", None, BRISK_WALK),
        ("COOL_DOWN", "Brisk Walk", None, BRISK_WALK),
    ]
    assert (changes["removed"], changes["unchanged"], changes["identical"]) == ([], [], False)
    assert (changes["name_changed"], changes["scheduled_date_changed"]) == (True, False)
    # the whole answer reads back as the schemas say it is
    assert ProposalChanges.model_validate(changes).model_dump(mode="json") == changes
    parsed = WorkoutPlanProposalResponse.model_validate(shown)
    assert isinstance(parsed.revision, ProposalRevisionResponse)
    assert set(shown) == set(WorkoutPlanProposalResponse.model_fields)


def plan_with_weights(session, user_id, ids, weight):
    """A plan of three core exercises: 3 sets of 10 and 60 s of rest, lifting `weight` kg."""
    plan = WorkoutPlan(
        user_id=user_id,
        name="Weighted Core",
        status="PLANNED",
        scheduled_date=TODAY,
        exercises=[
            WorkoutPlanExercise(
                exercise_id=ids[name],
                exercise_order=order,
                sets=3,
                reps=10,
                rest_seconds=60,
                weight_kg=weight,
            )
            for order, name in enumerate(CORE_PLAN, start=1)
        ],
    )
    session.add(plan)
    session.commit()
    return plan.id


def test_a_weight_the_plan_has_is_carried_on_not_dropped(client, use_provider, me, ids, test_engine):
    """Phase 2.5. Until then a proposal could set no weight, so every revision dropped the plan's
    (and Key Changes showed "15 kg to no weight" for each exercise). The proposal now carries
    the saved weight on unless the user gave another or asked for none."""
    with Session(test_engine) as session:
        weighted = plan_with_weights(session, me, ids, 15.0)

    # the same sets, reps and rest as the plan; the model gives no weight
    shown = propose_a_rewrite(client, use_provider, me, ids, weighted, sets=3)

    assert [item["weight_kg"] for item in shown["exercises"] if item["section"] == "MAIN_WORKOUT"] == [
        15.0,
        15.0,
        15.0,
    ]
    assert shown["changes"]["changed"] == []
    assert shown["changes"]["unchanged"] == list(CORE_PLAN)
    # the plan had no warm-up or cool-down, and every proposal has both: those are all it adds
    assert [item["exercise_name"] for item in shown["changes"]["added"]] == ["Brisk Walk"] * 2
    assert shown["changes"]["removed"] == []


def test_a_change_to_the_sets_keeps_the_weight_on_both_sides(
    client, use_provider, me, ids, test_engine
):
    with Session(test_engine) as session:
        weighted = plan_with_weights(session, me, ids, 15.0)

    shown = propose_a_rewrite(client, use_provider, me, ids, weighted, sets=4)

    changed = shown["changes"]["changed"]
    assert [item["exercise_name"] for item in changed] == list(CORE_PLAN)
    for item in changed:
        assert item["before"]["summary"] == "3 sets of 10 reps at 15 kg, 60 s rest"
        assert item["after"]["summary"] == "4 sets of 10 reps at 15 kg, 60 s rest"
        assert (item["before"]["weight_kg"], item["after"]["weight_kg"]) == (15.0, 15.0)


def test_a_new_workout_replaces_nothing_so_it_has_no_changes_and_no_revision(
    client, use_provider, users, ids
):
    me, _ = users

    body, _ = ask(client, use_provider, me, *proposing(ids))

    shown = body["proposal"]
    # given as null, never left out: a client does not infer them
    assert shown["revision"] is None
    assert "changes" in shown and shown["changes"] is None
    assert set(shown) == set(WorkoutPlanProposalResponse.model_fields)


def test_the_coach_reads_back_the_same_comparison(client, use_provider, me, plan_id, ids):
    shown = propose_a_rewrite(client, use_provider, me, ids, plan_id)

    _, provider = ask_the_coach(client, use_provider, me, *reading_it("It changes the sets."))

    read = provider.generate_turn.call_args_list[1].args[0][-1]
    told = {part.function_response.name: part.function_response.response for part in read.parts}
    told = told["get_pending_proposal"]["output"]["changes"]
    changes = shown["changes"]

    def lines(items):
        return [
            (
                item["section"],
                item["exercise_name"],
                None if item["before"] is None else item["before"]["summary"],
                None if item["after"] is None else item["after"]["summary"],
            )
            for item in items
        ]

    for key in ("added", "removed", "changed"):
        assert [
            (item["section"], item["exercise_name"], item["before"], item["after"])
            for item in told[key]
        ] == lines(changes[key])
    for key in (
        "compared_with_plan_id",
        "compared_with_plan_name",
        "unchanged",
        "name_changed",
        "scheduled_date_changed",
        "identical",
    ):
        assert told[key] == changes[key]


def test_a_proposal_shown_again_is_the_same_card(client, use_provider, me, plan_id, ids):
    shown = propose_a_rewrite(client, use_provider, me, ids, plan_id)

    again, _ = ask_the_coach(client, use_provider, me, *reading_it("It changes the sets."))

    assert again["proposal"] == shown


def test_a_plan_changed_since_is_not_shown_again_by_the_coach(
    client, use_provider, me, plan_id, ids
):
    propose_a_rewrite(client, use_provider, me, ids, plan_id)
    renamed = client.patch(f"/users/{me}/workout-plans/{plan_id}", json={"name": "Renamed"})
    assert renamed.status_code == 200

    again, _ = ask_the_coach(client, use_provider, me, *none_waiting())

    # approving it would be refused, since the plan is not as it was proposed against: it awaits
    # nothing, as GET /coach/proposals/pending does not list it, so the coach shows no card
    assert "proposal" not in again


def test_the_comparison_is_left_out_when_the_plan_changed_before_the_proposal_is_shown(
    tools, db_session, ids, terms
):
    """A plan can change between a proposal being made and the answer being built (the same
    request): the card still says what it replaces, and compares it with nothing."""
    user = add_user(db_session, "changed-before-shown@example.com")
    plan = core_plan(db_session, user.id, ids)
    (result,) = tools.run(
        [
            ToolCall(
                name="propose_workout_plan",
                arguments=revision_of(plan.id, "ALTERNATIVE", ids, *CORE_PLAN, sets=4),
            )
        ],
        user_id=user.id,
    )
    assert "output" in result, result
    proposal, shown = tools.proposals[0]
    plan.name = "Renamed"
    db_session.flush()

    card = PlanProposalService(db_session, terms).present(proposal, shown)

    assert card.revision.replaces_plan_id == plan.id
    assert card.revision.replaces_plan_estimated_minutes is None
    assert card.changes is None


# --- how long the plan it replaces takes ---


def test_the_length_of_the_replaced_plan_is_worked_out_with_its_warm_up_and_cool_down(
    client, use_provider, me, ids, test_engine
):
    with Session(test_engine) as session:
        plan = core_plan(session, me, ids)
        # the sections as the database holds them: text
        session.add_all(
            [
                WorkoutPlanExercise(
                    workout_plan_id=plan.id, exercise_id=ids["Brisk Walk"], exercise_order=4,
                    section="WARM_UP", sets=1, duration_seconds=180,
                ),
                WorkoutPlanExercise(
                    workout_plan_id=plan.id, exercise_id=ids["Brisk Walk"], exercise_order=5,
                    section="COOL_DOWN", sets=1, duration_seconds=180,
                ),
            ]
        )  # fmt: skip
        session.commit()
        plan_id = plan.id

    shown = propose_a_rewrite(client, use_provider, me, ids, plan_id)

    # warm-up 3, main 3 x (3 sets of 45 s and 90 s of rest) = 21, cool-down 3
    assert shown["revision"]["replaces_plan_estimated_minutes"] == 27
    # and the walks are not new: the plan has them
    assert shown["changes"]["added"] == []
    assert shown["changes"]["unchanged"] == ["Brisk Walk", "Brisk Walk"]


def test_the_length_is_given_beside_the_proposals_own(client, use_provider, me, plan_id, ids):
    shown = propose_a_rewrite(client, use_provider, me, ids, plan_id, sets=3)

    # a client compares like with like: both lengths come from the same formula
    assert shown["revision"]["replaces_plan_estimated_minutes"] == 21
    assert isinstance(shown["estimated_minutes"], int)
