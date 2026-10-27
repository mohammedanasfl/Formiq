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

from app.agent.context import SUPERSEDED_RESULT
from app.ai import AIProviderError, ToolCall
from app.api.dependencies import PROPOSAL_TTL, get_ai_provider, get_proposal_terms
from app.approvals import ProposalTerms, WriteAction, restore
from app.main import app
from app.models import Equipment, MuscleGroup, UserProfile, WorkoutPlan, WorkoutPlanProposal
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
from app.tools.limits import MAX_SEARCH_RESULTS
from tests.auth import bearer
from tests.coach import (
    call,
    fake_provider,
    respond_turn,
    sent_contents,
    tool_responses,
    tool_turn,
)
from tests.integration.catalog import add_exercise
from tests.integration.test_coach_daily import (
    DAILY_READS,
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
    """A full-body workout at home, with a resistance band and no dumbbells: a
    push, a lunge, a pull and a core exercise, a warm-up for the shoulders and
    legs it trains and a cool-down that stretches them."""
    return {
        "name": "Bodyweight Basics",
        "warm_up": [
            activity(ids["Arm Circles"], reps=10),
            activity(ids["Leg Swings"], sets=2, reps=10, notes="Each leg"),
        ],
        "exercises": [
            exercise(ids["Push-Up"], rest_seconds=60),
            exercise(ids["Walking Lunge"], reps=12, rest_seconds=60, notes="Each leg"),
            exercise(ids["Resistance Band Row"], reps=12, rest_seconds=60),
            exercise(ids["Bird Dog"], rest_seconds=60),
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

    def shown(
        order, section, name, sets, reps=None, duration=None, rest=None, notes=None, equipment=()
    ):
        return {
            "exercise_order": order,
            "section": section,
            "exercise_id": ids[name],
            "exercise_name": name,
            "equipment": list(equipment),
            "sets": sets,
            "reps": reps,
            "duration_seconds": duration,
            "rest_seconds": rest,
            # a proposal carries a weight only where the saved plan it revises has one, or the
            # user gave one (Phase 2.5): a new workout has none
            "weight_kg": None,
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
            shown(2, "WARM_UP", "Leg Swings", 2, reps=10, notes="Each leg"),
            shown(3, "MAIN_WORKOUT", "Push-Up", 3, reps=10, rest=60),
            shown(4, "MAIN_WORKOUT", "Walking Lunge", 3, reps=12, rest=60, notes="Each leg"),
            shown(
                5,
                "MAIN_WORKOUT",
                "Resistance Band Row",
                3,
                reps=12,
                rest=60,
                equipment=["Resistance Band"],
            ),
            shown(6, "MAIN_WORKOUT", "Bird Dog", 3, reps=10, rest=60),
            shown(7, "COOL_DOWN", "Doorway Chest Stretch", 2, duration=30, notes="Each side"),
            shown(8, "COOL_DOWN", "Standing Quad Stretch", 2, duration=30, notes="Each side"),
        ],
        # 3 sets of 45 s, no rest between activities
        "warm_up_minutes": 3,
        # 12 sets of 45 s, each with 60 s of rest
        "main_minutes": 21,
        # 4 holds of 30 s
        "cool_down_minutes": 2,
        "estimated_minutes": 26,
        # a push, a lunge, a pull and a core exercise: a whole body
        "coverage": {
            "complete": True,
            "focus": "FULL_BODY",
            "trained_regions": ["LOWER_BODY", "UPPER_PUSH", "UPPER_PULL", "CORE"],
            "missing_regions": [],
            "main_exercises_counted": 4,
            "main_exercises_required": 4,
            "limitations": [],
        },
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
    arguments = workout(ids, *bodyweight(ids)["exercises"])
    arguments["warm_up"] = [
        activity(ids["Bird Dog"], sets=2, reps=8),
        activity(ids["Cat-Cow"], sets=2, reps=8),
    ]
    arguments["cool_down"] = [activity(ids["Cat-Cow"], reps=8)]

    output = propose(tools, user, **arguments)["output"]

    assert [(item["section"], item["exercise_name"]) for item in output["exercises"]] == [
        ("WARM_UP", "Bird Dog"),
        ("WARM_UP", "Cat-Cow"),
        ("MAIN_WORKOUT", "Push-Up"),
        ("MAIN_WORKOUT", "Walking Lunge"),
        ("MAIN_WORKOUT", "Resistance Band Row"),
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

    assert refusal(result) == {
        "code": "INVALID_INPUT",
        "message": f"exercise {hard.id} (Test Hard Drill) is not a light warm-up activity: "
        "choose a BEGINNER one",
    }
    # and what could take its place: easy cardio, which suits any workout
    assert suggested(result)[0] == ("Brisk Walk", "the warm-up")


def test_a_user_without_equipment_can_say_so(tools, user, ids, db_session):
    every_piece = list(db_session.scalars(select(Equipment.name)))
    squat = workout(ids, exercise(ids["Goblet Squat"]), unavailable_equipment=every_piece)

    assert "needs Dumbbell" in propose(tools, user, **squat)["error"]["message"]
    squat["exercises"] = [
        exercise(ids[name]) for name in ("Bodyweight Squat", "Push-Up", "Walking Lunge", "Bird Dog")
    ]
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


def legs(ids):
    """A legs and core main workout without equipment, as in the Langfuse
    baseline trace, with a lunge added so that it fulfils a LOWER_BODY focus:
    it trains the glutes, quadriceps, hamstrings, calves, core and lower back,
    not the shoulders or the upper back."""
    return [
        exercise(ids["Bodyweight Squat"], reps=12, rest_seconds=60),
        exercise(ids["Glute Bridge"], reps=12, rest_seconds=60),
        exercise(ids["Walking Lunge"], reps=12, rest_seconds=60),
        exercise(ids["Bird Dog"], rest_seconds=60),
    ]


def test_every_warm_up_and_cool_down_misfit_is_named_at_once(tools, user, ids):
    # the baseline's two rejected choices, in one proposal: one correction
    # fixes both, instead of a second rejection for the second one
    arguments = workout(ids, *legs(ids))
    arguments["warm_up"] = [
        activity(ids["Brisk Walk"], duration_seconds=180),
        activity(ids["Arm Circles"], reps=10),
    ]
    arguments["cool_down"] = [
        activity(ids["Cross-Body Shoulder Stretch"], duration_seconds=30),
        activity(ids["Standing Quad Stretch"], sets=2, duration_seconds=30),
    ]

    result = propose(tools, user, **arguments)

    # with the rest of what is wrong (a legs-only workout is no full body): one
    # correction fixes it all
    assert problem(result).startswith(
        f"exercise {ids['Arm Circles']} (Arm Circles) works none of the muscles the main "
        "exercises train, so it does not belong in this warm-up; "
        f"exercise {ids['Cross-Body Shoulder Stretch']} (Cross-Body Shoulder Stretch) works "
        "none of the muscles the main exercises train, so it does not belong in this "
        "cool-down: the main exercises "
        "train Calves, Core, Glutes, Hamstrings, Lower Back, Quadriceps; choose activities "
        "that "
        "work one of them, or easy CARDIO; the main workout trains no upper-body push"
    )
    # easy cardio for each section, which suits any workout, never one already
    # there, and what the main workout misses
    assert {reason for _, reason in suggested(result)} == {
        "the warm-up", "the cool-down", "the upper-body push", "the upper-body pull",
    }  # fmt: skip
    assert ("Brisk Walk", "the warm-up") not in suggested(result)
    assert tools.proposals == []


def test_suits_main_says_which_activities_a_proposal_accepts(tools, user, ids):
    """What the warm-up and cool-down searches say each activity suits is what
    the proposal accepts: searched in one turn with the main exercises (the
    warm-up first, as the traced model did), each activity goes with the legs
    workout exactly when its suits_main is any or holds one of its exercises."""
    searches = [
        ToolCall(
            name="search_exercises",
            arguments={"use": use, "difficulty": "BEGINNER", "available_equipment": []},
            id=f"search-{use}",
        )
        for use in ("WARM_UP", "MAIN_WORKOUT", "COOL_DOWN")
    ]
    warm_up, main, cool_down = (
        result["output"]["exercises"] for result in tools.run(searches, user_id=user.id)
    )
    chosen = {item["exercise_id"] for item in legs(ids)}
    assert chosen <= {item["exercise_id"] for item in main}
    assert all("suits_main" not in item for item in main)

    for section, found in (("warm_up", warm_up), ("cool_down", cool_down)):
        assert found[0]["suits_main"] == "any"
        for item in found:
            arguments = workout(ids, *legs(ids), focus="LOWER_BODY")
            # long enough for a warm-up of at least 3 minutes (a stretch is held 60 seconds
            # at most a set)
            arguments[section] = [activity(item["exercise_id"], sets=3, duration_seconds=60)]
            suits = item["suits_main"] == "any" or bool(chosen & set(item["suits_main"]))

            accepted = "output" in propose(tools, user, **arguments)

            assert accepted == suits, item["name"]


def test_easy_cardio_and_activities_for_the_trained_muscles_are_accepted(tools, user, ids):
    arguments = workout(ids, *legs(ids), focus="LOWER_BODY")
    arguments["warm_up"] = [
        activity(ids["Brisk Walk"], duration_seconds=180),
        activity(ids["Leg Swings"], sets=2, reps=10, notes="Each leg"),
    ]
    arguments["cool_down"] = [
        activity(ids["Marching in Place"], duration_seconds=60),
        activity(ids["Standing Quad Stretch"], sets=2, duration_seconds=30),
        activity(ids["Figure-Four Glute Stretch"], sets=2, duration_seconds=30),
        activity(ids["Cat-Cow"], reps=8),
    ]

    output = propose(tools, user, **arguments)["output"]

    # Leg Swings work the hamstrings and glutes, the stretches the quadriceps and
    # glutes, Cat-Cow the lower back and core; walking and marching are CARDIO
    assert [(item["section"], item["exercise_name"]) for item in output["exercises"]] == [
        ("WARM_UP", "Brisk Walk"),
        ("WARM_UP", "Leg Swings"),
        ("MAIN_WORKOUT", "Bodyweight Squat"),
        ("MAIN_WORKOUT", "Glute Bridge"),
        ("MAIN_WORKOUT", "Walking Lunge"),
        ("MAIN_WORKOUT", "Bird Dog"),
        ("COOL_DOWN", "Marching in Place"),
        ("COOL_DOWN", "Standing Quad Stretch"),
        ("COOL_DOWN", "Figure-Four Glute Stretch"),
        ("COOL_DOWN", "Cat-Cow"),
    ]
    # a few minutes each: 3 minutes of walking and two sets of swings; a minute
    # of marching, four 30-second stretches and a set of Cat-Cow
    assert (output["warm_up_minutes"], output["cool_down_minutes"]) == (5, 4)


@pytest.mark.parametrize(
    ("unavailable", "message"),
    [
        # a misspelled piece was once ignored, so a dumbbell exercise passed
        (
            ["Dumbells"],
            "the catalog has no equipment 'Dumbells'; it has Barbell, Bench, ",
        ),
        # having no equipment does not name what the user cannot use
        (
            ["body weight"],
            (
                "unavailable_equipment names the equipment the user cannot use, and having no "
                "equipment is not one; the catalog has Barbell, Bench, "
            ),
        ),
    ],
)
def test_the_equipment_the_user_cannot_use_must_be_the_catalogs(
    tools, user, ids, unavailable, message
):
    goblet = workout(ids, exercise(ids["Goblet Squat"]), unavailable_equipment=unavailable)

    result = propose(tools, user, **goblet)

    assert result["error"]["code"] == "INVALID_INPUT"
    assert result["error"]["message"].startswith(message)
    assert result["error"]["message"].endswith(
        "; for a user with no equipment at all, name every piece"
    )
    assert tools.proposals == []


def test_the_equipment_the_user_cannot_use_is_matched_however_it_is_written(tools, user, ids):
    goblet = workout(ids, exercise(ids["Goblet Squat"]), unavailable_equipment=["DUMBBELL "])

    assert "needs Dumbbell, which the user cannot use" in (
        propose(tools, user, **goblet)["error"]["message"]
    )


def test_long_sets_of_reps_count_in_the_time_the_user_has(tools, user, ids):
    # 30 reps take longer than 10: estimated at 3 seconds a rep, so a plan of
    # long sets that would not fit in 18 minutes is not proposed as if it did
    def push_ups(reps):
        return workout(
            ids,
            exercise(ids["Push-Up"], reps=reps, rest_seconds=60),
            exercise(ids["Pike Push-Up"], reps=reps, rest_seconds=60),
            focus="PUSH",
            max_minutes=18,
        )

    short = propose(tools, user, **push_ups(10))["output"]
    long = propose(tools, user, **push_ups(30))

    # 6 sets of (45 s + 60 s rest), with a 3-minute walk before and after
    assert (short["main_minutes"], short["estimated_minutes"]) == (11, 17)
    # 6 sets of (90 s + 60 s rest)
    assert long["error"]["message"].startswith(
        "this plan takes about 21 minutes (warm-up 3, main 15, cool-down 3), more than the 18"
    )


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

    assert refusal(result) == {
        "code": "INVALID_INPUT",
        "message": f"exercise {retirable_exercise_id} is not an active Formiq catalog exercise",
    }
    # and what may take its place, from the active catalog
    assert retirable_exercise_id not in [
        item["exercise_id"] for item in result["error"]["suggestions"]
    ]


# --- a complete workout ---


def main_of(ids, *names, sets=3):
    return [exercise(ids[name], sets=sets, rest_seconds=60) for name in names]


def every_piece_of_equipment(session):
    return list(session.scalars(select(Equipment.name)))


def test_a_stretch_is_held_for_a_minute_at_most_a_set(tools, user, ids):
    """Live QA (2026-10-19) saw a chest stretch held for one 180-second set, against the
    20 to 30 seconds the catalog says: more time is more sets, never a longer hold."""
    arguments = workout(ids, *legs(ids), focus="LOWER_BODY")

    arguments["cool_down"] = [activity(ids["Standing Quad Stretch"], duration_seconds=180)]
    refused = propose(tools, user, **arguments)

    message = problem(refused)
    stretch = f"exercise {ids['Standing Quad Stretch']} (Standing Quad Stretch)"
    assert f"{stretch} is a held stretch" in message
    assert "at most 60 seconds a set" in message and "up to 3 sets" in message
    assert tools.proposals == []
    # one second over is refused, the minute itself is not, and three of them make the time
    arguments["cool_down"] = [activity(ids["Standing Quad Stretch"], duration_seconds=61)]
    assert "error" in propose(tools, user, **arguments)
    arguments["cool_down"] = [activity(ids["Standing Quad Stretch"], sets=3, duration_seconds=60)]
    output = propose(tools, user, **arguments)["output"]
    assert output["cool_down_minutes"] == 3


def test_only_a_held_stretch_is_held_for_a_minute_at_most(tools, user, ids):
    """Easy cardio and mobility drills are timed by the minute, as they were."""
    arguments = workout(ids, *legs(ids), focus="LOWER_BODY")
    arguments["warm_up"] = [activity(ids["Brisk Walk"], duration_seconds=300)]
    arguments["cool_down"] = [activity(ids["Cat-Cow"], duration_seconds=180)]

    assert "output" in propose(tools, user, **arguments)


def problem(result):
    assert result["error"]["code"] == "INVALID_INPUT", result
    return result["error"]["message"]


def refusal(result):
    """A refused proposal's error, without the catalog exercises Formiq
    suggests to correct it (suggested)."""
    return {key: value for key, value in result["error"].items() if key != "suggestions"}


def suggested(result):
    """The names of the catalog exercises a refusal suggests, and what for."""
    return [(item["name"], item["for"]) for item in result["error"].get("suggestions", [])]


PUSH_HINT = (
    "the main workout trains no upper-body push (no main exercise with Chest, Shoulders or "
    "Front Deltoid as a primary muscle), which a FULL_BODY workout needs: add a main exercise "
    "for it, such as one search_exercises finds with use MAIN_WORKOUT and muscle Chest"
)
PULL_HINT = (
    "the main workout trains no upper-body pull (no main exercise with Upper Back, Lats or "
    "Rear Deltoid as a primary muscle), which a FULL_BODY workout needs: add a main exercise "
    "for it, such as one search_exercises finds with use MAIN_WORKOUT and muscle Upper Back"
)
# what the hints add when the model gave no equipment: how to say the user has none
LACKING = (
    ", or, if the user does not have the equipment it needs, give available_equipment (what "
    "they have; [] for none) and Formiq proposes the workout without it, saying what it "
    "leaves out"
)
NO_PULL = {
    "code": "NO_SUITABLE_EXERCISE",
    "region": "UPPER_PULL",
    "message": (
        "Formiq's catalog has no upper-body pull exercise (with Upper Back, Lats or Rear "
        "Deltoid as a primary muscle) that suits the user's equipment and experience, so this "
        "workout does not train it."
    ),
}


def test_a_full_body_workout_of_three_main_exercises_is_not_proposed(tools, user, ids):
    """The undersized proposal the dev database kept: a squat, a bird dog and a
    lunge, called full body. Every way it falls short is named at once."""
    arguments = workout(ids, *main_of(ids, "Bodyweight Squat", "Bird Dog", "Walking Lunge"))

    assert problem(propose(tools, user, **arguments)) == (
        f"{PUSH_HINT}{LACKING}; {PULL_HINT}{LACKING}; the main workout has 3 exercises that "
        "count for a FULL_BODY workout (each different, for lower body, upper-body push, "
        "upper-body pull, core, of at least 2 sets), fewer than the 4 it needs: add main "
        "exercises from the catalog"
    )
    assert tools.proposals == []


def test_a_complete_full_body_workout_is_proposed_as_complete(tools, user, ids):
    arguments = workout(
        ids, *main_of(ids, "Bodyweight Squat", "Push-Up", "Resistance Band Row", "Bird Dog")
    )

    output = propose(tools, user, **arguments)["output"]

    assert output["coverage"] == {
        "complete": True,
        "focus": "FULL_BODY",
        "trained_regions": ["LOWER_BODY", "UPPER_PUSH", "UPPER_PULL", "CORE"],
        "missing_regions": [],
        "main_exercises_counted": 4,
        "main_exercises_required": 4,
        "limitations": [],
    }


def test_a_carry_or_curls_are_no_pull_and_calf_raises_no_lower_body(tools, user, ids):
    # Farmer's Carry trains the forearms, a curl the biceps, calf raises the
    # calves: each belongs to its region, but a full-body workout still needs a
    # back exercise and a leg exercise
    accessories = main_of(
        ids, "Standing Calf Raise", "Push-Up", "Farmer's Carry", "Dumbbell Biceps Curl"
    )

    message = problem(propose(tools, user, **workout(ids, *accessories)))

    assert "trains no lower body" in message
    assert PULL_HINT in message
    assert "fewer than" not in message


def test_a_short_session_may_hold_fewer_exercises_but_still_covers_its_focus(tools, user, ids):
    # 20 minutes: two or three exercises will do, but still the whole body
    two = workout(ids, *main_of(ids, "Bodyweight Squat", "Push-Up", sets=2), max_minutes=20)
    three = workout(
        ids,
        *main_of(ids, "Bodyweight Squat", "Push-Up", "Resistance Band Row", sets=2),
        max_minutes=20,
    )

    assert problem(propose(tools, user, **two)) == PULL_HINT + LACKING
    output = propose(tools, user, **three)["output"]
    assert output["coverage"]["complete"] is True
    assert (
        output["coverage"]["main_exercises_counted"],
        output["coverage"]["main_exercises_required"],
    ) == (3, 2)
    # 6 sets of (45 s + 60 s rest), between two 3-minute walks
    assert output["estimated_minutes"] == 17


def test_a_focused_workout_is_judged_by_its_focus_not_as_a_full_body_one(tools, user, ids):
    presses = main_of(ids, "Push-Up", "Dumbbell Bench Press", "Dumbbell Shoulder Press")

    push = propose(tools, user, **workout(ids, *presses, focus="PUSH"))["output"]
    full_body = propose(tools, user, **workout(ids, *presses))

    assert push["coverage"] == {
        "complete": True,
        "focus": "PUSH",
        "trained_regions": ["UPPER_PUSH"],
        "missing_regions": [],
        "main_exercises_counted": 3,
        "main_exercises_required": 3,
        "limitations": [],
    }
    assert "trains no lower body" in problem(full_body)
    assert "trains no upper-body pull" in problem(full_body)


def test_an_exercise_outside_the_focus_does_not_belong_in_it(tools, user, ids):
    upper = main_of(
        ids, "Push-Up", "One-Arm Dumbbell Row", "Dumbbell Shoulder Press", "Leg Press"
    )

    assert problem(propose(tools, user, **workout(ids, *upper, focus="UPPER_BODY"))) == (
        f"exercise {ids['Leg Press']} (Leg Press) trains none of what a UPPER_BODY workout "
        "trains (upper-body push, upper-body pull, core): choose another exercise, or another "
        "focus"
    )


def test_repeated_exercises_and_single_sets_do_not_make_a_workout_complete(
    tools, user, ids, db_session
):
    push_ups = add_main_exercise(db_session, "Push-Ups", "Chest", "BEGINNER")
    three = main_of(ids, "Bodyweight Squat", "Push-Up", "Resistance Band Row")

    twice = propose(tools, user, **workout(ids, *three, exercise(ids["Push-Up"])))
    renamed = propose(tools, user, **workout(ids, *three, exercise(push_ups.id)))
    one_set = propose(tools, user, **workout(ids, *three, exercise(ids["Bird Dog"], sets=1)))

    # every problem at once: the repeat, and so one exercise too few
    assert problem(twice) == (
        f"exercise {ids['Push-Up']} (Push-Up) is in the main workout twice: list each main "
        "exercise once, and give it more sets for more work; the main workout has 3 exercises "
        "that count for a FULL_BODY workout (each different, for lower body, upper-body push, "
        "upper-body pull, core, of at least 2 sets), fewer than the 4 it needs: add main "
        "exercises from the catalog"
    )
    assert all(reason == "a FULL_BODY workout" for _, reason in suggested(twice))
    assert problem(renamed).startswith(
        f"exercise {push_ups.id} (Push-Ups) repeats exercise {ids['Push-Up']} (Push-Up)"
    )
    assert "has 3 exercises that count for a FULL_BODY workout" in problem(one_set)
    assert tools.proposals == []


def test_a_gap_the_catalog_cannot_fill_is_disclosed_never_hidden(tools, user, ids, db_session):
    """With no equipment at all, Formiq's catalog has no pulling exercise: the
    full-body workout is proposed, marked incomplete, with what it leaves out.
    With equipment, the same workout is refused: a pull is there to choose."""
    no_pull = main_of(ids, "Bodyweight Squat", "Push-Up", "Walking Lunge", "Bird Dog")
    nothing = every_piece_of_equipment(db_session)

    at_home = propose(tools, user, **workout(ids, *no_pull, unavailable_equipment=nothing))
    at_the_gym = propose(tools, user, **workout(ids, *no_pull))

    assert at_home["output"]["coverage"] == {
        "complete": False,
        "focus": "FULL_BODY",
        "trained_regions": ["LOWER_BODY", "UPPER_PUSH", "CORE"],
        "missing_regions": ["UPPER_PULL"],
        "main_exercises_counted": 4,
        "main_exercises_required": 4,
        "limitations": [NO_PULL],
    }
    assert problem(at_the_gym) == PULL_HINT + LACKING
    # the gap is never filled with an exercise the user cannot do
    banded = workout(
        ids,
        *no_pull,
        exercise(ids["Resistance Band Row"]),
        unavailable_equipment=nothing,
    )
    assert "needs Resistance Band, which the user cannot use" in problem(
        propose(tools, user, **banded)
    )
    assert len(tools.proposals) == 1


@pytest.mark.parametrize(
    "has", [[], ["body weight"], ["Pull-up Bar"]], ids=["nothing", "body_weight", "a_bar"]
)
def test_a_user_may_say_what_equipment_they_have(tools, user, ids, has):
    """As in a search: [] (or a name for no equipment) for none at all, so the
    gap is disclosed without naming every piece the user lacks. With a pull-up
    bar, the pull-up can fill it, so the workout without a pull is refused."""
    no_pull = main_of(ids, "Bodyweight Squat", "Push-Up", "Walking Lunge", "Bird Dog")

    result = propose(tools, user, **workout(ids, *no_pull, available_equipment=has))

    if has == ["Pull-up Bar"]:
        assert problem(result) == PULL_HINT
    else:
        assert result["output"]["coverage"]["limitations"] == [NO_PULL]


def test_the_equipment_the_user_has_bounds_every_exercise(tools, user, ids):
    banded = workout(
        ids,
        *main_of(ids, "Bodyweight Squat", "Push-Up", "Resistance Band Row", "Goblet Squat"),
        available_equipment=["Resistance Band"],
    )

    assert "needs Dumbbell, which the user cannot use" in problem(propose(tools, user, **banded))
    misspelled = workout(ids, *main_of(ids, "Push-Up"), available_equipment=["Dumbells"])
    assert problem(propose(tools, user, **misspelled)).startswith(
        "the catalog has no equipment 'Dumbells'; it has Barbell, Bench, "
    )


def test_too_few_suitable_exercises_are_disclosed(tools, user, ids, db_session):
    # with only a resistance band, the catalog has one pulling exercise
    band_only = [name for name in every_piece_of_equipment(db_session) if name != "Resistance Band"]
    pull = workout(
        ids,
        *main_of(ids, "Resistance Band Row", "Bird Dog"),
        focus="PULL",
        unavailable_equipment=band_only,
    )

    output = propose(tools, user, **pull)["output"]

    assert output["coverage"] == {
        "complete": False,
        "focus": "PULL",
        "trained_regions": ["UPPER_PULL", "CORE"],
        "missing_regions": [],
        "main_exercises_counted": 1,
        "main_exercises_required": 3,
        "limitations": [
            {
                "code": "TOO_FEW_SUITABLE_EXERCISES",
                "region": None,
                "message": (
                    "Formiq's catalog has only 1 different exercises for a PULL workout that "
                    "suit the user's equipment and experience, fewer than the 3 it needs."
                ),
            }
        ],
    }


def test_a_focus_the_catalog_has_nothing_for_is_refused(tools, user, ids, db_session):
    nothing = every_piece_of_equipment(db_session)
    pull = workout(
        ids, *main_of(ids, "Bird Dog"), focus="PULL", unavailable_equipment=nothing
    )

    assert "Formiq's catalog has no exercise for a PULL workout that suits the user's " in (
        problem(propose(tools, user, **pull))
    )
    assert tools.proposals == []


def muscle_group(session, name):
    return session.scalars(select(MuscleGroup).where(MuscleGroup.name == name)).one()


def add_experience(session, user, profile_fields, experience):
    """The user's profile, which says how experienced they are."""
    fields = {**profile_fields, "fitness_experience": experience}
    session.add(UserProfile(user_id=user.id, **fields))
    session.flush()


def add_main_exercise(session, name, muscle, difficulty):
    return add_exercise(
        session,
        name,
        primary=[muscle_group(session, muscle)],
        difficulty=difficulty,
        uses=["MAIN_WORKOUT"],
    )


@pytest.mark.parametrize(("experience", "accepted"), [("beginner", False), ("intermediate", True)])
def test_a_beginner_is_never_proposed_an_advanced_exercise(
    tools, user, ids, db_session, profile_fields, experience, accepted
):
    add_experience(db_session, user, profile_fields, experience)
    hard = add_main_exercise(db_session, "Test Advanced Press", "Chest", "ADVANCED")
    arguments = workout(
        ids,
        *main_of(ids, "Bodyweight Squat", "Resistance Band Row", "Bird Dog"),
        exercise(hard.id),
    )

    result = propose(tools, user, **arguments)

    if accepted:
        assert result["output"]["coverage"]["complete"] is True
    else:
        assert problem(result) == (
            f"exercise {hard.id} (Test Advanced Press) is ADVANCED, too hard for a beginner: "
            "choose a BEGINNER or INTERMEDIATE one (search_exercises with difficulty BEGINNER "
            "finds them)"
        )


@pytest.mark.parametrize(("experience", "disclosed"), [("beginner", True), ("intermediate", False)])
def test_only_what_suits_the_users_experience_fills_a_gap(
    tools, user, ids, db_session, profile_fields, experience, disclosed
):
    # without equipment, the only pull is too hard for a beginner: for them the
    # gap is disclosed, for anyone else it is to be filled
    add_experience(db_session, user, profile_fields, experience)
    add_main_exercise(db_session, "Test Advanced Pull", "Lats", "ADVANCED")
    arguments = workout(
        ids,
        *main_of(ids, "Bodyweight Squat", "Push-Up", "Walking Lunge", "Bird Dog"),
        unavailable_equipment=every_piece_of_equipment(db_session),
    )

    result = propose(tools, user, **arguments)

    if disclosed:
        assert result["output"]["coverage"]["limitations"] == [NO_PULL]
    else:
        assert problem(result).startswith("the main workout trains no upper-body pull")


@pytest.mark.parametrize(
    ("max_minutes", "accepted"),
    # the workout takes about 26 minutes: at least half of 35, not of 60 (and a session of 40
    # minutes or more needs five main exercises, which this one does not have)
    [(None, True), (35, True), (60, False)],
)
def test_a_workout_uses_at_least_half_the_time_the_user_has(
    tools, user, ids, max_minutes, accepted
):
    arguments = {**bodyweight(ids), "max_minutes": max_minutes}
    if max_minutes is None:
        del arguments["max_minutes"]

    result = propose(tools, user, **arguments)

    if accepted:
        assert result["output"]["estimated_minutes"] == 26
    else:
        # (it also has too few exercises for 60 minutes: both are named)
        assert (
            "this plan takes about 26 minutes, less than half of the 60 the user has: make it "
            "at least 30 minutes, with more sets or main exercises"
        ) in problem(result)


@pytest.mark.parametrize(("max_minutes", "accepted"), [(None, False), (30, False), (25, True)])
def test_a_warm_up_lasts_three_minutes_unless_the_session_is_short(
    tools, user, ids, max_minutes, accepted
):
    arguments = {**bodyweight(ids), "warm_up": [activity(ids["Arm Circles"], reps=10)]}
    if max_minutes is not None:
        arguments["max_minutes"] = max_minutes

    result = propose(tools, user, **arguments)

    if accepted:
        assert result["output"]["warm_up_minutes"] == 1
    else:
        assert problem(result) == (
            "the warm-up takes about 1 minutes, less than 3: make it longer, such as a longer "
            "bout of easy cardio, rather than add activities"
        )


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


def proposing(ids, push_up_sets=3):
    """A model that reads what today needs and the catalog (the main exercises,
    then the warm-up drills and the stretches for the muscles it trains: there
    are more of each than one search returns), then proposes a full-body
    workout that fits 30 minutes without dumbbells (push_up_sets sets of
    push-ups: another number is another workout)."""
    workout = bodyweight(ids)
    workout["exercises"][0] = {**workout["exercises"][0], "sets": push_up_sets}
    return (
        daily_reads(
            call("search_exercises", movement_pattern="HORIZONTAL_PUSH"),
            call("search_exercises", movement_pattern="LUNGE"),
        ),
        tool_turn(
            call("search_exercises", movement_pattern="HORIZONTAL_PULL"),
            call("search_exercises", movement_pattern="ROTATION"),
            call("search_exercises", movement_pattern="MOBILITY", muscle="Shoulders"),
            call("search_exercises", movement_pattern="MOBILITY", muscle="Hamstrings"),
            call("search_exercises", movement_pattern="STRETCH", muscle="Chest"),
            call("search_exercises", movement_pattern="STRETCH", muscle="Quadriceps"),
        ),
        tool_turn(proposal(**workout, max_minutes=30, unavailable_equipment=["Dumbbell"])),
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
        # proposing before looking at the plan is refused, and Formiq reads it
        tool_turn(proposal(**bodyweight(ids))),
        recommend(answer),
    )

    assert body == {"reply": answer}
    refusal = received(provider, 1)["propose_workout_plan"]["error"]
    assert refusal["code"] == "CONTEXT_MISSING"
    assert "no planned workout already suits the user" in refusal["message"]
    # what Formiq read for the model is the user's own: their plan, by the trusted user
    loaded = {item["tool"]: item["result"] for item in refusal["loaded"]}
    assert list(loaded) == ["get_user_profile", "get_current_workout_plan", "get_latest_workout_session"]
    assert loaded["get_current_workout_plan"]["output"]["plan_id"] == planned
    assert "error" in loaded["get_latest_workout_session"]  # no workout yet: checked, none
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
    ] == [3, 21, 2, 26]
    assert shown["coverage"]["complete"] is True
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
        (2, "WARM_UP", "Leg Swings", [], 2, 10, None),
        (3, "MAIN_WORKOUT", "Push-Up", [], 3, 10, None),
        (4, "MAIN_WORKOUT", "Walking Lunge", [], 3, 12, None),
        (5, "MAIN_WORKOUT", "Resistance Band Row", ["Resistance Band"], 3, 12, None),
        (6, "MAIN_WORKOUT", "Bird Dog", [], 3, 10, None),
        (7, "COOL_DOWN", "Doorway Chest Stretch", [], 2, None, 30),
        (8, "COOL_DOWN", "Standing Quad Stretch", [], 2, None, 30),
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
        (2, "WARM_UP", ids["Leg Swings"], 2, 10, None, None, None, "Each leg"),
        (3, "MAIN_WORKOUT", ids["Push-Up"], 3, 10, None, None, 60, None),
        (4, "MAIN_WORKOUT", ids["Walking Lunge"], 3, 12, None, None, 60, "Each leg"),
        (5, "MAIN_WORKOUT", ids["Resistance Band Row"], 3, 12, None, None, 60, None),
        (6, "MAIN_WORKOUT", ids["Bird Dog"], 3, 10, None, None, 60, None),
        (7, "COOL_DOWN", ids["Doorway Chest Stretch"], 2, None, 30, None, None, "Each side"),
        (8, "COOL_DOWN", ids["Standing Quad Stretch"], 2, None, 30, None, None, "Each side"),
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
    # the approval is used up: approving again saves nothing, and returns the plan it saved
    again = approve(client, me, shown)
    assert (again.status_code, again.json()) == (200, plan)
    assert plans_of(test_engine, me) == [plan["id"]]


def test_the_baseline_journey_proposes_in_four_requests_and_saves_only_on_approval(
    client, use_provider, users, ids, test_engine
):
    """The journey of the Langfuse baseline trace: no plan and no workout yet,
    and a user without equipment asking for today's workout. A model that
    follows the instructions reads, searches each section once (saying "body
    weight", as the traced model did), proposes, then replies: four requests
    and seven tool calls, none invalid, where the trace took six and eleven.
    Once the proposal is accepted, the search results are not sent again; the
    reply rests on the proposal, which the response carries; nothing is saved
    until the user approves it."""
    me, _ = users
    searches = [
        call(
            "search_exercises", use=use, difficulty="BEGINNER", available_equipment=["body weight"]
        )
        for use in ("WARM_UP", "MAIN_WORKOUT", "COOL_DOWN")
    ]
    plan = {
        "name": "Beginner Legs and Core",
        "warm_up": [
            activity(ids["Brisk Walk"], duration_seconds=180),
            activity(ids["Inchworm"], reps=6),
        ],
        "focus": "LOWER_BODY",
        "exercises": legs(ids),
        "cool_down": [
            activity(ids["Figure-Four Glute Stretch"], sets=2, duration_seconds=30),
            activity(ids["Kneeling Hip Flexor Stretch"], sets=2, duration_seconds=30),
            activity(ids["Cat-Cow"], reps=8),
        ],
    }
    reply = (
        "Here is a bodyweight workout for your legs and core, about 28 minutes. Review it "
        "in Formiq and approve it to save it."
    )

    body, provider = ask(
        client,
        use_provider,
        me,
        daily_reads(),
        tool_turn(*searches),
        tool_turn(proposal(**plan)),
        recommend(reply),
        message="give workout plan for today",
    )

    assert provider.generate_turn.call_count == 4
    # every search ran, and found only what needs no equipment, easy cardio first
    found = [response.response for response in tool_responses(sent_contents(provider, 2)[-1])]
    assert [len(result["output"]["exercises"]) for result in found] == [
        MAX_SEARCH_RESULTS,
        6,
        MAX_SEARCH_RESULTS,
    ]
    for result in found:
        assert all(item["equipment"] == [] for item in result["output"]["exercises"])
    main = {item["exercise_id"] for item in plan["exercises"]}
    for section, results in (("warm_up", found[0]), ("cool_down", found[2])):
        activities = {item["exercise_id"]: item for item in results["output"]["exercises"]}
        assert next(iter(activities.values()))["movement_pattern"] == "CARDIO"
        # each activity chosen says it suits the main exercises chosen
        for chosen in plan[section]:
            suits = activities[chosen["exercise_id"]]["suits_main"]
            assert suits == "any" or main & set(suits)
    # the reply's request: the reads and the proposal, not the candidates again
    final = sent_contents(provider, 3)
    assert [response.response for response in tool_responses(final[4])] == (
        [SUPERSEDED_RESULT] * 3
    )
    assert {response.name for response in tool_responses(final[2])} == set(DAILY_READS)
    assert received(provider, 3)["propose_workout_plan"]["output"]["status"] == (
        "awaiting_user_approval"
    )
    # the reply, and the proposal it introduces, as the user is shown them
    assert body["reply"] == reply
    shown = body["proposal"]
    assert [(item["section"], item["exercise_name"]) for item in shown["exercises"]] == [
        ("WARM_UP", "Brisk Walk"),
        ("WARM_UP", "Inchworm"),
        ("MAIN_WORKOUT", "Bodyweight Squat"),
        ("MAIN_WORKOUT", "Glute Bridge"),
        ("MAIN_WORKOUT", "Walking Lunge"),
        ("MAIN_WORKOUT", "Bird Dog"),
        ("COOL_DOWN", "Figure-Four Glute Stretch"),
        ("COOL_DOWN", "Kneeling Hip Flexor Stretch"),
        ("COOL_DOWN", "Cat-Cow"),
    ]
    assert [
        shown[key]
        for key in ("warm_up_minutes", "main_minutes", "cool_down_minutes", "estimated_minutes")
    ] == [4, 21, 3, 28]
    assert plans_of(test_engine, me) == []

    response = approve(client, me, shown)

    assert response.status_code == 201
    assert plans_of(test_engine, me) == [response.json()["id"]]


def test_a_reply_offering_a_proposal_the_turn_never_made_is_rejected(
    client, use_provider, users, test_engine
):
    """A model that describes a changed workout as a proposal to approve, without
    proposing it, is told so; only its corrected reply reaches the user."""
    me, _ = users
    suggestion = "Try 3 sets of 10 push-ups and 3 sets of 12 bodyweight squats today."

    body, provider = ask(
        client,
        use_provider,
        me,
        daily_reads(call("search_exercises", movement_pattern="HORIZONTAL_PUSH")),
        recommend(
            "Here is your updated workout with Push-Ups. Review this proposal in Formiq to "
            "save it when you are ready."
        ),
        recommend(suggestion),
        message="Propose a new version of today's workout with Push-Ups instead of Bench Dips.",
    )

    assert body == {"reply": suggestion}
    refusal = received(provider, 2)["respond"]["error"]["message"]
    assert "none was made in this turn" in refusal
    with Session(test_engine) as session:
        stored = session.scalars(
            select(WorkoutPlanProposal).where(WorkoutPlanProposal.user_id == me)
        ).all()
    assert stored == []
    assert plans_of(test_engine, me) == []


def follow_up(client, use_provider, user_id, *replies, message, history=()):
    """The response to a later message, from a model that answers it with these
    replies in turn, reading nothing (the first one the coach accepts reaches
    the user), and the scripted model."""
    provider = use_provider(*(respond_turn(reply) for reply in replies))
    response = client.post(
        "/coach/message",
        headers=bearer(user_id),
        json={"message": message, "history": list(history)},
    )
    assert response.status_code == 200, response.json()
    return response.json(), provider


def proposals_of(test_engine, user_id):
    """The user's stored proposals, by id, with their status."""
    with Session(test_engine) as session:
        return {
            stored.proposal_id: stored.status
            for stored in session.scalars(
                select(WorkoutPlanProposal).where(WorkoutPlanProposal.user_id == user_id)
            )
        }


@pytest.mark.parametrize(
    ("message", "reply"),
    [
        (
            "Why did you choose those exercises?",
            "The proposal I made earlier works your chest and legs, since you rested yesterday.",
        ),
        (
            "Is that workout still there?",
            "Your workout proposal from earlier is still waiting for your approval in Formiq.",
        ),
        (
            "How do I approve the workout you proposed?",
            "Open the proposal in Formiq and tap Approve: that saves it as today's plan.",
        ),
    ],
)
def test_a_later_reply_may_point_to_the_users_proposal_awaiting_approval(
    client, use_provider, users, ids, test_engine, message, reply
):
    """Explaining an earlier proposal, reminding the user of it, or saying how to
    approve it: Formiq's records hold it, pending and unexpired, so the reply
    reaches the user. It approves nothing: the proposal still waits for the
    user's own approval."""
    me, _ = users
    shown = ask(client, use_provider, me, *proposing(ids))[0]["proposal"]

    body, _ = follow_up(client, use_provider, me, reply, message=message)

    assert body == {"reply": reply}
    assert proposals_of(test_engine, me) == {shown["proposal_id"]: "PENDING"}
    assert plans_of(test_engine, me) == []
    assert approve(client, me, shown).status_code == 201


@pytest.mark.parametrize(
    "earlier", ["none", "in the history only", "expired", "approved", "theirs"]
)
def test_a_reply_pointing_to_a_proposal_none_awaits_is_rejected(
    client, use_provider, users, ids, test_engine, clock, earlier
):
    """Only a pending, unexpired proposal of the user's in Formiq's records backs
    a reply pointing to one: not one the model or the client-sent history
    invents, an expired or already approved one, or another user's."""
    me, them = users
    history = []
    if earlier == "in the history only":
        history = [
            {"role": "user", "text": "What should I do today?"},
            {"role": "coach", "text": "Here is a proposal for today: approve it in Formiq."},
        ]
    if earlier in ("expired", "approved"):
        shown = ask(client, use_provider, me, *proposing(ids))[0]["proposal"]
        if earlier == "approved":
            assert approve(client, me, shown).status_code == 201
        else:
            clock.now += PROPOSAL_TTL
    if earlier == "theirs":
        ask(client, use_provider, them, *proposing(ids))
    reminder = "Your workout proposal from earlier is still waiting for your approval in Formiq."
    suggestion = "No workout is waiting for you: shall I propose one for today?"

    body, provider = follow_up(
        client,
        use_provider,
        me,
        reminder,
        suggestion,
        message="Is my workout still waiting?",
        history=history,
    )

    assert body == {"reply": suggestion}
    refusal = received(provider, 1)["respond"]["error"]["message"]
    assert "none of theirs awaits approval" in refusal


def test_an_earlier_proposal_is_never_presented_as_a_changed_one(
    client, use_provider, users, ids, test_engine
):
    """The user asks for a change, and the model, without proposing it, says
    the earlier proposal is the changed one: refused, since the user would
    approve the earlier one believing it changed. That one is left as it was."""
    me, _ = users
    shown = ask(client, use_provider, me, *proposing(ids))[0]["proposal"]
    claim = (
        "Here is your updated workout with Push-Ups. Review this proposal in Formiq to save "
        "it when you are ready."
    )
    honest = (
        "Your earlier proposal still awaits your approval in Formiq as it was. Ask again "
        "and I will propose a workout with push-ups."
    )

    body, provider = follow_up(
        client, use_provider, me, claim, honest, message="Swap the lunges for push-ups."
    )

    assert body == {"reply": honest}
    refusal = received(provider, 1)["respond"]["error"]["message"]
    assert "the one awaiting the user's approval is unchanged" in refusal
    assert proposals_of(test_engine, me) == {shown["proposal_id"]: "PENDING"}
    assert approve(client, me, shown).status_code == 201


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
    # another workout: the same one again would not be proposed twice
    second, _ = ask(client, use_provider, me, *proposing(ids, push_up_sets=2))
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
        *["MAIN_WORKOUT"] * 4,
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


# --- a complete workout, through the coach and the API ---


def at_home_searches():
    """The model's searches of each section, for a user without equipment."""
    return tool_turn(
        *(
            call("search_exercises", use=use, available_equipment=[])
            for use in ("MAIN_WORKOUT", "WARM_UP", "COOL_DOWN")
        )
    )


def test_an_incomplete_workout_is_disclosed_to_the_user_and_saved_only_on_approval(
    client, use_provider, users, ids, test_engine
):
    """A user without equipment: Formiq's catalog has no pull they can do, so
    the proposal the response carries says it is incomplete and what it leaves
    out, whatever the reply says. It waits for the user's own approval like any
    other, of the exact proposal shown, once."""
    me, _ = users
    # what the live model found it needed: to say the user has no equipment
    plan = workout(
        ids,
        *main_of(ids, "Bodyweight Squat", "Push-Up", "Walking Lunge", "Bird Dog"),
        available_equipment=[],
    )
    reply = (
        "Here is a full-body bodyweight workout, about 27 minutes. It has no pulling "
        "exercise: there is none you can do without equipment. Review it in Formiq and "
        "approve it to save it."
    )

    body, _ = ask(
        client,
        use_provider,
        me,
        daily_reads(),
        at_home_searches(),
        tool_turn(proposal(**plan)),
        recommend(reply),
    )

    assert body["reply"] == reply
    shown = body["proposal"]
    assert shown["coverage"] == {
        "complete": False,
        "focus": "FULL_BODY",
        "trained_regions": ["LOWER_BODY", "UPPER_PUSH", "CORE"],
        "missing_regions": ["UPPER_PULL"],
        "main_exercises_counted": 4,
        "main_exercises_required": 4,
        "limitations": [NO_PULL],
    }
    assert proposals_of(test_engine, me) == {shown["proposal_id"]: "PENDING"}
    assert plans_of(test_engine, me) == []
    # disclosed is not approved: only the binding the user was shown saves it
    assert approve(client, me, shown, binding="0" * 64).status_code == 409
    assert plans_of(test_engine, me) == []
    saved = approve(client, me, shown)
    assert saved.status_code == 201
    again = approve(client, me, shown)
    assert (again.status_code, again.json()) == (200, saved.json())
    assert plans_of(test_engine, me) == [saved.json()["id"]]


def test_an_undersized_workout_is_refused_and_nothing_is_kept(
    client, use_provider, users, ids, test_engine
):
    """The model proposes the undersized full-body workout the dev database
    kept, is told what it lacks, and gives up: the user gets no proposal, and
    Formiq keeps none."""
    me, _ = users
    undersized = workout(ids, *main_of(ids, "Bodyweight Squat", "Bird Dog", "Walking Lunge"))
    honest = "I could not put a complete workout together today."

    body, provider = ask(
        client,
        use_provider,
        me,
        daily_reads(),
        at_home_searches(),
        tool_turn(proposal(**undersized)),
        respond_turn(honest, "DAILY_WORKOUT", "CANNOT_ANSWER"),
    )

    refusal = received(provider, 3)["propose_workout_plan"]["error"]
    assert refusal["code"] == "INVALID_INPUT"
    assert PULL_HINT in refusal["message"]
    assert body == {"reply": honest}
    assert proposals_of(test_engine, me) == {}
    assert plans_of(test_engine, me) == []


def test_a_refused_workout_is_completed_from_the_catalog_and_proposed_once(
    client, use_provider, users, ids, test_engine
):
    """Told what the workout lacks, the model searches for a pull and a push,
    and proposes again: only the complete proposal reaches the user and is
    kept."""
    me, _ = users
    lower = ("Bodyweight Squat", "Bird Dog", "Walking Lunge")
    complete = workout(ids, *main_of(ids, *lower, "Push-Up", "Resistance Band Row"))

    body, provider = ask(
        client,
        use_provider,
        me,
        daily_reads(),
        at_home_searches(),
        tool_turn(proposal(**workout(ids, *main_of(ids, *lower)))),
        tool_turn(call("search_exercises", use="MAIN_WORKOUT", muscle="Upper Back")),
        tool_turn(proposal(**complete)),
        recommend("Here is a full-body workout. Review it in Formiq and approve it to save it."),
    )

    assert "error" in received(provider, 3)["propose_workout_plan"]
    shown = body["proposal"]
    assert shown["coverage"]["complete"] is True
    assert [
        item["exercise_name"] for item in shown["exercises"] if item["section"] == "MAIN_WORKOUT"
    ] == [*lower, "Push-Up", "Resistance Band Row"]
    assert proposals_of(test_engine, me) == {shown["proposal_id"]: "PENDING"}
    assert plans_of(test_engine, me) == []
