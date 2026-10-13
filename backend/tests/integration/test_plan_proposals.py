"""Workout plans the coach proposes, and the user's approval that saves one.

First the proposal tool on the real catalog: what a proposal holds (a warm-up,
the main workout and a cool-down), what each section may hold (the exercises
Formiq uses for it), the user's time and equipment it must fit, and the
exercises and prescriptions it refuses. Then the whole flow through the API:
the coach proposes, nothing is saved but the proposal itself, kept in the
database for the user's approval, and only the signed-in user's approval of the
exact proposal they were shown creates the plan, every section of it, once; the
plan then runs as a workout session.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

import dataclasses
import re
from datetime import UTC, datetime, timedelta
from itertools import count
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import AIProviderError, ToolCall
from app.api.dependencies import PROPOSAL_TTL, get_ai_provider, get_proposal_terms
from app.approvals import ProposalTerms, WriteAction, restore
from app.main import app
from app.models import Equipment, WorkoutPlan, WorkoutPlanProposal
from app.schemas import WorkoutPlanProposalResponse
from app.schemas.coach import ProposedExerciseResponse
from app.services import (
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.tools import FormiqTools, formiq_tools
from tests.auth import bearer
from tests.coach import call, fake_provider, respond_turn, tool_turn
from tests.integration.catalog import add_exercise
from tests.integration.test_coach_daily import (
    TODAY,
    add_plan,
    create_user,
    daily_reads,
    received,
    recommend,
)
from tests.integration.workout_plans import add_user, retire_exercise

UNKNOWN_EXERCISE = 2_147_483_647


class Clock:
    def __init__(self):
        self.now = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def today(monkeypatch):
    """Formiq's date, fixed for these tests."""
    monkeypatch.setattr(formiq_tools, "utc_today", lambda: TODAY)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def terms(clock):
    return ProposalTerms(clock=clock, ttl=PROPOSAL_TTL)


@pytest.fixture
def ids(catalog_exercise_ids):
    return catalog_exercise_ids


_call_ids = count(1)


def proposal(**arguments):
    """The model's propose_workout_plan call. (tests.coach.call would take its
    name argument for the tool's.)"""
    return ToolCall(name="propose_workout_plan", arguments=arguments, id=f"p-{next(_call_ids)}")


def exercise(exercise_id, sets=3, reps=10, **fields):
    return {"exercise_id": exercise_id, "sets": sets, "reps": reps, **fields}


def activity(exercise_id, sets=1, **fields):
    """A warm-up or cool-down activity: give it reps= or duration_seconds=."""
    return {"exercise_id": exercise_id, "sets": sets, **fields}


def bodyweight(ids):
    """A short workout that needs no equipment, with a warm-up for the
    shoulders and legs it trains and a cool-down that stretches them."""
    return {
        "name": "Bodyweight Basics",
        "warm_up": [
            activity(ids["Arm Circles"], reps=10),
            activity(ids["Leg Swings"], reps=10, notes="Each leg"),
        ],
        "exercises": [
            exercise(ids["Push-Up"], rest_seconds=60),
            exercise(ids["Walking Lunge"], reps=12, rest_seconds=60, notes="Each leg"),
        ],
        "cool_down": [
            activity(ids["Doorway Chest Stretch"], sets=2, duration_seconds=30, notes="Each side"),
            activity(ids["Standing Quad Stretch"], sets=2, duration_seconds=30, notes="Each side"),
        ],
    }


def workout(ids, *main, **fields):
    """These main exercises, with a 3-minute easy walk to warm up and another
    to cool down: easy cardio suits any workout."""
    walk = [activity(ids["Brisk Walk"], duration_seconds=180)]
    return {"name": "Today", "warm_up": walk, "exercises": list(main), "cool_down": walk, **fields}


# --- the proposal tool ---


@pytest.fixture
def tools(db_session, terms):
    return FormiqTools(
        users=UserService(db_session),
        profiles=UserProfileService(db_session),
        plans=WorkoutPlanService(db_session),
        sessions=WorkoutSessionService(db_session),
        catalog=ExerciseCatalogService(db_session),
        # ending the read would roll back the flushed test data
        end_read=Mock(),
        today=TODAY,
        proposal_terms=terms,
    )


