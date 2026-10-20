"""Formiq's movement pattern for every imported exercise (app/catalog/patterns.py, and
docs/warm-up-cool-down.md's neighbour, docs/exercise-fields.md): the rules that classify the
main exercises, the hand-made table for the records no section uses, and what the pinned
dataset comes to. Without a database; the import is tested in
tests/integration/test_exercise_import.py.

The counts pin the rules to the vendored dataset on purpose: a rule that moves an exercise
from one pattern to another is a decision to make, never a side effect.
"""

from collections import Counter

import pytest

from app.catalog import patterns
from app.catalog.classification import HIDDEN_DUPLICATE_IDS
from app.catalog.free_exercise_db import load_records, parse_records
from app.schemas.exercise import MovementPattern, WorkoutSection

P = MovementPattern
MAIN = WorkoutSection.MAIN_WORKOUT


@pytest.fixture(scope="module")
def dataset():
    return load_records()


@pytest.fixture(scope="module")
def by_id(dataset):
    return {item["id"]: item for item in dataset}


@pytest.fixture(scope="module")
def parsed(dataset):
    return parse_records(dataset)


def record(name, primary, *, force=None, mechanic=None, category="strength"):
    return {
        "name": name,
        "primaryMuscles": primary,
        "force": force,
        "mechanic": mechanic,
        "category": category,
    }


