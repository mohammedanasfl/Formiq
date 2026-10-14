"""The catalog covers what the coach needs to build a whole workout, once the
pinned free-exercise-db dataset is imported (the imported_catalog fixture, in conftest.py):
main exercises, warm-up and cool-down activities by Formiq's classification
(each exercise's uses), for the major muscle groups and with little or no
equipment. It also records the gaps that remain.

They import into a transaction that is rolled back, never commit, and require
the local PostgreSQL container to be running.
"""

from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.ai import ToolCall
from app.models import Equipment, Exercise
from app.repositories.exercise_repository import LOAD_MUSCLES_AND_EQUIPMENT
from app.services import (
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.tools import FormiqTools

MAJOR_MUSCLE_GROUPS = (
    "Chest",
    "Upper Back",
    "Lats",
    "Shoulders",
    "Biceps",
    "Triceps",
    "Core",
    "Glutes",
    "Quadriceps",
    "Hamstrings",
    "Calves",
)


@pytest.fixture
def catalog(imported_session):
    """The active exercises, with their muscles and equipment."""
    return imported_session.scalars(
        select(Exercise).options(*LOAD_MUSCLES_AND_EQUIPMENT).where(Exercise.is_active)
    ).all()


def used_for(catalog, section):
    return [exercise for exercise in catalog if section in exercise.uses]


def muscles(exercise, role=None):
    return {link.muscle_group.name for link in exercise.muscles if role in (None, link.role)}


def is_cardio(exercise):
    return exercise.movement_pattern == "CARDIO"


def test_each_section_has_the_measured_coverage(catalog):
    counts = {
        section: (
            len(used_for(catalog, section)),
            sum(e.source == "FORMIQ" for e in used_for(catalog, section)),
            sum(not e.equipment for e in used_for(catalog, section)),
        )
        for section in ("WARM_UP", "MAIN_WORKOUT", "COOL_DOWN")
    }

    # (in all, Formiq's own, needing no equipment)
    assert counts == {
        "WARM_UP": (38, 16, 26),
        "MAIN_WORKOUT": (747, 27, 90),
        "COOL_DOWN": (69, 17, 51),
    }


def test_warm_up_and_cool_down_activities_are_light_and_say_what_they_work(catalog):
    for exercise in used_for(catalog, "WARM_UP") + used_for(catalog, "COOL_DOWN"):
        assert exercise.difficulty == "BEGINNER", exercise.name
        assert muscles(exercise, "PRIMARY"), exercise.name


def test_anyone_can_warm_up_and_cool_down_without_equipment(catalog):
    # easy cardio suits any workout, and needs nothing
    for section in ("WARM_UP", "COOL_DOWN"):
        assert {e.name for e in used_for(catalog, section) if is_cardio(e) and not e.equipment} >= {
            "Brisk Walk",
            "Marching in Place",
        }


@pytest.mark.parametrize("muscle_group", MAJOR_MUSCLE_GROUPS)
def test_every_major_muscle_group_has_main_exercises_and_a_stretch(catalog, muscle_group):
    assert [e for e in used_for(catalog, "MAIN_WORKOUT") if muscle_group in muscles(e, "PRIMARY")]
    stretches = [
        e.name
        for e in used_for(catalog, "COOL_DOWN")
        if not is_cardio(e) and muscle_group in muscles(e)
    ]
    assert len(stretches) >= 2, stretches


# A gap that remains: no warm-up drill works the triceps, so a workout that
# trains only them warms up with easy cardio.
WARM_UP_DRILL_GAPS = {"Triceps"}


@pytest.mark.parametrize("muscle_group", MAJOR_MUSCLE_GROUPS)
def test_every_major_muscle_group_but_the_known_gaps_has_a_warm_up_drill(catalog, muscle_group):
    drills = [
        e.name
        for e in used_for(catalog, "WARM_UP")
        if not is_cardio(e) and muscle_group in muscles(e)
    ]

    assert bool(drills) is (muscle_group not in WARM_UP_DRILL_GAPS), drills


@pytest.mark.parametrize(
    ("muscle_group", "count"),
    [
        ("Chest", 14),
        ("Core", 38),
        ("Quadriceps", 15),
        ("Glutes", 9),
        ("Triceps", 5),
        ("Shoulders", 2),
        ("Hamstrings", 2),
        # gaps: pulling and arm work need something to pull or lift (a pull-up
        # needs a bar, though its record says "body only")
        ("Lats", 0),
        ("Upper Back", 0),
        ("Biceps", 0),
    ],
)
def test_main_exercises_that_need_no_equipment(catalog, muscle_group, count):
    found = [
        e
        for e in used_for(catalog, "MAIN_WORKOUT")
        if not e.equipment and muscle_group in muscles(e, "PRIMARY")
    ]

    assert len(found) == count


@pytest.mark.parametrize(
    ("pattern", "allowed"),
    [
        ("SQUAT", set()),
        ("HINGE", set()),
        ("LUNGE", set()),
        ("HORIZONTAL_PUSH", set()),
        ("VERTICAL_PUSH", set()),
        ("ROTATION", set()),
        # pulling needs something to pull: a band is the least
        ("HORIZONTAL_PULL", {"Resistance Band"}),
    ],
)
def test_formiqs_main_patterns_can_be_trained_with_little_or_no_equipment(
    catalog, pattern, allowed
):
    assert [
        exercise.name
        for exercise in used_for(catalog, "MAIN_WORKOUT")
        if exercise.movement_pattern == pattern
        and {item.name for item in exercise.equipment} <= allowed
    ]


def test_every_piece_of_equipment_has_an_exercise(imported_session, catalog):
    used = {item.name for exercise in catalog for item in exercise.equipment}

    assert set(imported_session.scalars(select(Equipment.name).where(Equipment.is_active))) == used


# --- Formiq's corrections of the imported records ---


def by_source_id(catalog):
    return {exercise.source_id: exercise for exercise in catalog if exercise.source_id}


@pytest.mark.parametrize(
    ("source_id", "equipment"),
    [
        ("Pullups", {"Pull-up Bar"}),
        ("Chin-Up", {"Pull-up Bar"}),
        ("V-Bar_Pullup", {"Pull-up Bar", "Other Equipment"}),
        ("Wide-Grip_Rear_Pull-Up", {"Pull-up Bar"}),
        ("Hanging_Leg_Raise", {"Pull-up Bar"}),
        ("Bench_Dips", {"Bench"}),
        ("Dips_-_Triceps_Version", {"Other Equipment"}),
        ("Body_Tricep_Press", {"Barbell", "Squat Rack"}),
    ],
)
def test_an_exercise_its_record_calls_body_only_needs_its_equipment(
    catalog, source_id, equipment
):
    exercise = by_source_id(catalog)[source_id]

    assert {item.name for item in exercise.equipment} == equipment
    # the upstream record is kept as it was
    assert exercise.source_record["equipment"] == "body only"
    assert exercise.uses == ["MAIN_WORKOUT"]


@pytest.mark.parametrize(
    ("source_id", "formiqs"),
    [
        ("Bodyweight_Walking_Lunge", "Walking Lunge"),
        ("Pushups", "Push-Up"),
        ("Seated_Cable_Rows", "Seated Cable Row"),
        ("Standing_Cable_Wood_Chop", "Cable Woodchop"),
        ("Triceps_Pushdown", "Cable Triceps Pushdown"),
    ],
)
def test_an_imported_copy_of_formiqs_own_exercise_suits_no_section(catalog, source_id, formiqs):
    copy = by_source_id(catalog)[source_id]
    own = next(exercise for exercise in catalog if exercise.name == formiqs)

    # never in a workout beside Formiq's own; still readable by id
    assert copy.uses == []
    assert copy.is_active
    assert "MAIN_WORKOUT" in own.uses
    assert {item.name for item in copy.equipment} == {item.name for item in own.equipment}


def test_a_search_for_no_equipment_finds_nothing_that_needs_some(imported_session):
    """What the coach finds for a user without equipment: no pull-up, dip or
    hanging exercise, and so no pulling exercise at all; with a pull-up bar,
    the pull-ups."""
    tools = FormiqTools(
        users=UserService(imported_session),
        profiles=UserProfileService(imported_session),
        plans=WorkoutPlanService(imported_session),
        sessions=WorkoutSessionService(imported_session),
        catalog=ExerciseCatalogService(imported_session),
        end_read=Mock(),
    )

    def search(**arguments):
        (result,) = tools.run([ToolCall(name="search_exercises", arguments=arguments)], user_id=1)
        return result["output"]

    corrected = {"Pullups", "Chin-Up", "V-Bar Pullup", "Bench Dips", "Dips - Triceps Version"}
    for muscle in ("Lats", "Upper Back", "Triceps", "Chest", "Core"):
        found = search(use="MAIN_WORKOUT", muscle=muscle, available_equipment=[])
        names = {item["name"] for item in found["exercises"]}
        assert all(item["equipment"] == [] for item in found["exercises"]), muscle
        assert not names & (corrected | {"Pushups", "Bodyweight Walking Lunge"}), muscle
    for muscle in ("Lats", "Upper Back"):
        assert search(use="MAIN_WORKOUT", muscle=muscle, available_equipment=[])[
            "total_matches"
        ] == 0
    with_a_bar = search(use="MAIN_WORKOUT", muscle="Lats", available_equipment=["Pull-up Bar"])
    assert {"Pullups", "Chin-Up"} <= {item["name"] for item in with_a_bar["exercises"]}