@pytest.fixture
def user(db_session):
    return add_user(db_session, "proposals@example.com")


def propose(tools, user, **arguments):
    (result,) = tools.run([proposal(**arguments)], user_id=user.id)
    return result


def test_a_proposal_is_built_from_the_catalog_and_saves_nothing(
    tools, db_session, user, ids, clock
):
    result = propose(
        tools, user, **bodyweight(ids), max_minutes=30, unavailable_equipment=["Dumbbell"]
    )

    output = result["output"]

    def shown(order, section, name, sets, reps=None, duration=None, rest=None, notes=None):
        return {
            "exercise_order": order,
            "section": section,
            "exercise_id": ids[name],
            "exercise_name": name,
            "equipment": [],
            "sets": sets,
            "reps": reps,
            "duration_seconds": duration,
            "rest_seconds": rest,
            "notes": notes,
        }

    assert {key: value for key, value in output.items() if key != "expires_at"} == {
        "status": "awaiting_user_approval",
        "name": "Bodyweight Basics",
        "scheduled_date": "2026-10-13",
        "days_from_today": 0,
        # one order across the sections, warm-up first
        "exercises": [
            shown(1, "WARM_UP", "Arm Circles", 1, reps=10),
            shown(2, "WARM_UP", "Leg Swings", 1, reps=10, notes="Each leg"),
            shown(3, "MAIN_WORKOUT", "Push-Up", 3, reps=10, rest=60),
            shown(4, "MAIN_WORKOUT", "Walking Lunge", 3, reps=12, rest=60, notes="Each leg"),
            shown(5, "COOL_DOWN", "Doorway Chest Stretch", 2, duration=30, notes="Each side"),
            shown(6, "COOL_DOWN", "Standing Quad Stretch", 2, duration=30, notes="Each side"),
        ],
        # 2 sets of 45 s, no rest between activities
        "warm_up_minutes": 2,
        # 6 sets of 45 s, each with 60 s of rest
        "main_minutes": 11,
        # 4 holds of 30 s
        "cool_down_minutes": 2,
        "estimated_minutes": 15,
    }
    # made for the trusted user, for the coach's reply; the tool stores nothing,
    # not even the proposal (the coach service keeps the one it shows)
    ((registered, described),) = tools.proposals
    assert described.model_dump(mode="json") == output
    assert registered.expires_at == clock.now + PROPOSAL_TTL
    assert registered.trusted_user_id == user.id
    assert db_session.scalars(select(WorkoutPlanProposal)).all() == []
    # what the approval would save: every section, as shown, without the catalog's names
    assert registered.values()["exercises"] == [
        {
            key: value
            for key, value in item.items()
            if key not in ("exercise_name", "equipment") and value is not None
        }
        for item in output["exercises"]
    ]
    assert db_session.scalars(select(WorkoutPlan).where(WorkoutPlan.user_id == user.id)).all() == []


@pytest.mark.parametrize(
    ("main", "constraints", "reason"),
    [
        (
            [("Dumbbell Shoulder Press", 3)],
            {"unavailable_equipment": ["dumbbell"]},
            "needs Dumbbell, which the user cannot use",
        ),
        (
            [("Barbell Back Squat", 3)],
            {"unavailable_equipment": ["Squat Rack"]},
            "needs Squat Rack",
        ),
        (
            # 12 sets of 45 s with 90 s of rest, the default, between two 3-minute walks
            [("Push-Up", 4), ("Walking Lunge", 4), ("Pull-Up", 4)],
            {"max_minutes": 30},
            (
                "takes about 33 minutes (warm-up 3, main 27, cool-down 3), more than the 30 the "
                "user has"
            ),
        ),
    ],
    ids=["no_dumbbells", "crowded_gym", "limited_time"],
)
def test_a_proposal_must_fit_the_users_time_and_equipment(
    tools, user, ids, main, constraints, reason
):
    exercises = [exercise(ids[name], sets=sets) for name, sets in main]

    result = propose(tools, user, **workout(ids, *exercises, **constraints))

    assert result["error"]["code"] == "INVALID_INPUT"
    assert reason in result["error"]["message"]
    assert tools.proposals == []