@pytest.mark.parametrize(
    ("fields", "pattern"),
    [
        # the lifts, by the word that names them
        (record("Barbell Back Squat", ["quadriceps"], force="push", mechanic="compound"), P.SQUAT),
        (record("Front Squat (Clean Grip)", ["quadriceps"], force="push"), P.SQUAT),
        (record("Snatch Balance", ["quadriceps"], category="olympic weightlifting"), P.SQUAT),
        (record("Smith Machine Leg Press", ["quadriceps"], force="push"), P.SQUAT),
        (record("Dumbbell Lunges", ["quadriceps"], force="push"), P.LUNGE),
        (record("Step-up with Knee Raise", ["glutes"], force="push"), P.LUNGE),
        (record("Kettlebell Pistol Squat", ["quadriceps"], force="push"), P.LUNGE),
        (record("One Leg Barbell Squat", ["quadriceps"], force="push"), P.LUNGE),
        (record("Sled Push", ["quadriceps"], category="strongman"), P.LUNGE),
        (record("Barbell Deadlift", ["lower back"], force="pull"), P.HINGE),
        (record("Rack Pulls", ["lower back"], force="pull"), P.HINGE),
        (record("Seated Good Mornings", ["lower back"], force="pull"), P.HINGE),
        (record("Hang Clean", ["quadriceps"], category="olympic weightlifting"), P.HINGE),
        (record("One-Arm Kettlebell Swings", ["hamstrings"], force="pull"), P.HINGE),
        (record("Barbell Hip Thrust", ["glutes"], force="push"), P.HINGE),
        (record("Hyperextensions (Back Extensions)", ["lower back"], mechanic="isolation"), P.HINGE),
        (record("Glute Ham Raise", ["hamstrings"], force="pull", mechanic="isolation"), P.HINGE),
        (record("Barbell Bench Press - Medium Grip", ["chest"], force="push"), P.HORIZONTAL_PUSH),
        (record("Push-Up Wide", ["chest"], force="push"), P.HORIZONTAL_PUSH),
        (record("Smith Machine Decline Press", ["chest"], force=None), P.HORIZONTAL_PUSH),
        (record("Close-Grip Dumbbell Press", ["triceps"], force="push"), P.HORIZONTAL_PUSH),
        (record("Standing Military Press", ["shoulders"], force="push"), P.VERTICAL_PUSH),
        (record("Push Press", ["shoulders"], category="olympic weightlifting"), P.VERTICAL_PUSH),
        (record("Split Jerk", ["quadriceps"], category="olympic weightlifting"), P.VERTICAL_PUSH),
        (record("Parallel Bar Dip", ["triceps"], force="push"), P.VERTICAL_PUSH),
        (record("Handstand Push-Ups", ["shoulders"], force="push"), P.VERTICAL_PUSH),
        (record("Bent Over Barbell Row", ["middle back"], force="pull"), P.HORIZONTAL_PULL),
        (record("Face Pull", ["shoulders"], force="pull"), P.HORIZONTAL_PULL),
        (record("Pullups", ["lats"], force="pull"), P.VERTICAL_PULL),
        (record("Mixed Grip Chin", ["middle back"], force="pull"), P.VERTICAL_PULL),
        (record("Wide-Grip Lat Pulldown", ["lats"], force="pull"), P.VERTICAL_PULL),
        (record("Upright Barbell Row", ["shoulders"], force="pull"), P.VERTICAL_PULL),
        (record("Kettlebell Sumo High Pull", ["traps"], force="pull"), P.VERTICAL_PULL),
        (record("Straight-Arm Dumbbell Pullover", ["chest"], force="pull"), P.VERTICAL_PULL),
        (record("Farmer's Walk", ["forearms"], category="strongman"), P.CARRY),
        (record("Russian Twist", ["abdominals"], force="pull"), P.ROTATION),
        (record("Kettlebell Windmill", ["abdominals"], force="pull"), P.ROTATION),
        (record("Plank", ["abdominals"], force="static"), P.ROTATION),
        (record("Side Bridge", ["abdominals"], force="static"), P.ROTATION),
        (record("Pallof Press", ["abdominals"], force="static"), P.ROTATION),
        # one joint: whatever the dataset's own mechanic says of the word
        (record("Dumbbell Bicep Curl", ["biceps"], force="pull", mechanic="isolation"), P.ISOLATION),
        (record("Drag Curl", ["biceps"], force="pull", mechanic="compound"), P.ISOLATION),
        (record("Incline Dumbbell Flyes", ["chest"], force="push", mechanic="compound"), P.ISOLATION),
        (record("Reverse Flyes", ["shoulders"], force="pull", mechanic="isolation"), P.ISOLATION),
        (record("Dumbbell Raise", ["shoulders"], force="pull", mechanic="compound"), P.ISOLATION),
        (record("Tricep Dumbbell Kickback", ["triceps"], force="push"), P.ISOLATION),
        (record("External Rotation with Band", ["shoulders"], mechanic="isolation"), P.ISOLATION),
        (record("Standing Calf Raises", ["calves"], force="push"), P.ISOLATION),
        (record("Calf Press On The Leg Press Machine", ["calves"], force="push"), P.ISOLATION),
        (record("Crunches", ["abdominals"], force="pull", mechanic="compound"), P.ISOLATION),
        (record("Hanging Leg Raise", ["abdominals"], force="pull"), P.ISOLATION),
        (record("Monster Walk", ["abductors"], force="pull"), P.ISOLATION),
        # jumps are squat-like, hops and bounds one leg after the other
        (record("Box Jump (Multiple Response)", ["hamstrings"], category="plyometrics"), P.SQUAT),
        (record("Single-Leg Hop Progression", ["quadriceps"], category="plyometrics"), P.LUNGE),
        (record("Lateral Bound", ["adductors"], category="plyometrics"), P.LUNGE),
        (record("Plyo Push-up", ["chest"], category="plyometrics", force="push"), P.HORIZONTAL_PUSH),
        # no rule fits: no pattern
        (record("Wind Sprints", ["abdominals"], category="plyometrics"), None),
        (record("Rack Delivery", ["shoulders"], category="olympic weightlifting", force="pull"), None),
    ],
)
def test_the_rules_read_a_record_as_a_person_would(fields, pattern):
    assert patterns.main_pattern_of("anything", fields) == pattern


def test_a_name_decides_before_a_fact_of_the_record():
    """"Chin" is a pull, but not in the triceps press to the chin; "plank" is a hold, but not the
    push-up that ends in one: the exceptions say so by id."""
    chin = record("Lying Close-Grip Barbell Triceps Press To Chin", ["triceps"], mechanic="isolation")

    assert patterns.main_pattern_of("Some_Other_Id", chin) == P.VERTICAL_PULL
    assert (
        patterns.main_pattern_of("Lying_Close-Grip_Barbell_Triceps_Press_To_Chin", chin) == P.ISOLATION
    )
    plank = record("Push Up to Side Plank", ["chest"], force="push")
    assert patterns.main_pattern_of("Push_Up_to_Side_Plank", plank) == P.HORIZONTAL_PUSH


def test_the_exceptions_are_records_the_rules_get_wrong(by_id):
    """An exception that the rules already agree with is dead weight: it must be removed."""
    for source_id, pattern in patterns.EXCEPTIONS.items():
        fields = by_id[source_id]
        assert patterns.main_pattern_of("not-an-exception", fields) != pattern, source_id
        assert pattern is None or isinstance(pattern, MovementPattern)