@pytest.mark.parametrize(
    "change",
    [
        {"exercises": [exercise(UNKNOWN_EXERCISE)]},
        {"exercises": []},
        {"exercises": [exercise(1)] * 11},
        {"exercises": [exercise(1, sets=0)]},
        {"exercises": [exercise(1, sets=11)]},
        {"exercises": [exercise(1, reps=31)]},
        {"exercises": [exercise(1, sets=3.0)]},
        {"exercises": [exercise(1, sets="3")]},
        {"exercises": [exercise(1, rest_seconds=301)]},
        {"exercises": [exercise(1, weight_kg=60)]},
        {"exercises": [exercise(1, user_id=2)]},
        {"scheduled_date": "2026-10-12"},
        {"scheduled_date": "2026-10-28"},
        {"approved": True},
        {"exercises": [exercise(1, notes="Push through the pain")]},
    ],
    ids=[
        "unknown_exercise",
        "no_exercise",
        "too_many_exercises",
        "no_sets",
        "too_many_sets",
        "too_many_reps",
        "float_sets",
        "text_sets",
        "too_long_rest",
        "a_weight",
        "a_user",
        "yesterday",
        "too_far_ahead",
        "an_approval",
        "unsafe_notes",
    ],
)
def test_invalid_exercises_or_prescriptions_are_rejected(tools, user, ids, change):
    arguments = {**workout(ids, exercise(ids["Push-Up"])), **change}
    if change.get("exercises") and change["exercises"][0]["exercise_id"] == 1:
        # a real exercise, so only the prescription is wrong
        arguments["exercises"] = [
            {**item, "exercise_id": ids["Push-Up"]} for item in change["exercises"]
        ]

    result = propose(tools, user, **arguments)

    assert result["error"]["code"] == "INVALID_INPUT"
    assert tools.proposals == []


# Each changes the warm-up or the cool-down of a valid workout (workout()), whose
# walk is passed in.
@pytest.mark.parametrize(
    "change",
    [
        lambda walk: {"warm_up": []},
        lambda walk: {"cool_down": []},
        lambda walk: {"warm_up": None},
        lambda walk: {"warm_up": [activity(walk)]},
        lambda walk: {"warm_up": [activity(walk, reps=10, duration_seconds=60)]},
        lambda walk: {"warm_up": [activity(walk, sets=4, reps=10)]},
        lambda walk: {"warm_up": [activity(walk, reps=21)]},
        lambda walk: {"cool_down": [activity(walk, duration_seconds=5)]},
        lambda walk: {"cool_down": [activity(walk, duration_seconds=601)]},
        lambda walk: {"cool_down": [activity(walk, duration_seconds=60, rest_seconds=30)]},
        lambda walk: {"cool_down": [activity(walk, duration_seconds=60, weight_kg=5)]},
        lambda walk: {"warm_up": [activity(walk, duration_seconds=30)] * 6},
        lambda walk: {"warm_up": [activity(walk, duration_seconds=30, approved=True)]},
        lambda walk: {
            "cool_down": [activity(walk, duration_seconds=30, notes="Push through the pain")]
        },
    ],
    ids=[
        "no_warm_up",
        "no_cool_down",
        "null_warm_up",
        "no_target",
        "two_targets",
        "too_many_sets",
        "too_many_reps",
        "too_short",
        "too_long",
        "a_rest",
        "a_weight",
        "too_many_activities",
        "an_approval",
        "unsafe_notes",
    ],
)
def test_invalid_warm_ups_or_cool_downs_are_rejected(tools, user, ids, change):
    arguments = {**workout(ids, exercise(ids["Push-Up"])), **change(ids["Brisk Walk"])}

    result = propose(tools, user, **arguments)

    assert result["error"]["code"] == "INVALID_INPUT"
    assert tools.proposals == []


@pytest.mark.parametrize(
    ("section", "name", "reason"),
    [
        # each section holds what Formiq uses the exercise for
        (
            "warm_up",
            "Barbell Back Squat",
            (
                "is not a warm-up exercise in Formiq's catalog (its uses: MAIN_WORKOUT): "
                "choose one whose uses include WARM_UP"
            ),
        ),
        (
            "warm_up",
            "Standing Quad Stretch",
            "is not a warm-up exercise in Formiq's catalog (its uses: COOL_DOWN)",
        ),
        (
            "cool_down",
            "Push-Up",
            (
                "is not a cool-down exercise in Formiq's catalog (its uses: MAIN_WORKOUT): "
                "choose one whose uses include COOL_DOWN"
            ),
        ),
        # a warm-up drill only, which no longer cools down
        (
            "cool_down",
            "Arm Circles",
            "is not a cool-down exercise in Formiq's catalog (its uses: WARM_UP)",
        ),
        (
            "exercises",
            "Arm Circles",
            (
                "is not a main workout exercise in Formiq's catalog (its uses: WARM_UP): "
                "choose one whose uses include MAIN_WORKOUT"
            ),
        ),
        (
            "exercises",
            "Brisk Walk",
            "is not a main workout exercise in Formiq's catalog (its uses: WARM_UP, COOL_DOWN)",
        ),
        # a drill or a stretch must be for the muscles the main exercises train
        ("warm_up", "Leg Swings", "works none of the muscles the main exercises train"),
        ("cool_down", "Standing Calf Stretch", "works none of the muscles the main exercises"),
    ],
)
def test_each_section_holds_activities_that_suit_it_and_the_main_workout(
    tools, user, ids, section, name, reason
):
    # Push-Ups train the chest, front deltoids, triceps and core
    arguments = workout(ids, exercise(ids["Push-Up"]))
    item = (
        exercise(ids[name]) if section == "exercises" else activity(ids[name], duration_seconds=30)
    )
    arguments[section] = [item]

    result = propose(tools, user, **arguments)

    assert result["error"]["code"] == "INVALID_INPUT"
    assert reason in result["error"]["message"]
    assert tools.proposals == []


def test_an_exercise_may_suit_more_than_one_section(tools, user, ids):
    # Formiq uses Bird Dog to warm up and as a main exercise, and Cat-Cow to warm
    # up and to cool down: each may go in either
    arguments = workout(ids, exercise(ids["Push-Up"]), exercise(ids["Bird Dog"]))
    arguments["warm_up"] = [activity(ids["Bird Dog"], reps=8), activity(ids["Cat-Cow"], reps=8)]
    arguments["cool_down"] = [activity(ids["Cat-Cow"], reps=8)]

    output = propose(tools, user, **arguments)["output"]

    assert [(item["section"], item["exercise_name"]) for item in output["exercises"]] == [
        ("WARM_UP", "Bird Dog"),
        ("WARM_UP", "Cat-Cow"),
        ("MAIN_WORKOUT", "Push-Up"),
        ("MAIN_WORKOUT", "Bird Dog"),
        ("COOL_DOWN", "Cat-Cow"),
    ]


def test_a_warm_up_or_cool_down_activity_must_be_light(tools, user, ids, db_session):
    # a backstop to the classification: an activity Formiq uses for the
    # warm-up is still refused when it is not BEGINNER
    hard = add_exercise(
        db_session,
        "Test Hard Drill",
        difficulty="ADVANCED",
        movement_pattern="CARDIO",
        uses=["WARM_UP", "COOL_DOWN"],
    )
    arguments = workout(ids, exercise(ids["Push-Up"]))
    arguments["warm_up"] = [activity(hard.id, reps=10)]

    result = propose(tools, user, **arguments)

    assert result["error"] == {
        "code": "INVALID_INPUT",
        "message": f"exercise {hard.id} (Test Hard Drill) is not a light warm-up activity: "
        "choose a BEGINNER one",
    }


def test_a_user_without_equipment_can_say_so(tools, user, ids, db_session):
    every_piece = list(db_session.scalars(select(Equipment.name)))
    squat = workout(ids, exercise(ids["Goblet Squat"]), unavailable_equipment=every_piece)

    assert "needs Dumbbell" in propose(tools, user, **squat)["error"]["message"]
    squat["exercises"] = [exercise(ids["Bodyweight Squat"])]
    assert "output" in propose(tools, user, **squat)


def test_the_warm_up_and_cool_down_fit_the_users_equipment_and_stay_short(tools, user, ids):
    rowing = workout(ids, exercise(ids["Push-Up"]), unavailable_equipment=["Rowing Machine"])
    rowing["cool_down"] = [activity(ids["Easy Rowing"], duration_seconds=300)]
    long_walk = workout(ids, exercise(ids["Push-Up"]))
    long_walk["warm_up"] = [activity(ids["Brisk Walk"], sets=2, duration_seconds=600)]

    assert "needs Rowing Machine, which the user cannot use" in (
        propose(tools, user, **rowing)["error"]["message"]
    )
    assert "the warm-up takes about 20 minutes, more than 15" in (
        propose(tools, user, **long_walk)["error"]["message"]
    )
    assert tools.proposals == []