def test_the_hand_made_table_covers_exactly_the_records_no_section_uses(parsed, by_id):
    by_source = {item.source_id: item for item in parsed.exercises}
    assert len(patterns.OTHER_PATTERNS) == 61
    for source_id, pattern in patterns.OTHER_PATTERNS.items():
        item = by_source[source_id]
        assert item.uses == [], source_id
        assert source_id not in HIDDEN_DUPLICATE_IDS
        assert pattern is None or isinstance(pattern, MovementPattern)
    # every record that no section uses, and that nothing else patterns, is in the table
    unlisted = [
        item.source_id
        for item in parsed.exercises
        if not item.uses
        and item.source_id not in HIDDEN_DUPLICATE_IDS
        and by_id[item.source_id]["category"] != "cardio"
        and item.source_id not in patterns.OTHER_PATTERNS
    ]
    # the one exception is skipped by the import: the catalog has Formiq's own
    assert unlisted == ["Worlds_Greatest_Stretch"]


def test_every_visible_imported_exercise_has_a_pattern_but_the_few_that_fit_none(parsed):
    visible = [item for item in parsed.exercises if item.source_id not in HIDDEN_DUPLICATE_IDS]
    unclassified = sorted(item.source_id for item in visible if item.movement_pattern is None)

    assert len(visible) == 858
    # drills, throws and holds that are none of the patterns, and World's Greatest Stretch, which
    # is skipped because the catalog has Formiq's own
    assert unclassified == [
        "Bent_Press",
        "Catch_and_Overhead_Throw",
        "Forward_Drag_with_Press",
        "Frog_Hops",
        "Kettlebell_Figure_8",
        "Kettlebell_Pass_Between_The_Legs",
        "Linear_3-Part_Start_Technique",
        "Linear_Acceleration_Wall_Drill",
        "Moving_Claw_Series",
        "One-Arm_Medicine_Ball_Slam",
        "Rack_Delivery",
        "Spider_Crawl",
        "Standing_Two-Arm_Overhead_Throw",
        "Stomach_Vacuum",
        "Supine_One-Arm_Overhead_Throw",
        "Supine_Two-Arm_Overhead_Throw",
        "Wind_Sprints",
        "Worlds_Greatest_Stretch",
    ]


def test_the_dataset_comes_to_these_patterns(parsed):
    visible = [item for item in parsed.exercises if item.source_id not in HIDDEN_DUPLICATE_IDS]

    counts = Counter(str(item.movement_pattern) for item in visible)

    assert dict(counts) == {
        "ISOLATION": 284,
        "HINGE": 92,
        "HORIZONTAL_PUSH": 77,
        "SQUAT": 63,
        "STRETCH": 70,
        "LUNGE": 49,
        "VERTICAL_PUSH": 61,
        "VERTICAL_PULL": 37,
        "HORIZONTAL_PULL": 35,
        "MOBILITY": 34,
        "ROTATION": 22,
        "CARDIO": 12,
        "CARRY": 4,
        "None": 18,
    }


def test_the_main_exercises_are_patterned_and_the_hidden_duplicates_are_not(parsed):
    """A hidden duplicate is never shown by a search, so it has none (a cardio one is CARDIO, as
    every cardio record is); every main exercise has one but the dozen that fit none."""
    for item in parsed.exercises:
        if item.source_id in HIDDEN_DUPLICATE_IDS:
            assert item.movement_pattern in (None, P.CARDIO), item.source_id
    # 729 records suit the main workout, 9 of them skipped by the import since the catalog
    # has Formiq's own exercise of the name: 720 are imported
    main = [item for item in parsed.exercises if MAIN in item.uses]
    assert len(main) == 729
    assert sum(item.movement_pattern is None for item in main) == 12


def test_each_pattern_has_exercises_a_search_can_offer(parsed):
    """The coach searches the main workout by SQUAT, HINGE, LUNGE, HORIZONTAL_PUSH and the rest:
    each finds more than the few of Formiq's own."""
    main = Counter(str(item.movement_pattern) for item in parsed.exercises if MAIN in item.uses)

    for pattern in (
        P.SQUAT, P.HINGE, P.LUNGE, P.HORIZONTAL_PUSH, P.VERTICAL_PUSH, P.HORIZONTAL_PULL,
        P.VERTICAL_PULL, P.CARRY, P.ROTATION, P.ISOLATION,
    ):  # fmt: skip
        assert main[str(pattern)] >= 4, pattern
    assert main["SQUAT"] == 63 and main["HINGE"] == 91 and main["LUNGE"] == 47