@pytest.mark.parametrize("section", ["warm_up", "exercises", "cool_down"])
def test_a_retired_exercise_is_never_proposed(
    tools, user, ids, retirable_exercise_id, test_engine, section
):
    retire_exercise(test_engine, retirable_exercise_id)
    arguments = workout(ids, exercise(ids["Bodyweight Squat"]))
    arguments[section] = [
        exercise(retirable_exercise_id)
        if section == "exercises"
        else activity(retirable_exercise_id, duration_seconds=60)
    ]

    result = propose(tools, user, **arguments)

    assert result["error"] == {
        "code": "INVALID_INPUT",
        "message": f"exercise {retirable_exercise_id} is not an active Formiq catalog exercise",
    }


# --- through the coach and the API ---


@pytest.fixture
def use_provider(client):
    def use(*turns):
        provider = fake_provider(*turns)
        app.dependency_overrides[get_ai_provider] = lambda: provider
        return provider

    try:
        yield use
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)


@pytest.fixture(autouse=True)
def use_terms(terms):
    """Formiq's clock, for these tests: the proposals themselves are in the
    test database."""
    app.dependency_overrides[get_proposal_terms] = lambda: terms
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_proposal_terms, None)


@pytest.fixture
def users(client, test_engine, profile_fields):
    """Two signed-up users with a profile and no plan."""
    with Session(test_engine) as session:
        return (
            create_user(session, "proposals-me@example.com", profile_fields),
            create_user(session, "proposals-them@example.com", profile_fields),
        )


def plans_of(test_engine, user_id):
    with Session(test_engine) as session:
        return session.scalars(select(WorkoutPlan.id).where(WorkoutPlan.user_id == user_id)).all()


def ask(client, use_provider, user_id, *turns, message="What should I do today?"):
    provider = use_provider(*turns)
    response = client.post("/coach/message", headers=bearer(user_id), json={"message": message})
    assert response.status_code == 200, response.json()
    return response.json(), provider


def proposing(ids):
    """A model that reads what today needs and the catalog (the main exercises,
    then the warm-up drills and the stretches), then proposes a bodyweight
    workout that fits 30 minutes without dumbbells."""
    return (
        daily_reads(
            call("search_exercises", movement_pattern="HORIZONTAL_PUSH"),
            call("search_exercises", movement_pattern="LUNGE"),
        ),
        tool_turn(
            call("search_exercises", movement_pattern="MOBILITY"),
            call("search_exercises", movement_pattern="STRETCH"),
        ),
        tool_turn(proposal(**bodyweight(ids), max_minutes=30, unavailable_equipment=["Dumbbell"])),
        recommend("Here is a short bodyweight workout. Review it, and approve it to save it."),
    )


def approve(client, user_id, shown, binding=None):
    """The user approves the proposal as the coach's response showed it."""
    return client.post(
        f"/coach/proposals/{shown['proposal_id']}/approve",
        headers=bearer(user_id),
        json={"binding": binding or shown["binding"]},
    )


def test_a_suitable_planned_workout_is_recommended_not_proposed_again(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    with Session(test_engine) as session:
        planned = add_plan(session, me, 0, (ids["Barbell Bench Press"], 3, 8, 60.0)).id
    answer = "Today is Upper Body A: bench press 3 x 8 at 60 kg."

    body, provider = ask(
        client,
        use_provider,
        me,
        # proposing before looking at the plan is refused
        tool_turn(proposal(**bodyweight(ids))),
        daily_reads(),
        recommend(answer),
    )

    assert body == {"reply": answer}
    refusal = received(provider, 1)["propose_workout_plan"]["error"]
    assert refusal["code"] == "PROPOSAL_REFUSED"
    assert "a suitable planned workout is recommended, not duplicated" in refusal["message"]
    assert plans_of(test_engine, me) == [planned]


def test_a_proposed_plan_is_saved_only_by_the_users_approval_and_once(
    client, use_provider, users, ids, test_engine
):
    me, _ = users

    body, _ = ask(client, use_provider, me, *proposing(ids))

    shown = body["proposal"]
    assert set(shown) == set(WorkoutPlanProposalResponse.model_fields)
    assert re.fullmatch(r"[0-9a-f]{32}", shown["proposal_id"])
    assert re.fullmatch(r"[0-9a-f]{64}", shown["binding"])
    assert (shown["name"], shown["scheduled_date"]) == ("Bodyweight Basics", "2026-10-13")
    assert [
        shown[key]
        for key in ("warm_up_minutes", "main_minutes", "cool_down_minutes", "estimated_minutes")
    ] == [2, 11, 2, 15]
    assert [
        (
            item["exercise_order"],
            item["section"],
            item["exercise_name"],
            item["equipment"],
            item["sets"],
            item["reps"],
            item["duration_seconds"],
        )
        for item in shown["exercises"]
    ] == [
        (1, "WARM_UP", "Arm Circles", [], 1, 10, None),
        (2, "WARM_UP", "Leg Swings", [], 1, 10, None),
        (3, "MAIN_WORKOUT", "Push-Up", [], 3, 10, None),
        (4, "MAIN_WORKOUT", "Walking Lunge", [], 3, 12, None),
        (5, "COOL_DOWN", "Doorway Chest Stretch", [], 2, None, 30),
        (6, "COOL_DOWN", "Standing Quad Stretch", [], 2, None, 30),
    ]
    # proposed, not saved
    assert plans_of(test_engine, me) == []

    response = approve(client, me, shown)

    assert response.status_code == 201
    plan = response.json()
    assert (plan["user_id"], plan["name"], plan["status"], plan["scheduled_date"]) == (
        me,
        "Bodyweight Basics",
        "PLANNED",
        "2026-10-13",
    )
    # the whole workout, each exercise in its section, exactly as shown
    assert [
        (
            item["exercise_order"],
            item["section"],
            item["exercise_id"],
            item["sets"],
            item["reps"],
            item["duration_seconds"],
            item["weight_kg"],
            item["rest_seconds"],
            item["notes"],
        )
        for item in plan["exercises"]
    ] == [
        (1, "WARM_UP", ids["Arm Circles"], 1, 10, None, None, None, None),
        (2, "WARM_UP", ids["Leg Swings"], 1, 10, None, None, None, "Each leg"),
        (3, "MAIN_WORKOUT", ids["Push-Up"], 3, 10, None, None, 60, None),
        (4, "MAIN_WORKOUT", ids["Walking Lunge"], 3, 12, None, None, 60, "Each leg"),
        (5, "COOL_DOWN", ids["Doorway Chest Stretch"], 2, None, 30, None, None, "Each side"),
        (6, "COOL_DOWN", ids["Standing Quad Stretch"], 2, None, 30, None, None, "Each side"),
    ]
    assert [
        {key: item[key] for key in ProposedExerciseResponse.model_fields if key in item}
        for item in plan["exercises"]
    ] == [
        {
            key: value
            for key, value in item.items()
            if key not in ("exercise_name", "equipment")
        }
        for item in shown["exercises"]
    ]
    assert client.get(f"/users/{me}/workout-plans/{plan['id']}").json() == plan
    # the approval is used up
    again = approve(client, me, shown)
    assert (again.status_code, again.json()) == (
        409,
        {"detail": "this proposal was already approved"},
    )
    assert plans_of(test_engine, me) == [plan["id"]]


def test_a_provider_failure_after_the_coach_proposed_leaves_nothing_to_approve(
    client, use_provider, users, ids, test_engine
):
    """Gemini failing between the proposal and the reply, as a live 503
    UNAVAILABLE or 504 DEADLINE_EXCEEDED does (test_coach_failures turns those
    into this AIProviderError): the user is shown no proposal, so none is kept."""
    me, _ = users
    *before_the_reply, _ = proposing(ids)
    provider = use_provider(*before_the_reply, AIProviderError("the model request failed"))

    response = client.post(
        "/coach/message", headers=bearer(me), json={"message": "What should I do today?"}
    )

    assert (response.status_code, response.json()) == (
        502,
        {"detail": "the AI coach could not answer; try again later"},
    )
    # the proposal was made in the turn, then the reply failed
    assert received(provider, 3)["propose_workout_plan"]["output"]["status"] == (
        "awaiting_user_approval"
    )
    with Session(test_engine) as session:
        stored = session.scalars(
            select(WorkoutPlanProposal).where(WorkoutPlanProposal.user_id == me)
        ).all()
    assert stored == []
    assert plans_of(test_engine, me) == []


def test_an_approval_covers_only_the_proposal_shown_and_only_until_it_expires(
    client, use_provider, users, ids, test_engine, clock
):
    me, _ = users
    first, _ = ask(client, use_provider, me, *proposing(ids))
    second, _ = ask(client, use_provider, me, *proposing(ids))
    first, second = first["proposal"], second["proposal"]

    # approving one proposal with what was shown of another approves nothing
    mixed = approve(client, me, first, binding=second["binding"])
    assert mixed.status_code == 409
    assert "different version of the proposal" in mixed.json()["detail"]
    assert plans_of(test_engine, me) == []
    # the proposal itself is still waiting for the user
    assert approve(client, me, first).status_code == 201

    clock.now += PROPOSAL_TTL
    expired = approve(client, me, second)
    assert (expired.status_code, expired.json()) == (
        409,
        {"detail": "this proposal has expired: ask the coach for a new one"},
    )
    assert len(plans_of(test_engine, me)) == 1


def test_warm_up_and_cool_down_ids_must_come_from_the_catalog_in_the_turn(
    client, use_provider, users, ids, test_engine
):
    me, _ = users

    body, provider = ask(
        client,
        use_provider,
        me,
        daily_reads(
            call("search_exercises", movement_pattern="HORIZONTAL_PUSH"),
            call("search_exercises", movement_pattern="LUNGE"),
        ),
        # the warm-up and cool-down activities were never looked up
        tool_turn(proposal(**bodyweight(ids))),
        respond_turn("I could not put a full workout together.", "DAILY_WORKOUT", "CANNOT_ANSWER"),
    )

    refusal = received(provider, 2)["propose_workout_plan"]["error"]
    assert refusal["code"] == "ID_NOT_GROUNDED"
    assert f"exercise_id={ids['Arm Circles']}" in refusal["message"]
    assert f"exercise_id={ids['Doorway Chest Stretch']}" in refusal["message"]
    assert "proposal" not in body
    assert plans_of(test_engine, me) == []


def stored_proposal(test_engine, proposal_id):
    """The proposal as the database keeps it, and as approving it rebuilds it."""
    with Session(test_engine) as session:
        row = session.get(WorkoutPlanProposal, proposal_id)
        return row, restore(
            proposal_id=row.proposal_id,
            trusted_user_id=row.user_id,
            action=WriteAction(row.action),
            parameters=row.parameters,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )


def test_the_binding_covers_every_section_of_the_proposal(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    body, _ = ask(client, use_provider, me, *proposing(ids))
    shown = body["proposal"]
    _, registered = stored_proposal(test_engine, shown["proposal_id"])
    exercises = dict(registered.parameters)["exercises"]

    def changed(records):
        """The binding of the same proposal with other exercises records."""
        parameters = tuple(
            (name, records if name == "exercises" else value)
            for name, value in registered.parameters
        )
        return dataclasses.replace(registered, parameters=parameters).binding()

    no_warm_up = changed(tuple(r for r in exercises if ("section", "WARM_UP") not in r))
    no_cool_down = changed(tuple(r for r in exercises if ("section", "COOL_DOWN") not in r))
    longer_stretch = changed(
        tuple(
            tuple(
                (key, 60 if key == "duration_seconds" else value) for key, value in record
            )
            for record in exercises
        )
    )
    assert changed(exercises) == shown["binding"]

    # an approval of the workout with a section left out or changed approves nothing
    for binding in (no_warm_up, no_cool_down, longer_stretch):
        assert binding != shown["binding"]
        refused = approve(client, me, shown, binding=binding)
        assert refused.status_code == 409
        assert "different version of the proposal" in refused.json()["detail"]
    assert plans_of(test_engine, me) == []
    # the proposal as shown is still waiting, and saves with all its sections
    saved = approve(client, me, shown).json()
    assert [item["section"] for item in saved["exercises"]] == [
        "WARM_UP",
        "WARM_UP",
        "MAIN_WORKOUT",
        "MAIN_WORKOUT",
        "COOL_DOWN",
        "COOL_DOWN",
    ]


def test_an_approved_plan_runs_as_a_workout_session(client, use_provider, users, ids):
    me, _ = users
    body, _ = ask(client, use_provider, me, *proposing(ids))
    plan = approve(client, me, body["proposal"]).json()
    warm_up, push_up = plan["exercises"][0], plan["exercises"][2]
    sessions = f"/users/{me}/workout-sessions"

    started = client.post(sessions, json={"workout_plan_id": plan["id"]})
    assert started.status_code == 201, started.json()
    session_id = started.json()["id"]
    # the warm-up can be logged against its plan exercise, as the main exercises are
    for order, planned, reps in ((1, warm_up, 10), (2, push_up, 8)):
        logged = client.post(
            f"{sessions}/{session_id}/exercises",
            json={
                "exercise_id": planned["exercise_id"],
                "exercise_order": order,
                "plan_exercise_id": planned["id"],
            },
        )
        assert logged.status_code == 201, logged.json()
        assert client.post(
            f"{sessions}/{session_id}/exercises/{logged.json()['id']}/sets",
            json={"set_number": 1, "reps": reps},
        ).status_code == 201
    completed = client.patch(f"{sessions}/{session_id}", json={"status": "COMPLETED"})

    assert completed.status_code == 200
    assert [item["plan_exercise_id"] for item in completed.json()["exercises"]] == [
        warm_up["id"],
        push_up["id"],
    ]
    # performing the plan leaves its prescription as it was
    assert client.get(f"/users/{me}/workout-plans/{plan['id']}").json() == plan


def test_another_user_can_neither_approve_nor_find_a_proposal(
    client, use_provider, users, ids, test_engine
):
    me, them = users
    body, _ = ask(client, use_provider, me, *proposing(ids))
    shown = body["proposal"]

    theirs = approve(client, them, shown)

    # not told apart from a proposal that does not exist
    assert theirs.status_code == 404
    missing = approve(client, them, {**shown, "proposal_id": "0" * 32})
    assert missing.json() == {"detail": f"there is no workout plan proposal {'0' * 32}"}
    assert theirs.json() == {"detail": f"there is no workout plan proposal {shown['proposal_id']}"}
    assert plans_of(test_engine, me) == plans_of(test_engine, them) == []
    # their attempt decided nothing
    assert approve(client, me, shown).status_code == 201


@pytest.mark.parametrize(
    ("proposal_id", "body", "signed_in", "status"),
    [
        ("not-a-proposal", {"binding": "a" * 64}, True, 422),
        ("a" * 32, {"binding": "not-a-binding"}, True, 422),
        ("a" * 32, {"binding": "a" * 64, "user_id": 1}, True, 422),
        ("a" * 32, {}, True, 422),
        ("a" * 32, {"binding": "a" * 64}, False, 401),
    ],
    ids=["bad_id", "bad_binding", "user_id_in_body", "no_binding", "signed_out"],
)
def test_a_malformed_or_unauthenticated_approval_is_refused(
    client, users, proposal_id, body, signed_in, status
):
    me, _ = users
    headers = bearer(me) if signed_in else {}

    response = client.post(f"/coach/proposals/{proposal_id}/approve", headers=headers, json=body)

    assert response.status_code == status


def test_without_a_profile_the_coach_asks_instead_of_proposing(
    client, use_provider, test_engine, ids
):
    with Session(test_engine) as session:
        me = create_user(session, "proposals-new@example.com")
    question = "How experienced are you, and what equipment do you have?"

    body, provider = ask(
        client,
        use_provider,
        me,
        daily_reads(call("search_exercises", movement_pattern="HORIZONTAL_PUSH")),
        tool_turn(proposal(**bodyweight(ids))),
        respond_turn(question, "DAILY_WORKOUT", "ASK_CLARIFICATION"),
    )

    assert body == {"reply": question}
    refusal = received(provider, 2)["propose_workout_plan"]["error"]
    assert refusal["code"] == "PROPOSAL_REFUSED"
    assert "no fitness profile" in refusal["message"]
    assert plans_of(test_engine, me) == []
