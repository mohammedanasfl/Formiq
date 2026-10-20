"""Formiq's warm-up and cool-down catalog (docs/warm-up-cool-down.md), without a
database: the duplicates Formiq hides, the movement patterns it gives the
imported activities, its own description of the easy cardio ones, and the data
of the migration that adds Formiq's own activities and says how to do them.
The migration itself, and the catalog it gives a database, are tested in
tests/integration/test_warm_up_cool_down_migration.py and
tests/integration/test_exercise_catalog_coverage.py.
"""

import re

import pytest

from app.catalog import classification, descriptions
from app.catalog.free_exercise_db import load_records, parse_records
from app.models import Exercise, WorkoutPlanExercise
from app.schemas.exercise import MovementPattern, WorkoutSection
from app.services.exercise_import_service import comparable_name
from app.services.recovery_summary_service import _section
from tests.migrations import (
    ACTIVITIES_REVISION,
    LATER_SEED_REVISION,
    SEED_REVISION,
    SOURCE_REVISION,
    migration_module,
)

WARM_UP = WorkoutSection.WARM_UP
COOL_DOWN = WorkoutSection.COOL_DOWN

# what no description may say: Formiq does not claim a benefit (docs/warm-up-cool-down.md)
CLAIMS = re.compile(
    r"\b(prevent\w*|injur\w*|sore\w*|recover\w*|burn\w*|calorie\w*|boost\w*|improv\w*|"
    r"performance|heal\w*|cure[sd]?|therap\w*|benefit\w*)\b",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def dataset():
    return load_records()


@pytest.fixture(scope="module")
def parsed(dataset):
    return parse_records(dataset)


@pytest.fixture(scope="module")
def by_id(dataset):
    return {item["id"]: item for item in dataset}


@pytest.fixture(scope="module")
def activities():
    """The migration that adds the activities."""
    return migration_module(ACTIVITIES_REVISION)


@pytest.fixture(scope="module")
def seed():
    return migration_module(SEED_REVISION)


@pytest.fixture(scope="module")
def later_seed():
    return migration_module(LATER_SEED_REVISION)


@pytest.fixture(scope="module")
def source_migration():
    return migration_module(SOURCE_REVISION)


def formiq_uses(source_migration, name, pattern):
    """The sections 620eafb9c204 gave Formiq's own exercise: by its name, else its pattern."""
    return set(source_migration.USES_BY_NAME.get(name, source_migration.USES_BY_PATTERN[pattern]))


def is_described_as_expected(text):
    """The pattern of every description Formiq writes: steps, a suggested dose, a safety note."""
    return (
        "Suggested dose" in text
        and text.count("Safety: ") == 1
        and text.index("Suggested dose") < text.index("Safety: ")
        and text.endswith(".")
        and not CLAIMS.search(text)
    )


# --- the duplicates ---


def test_thirteen_imported_activities_suit_no_section(parsed):
    found = {item.source_id: item for item in parsed.exercises}

    assert len(classification.ACTIVITY_DUPLICATES) == 13
    assert [s for s in classification.ACTIVITY_DUPLICATES if found[s].uses] == []


def test_a_duplicate_is_in_no_section_list_but_is_still_classified_as_an_activity():
    duplicates = set(classification.ACTIVITY_DUPLICATES)
    activities = (
        classification.WARM_UP_DRILLS
        | classification.COOL_DOWN_STRETCHES
        | classification.WARM_UP_CARDIO
        | classification.COOL_DOWN_CARDIO
    )

    assert not duplicates & (classification.WARM_UP_IDS | classification.COOL_DOWN_IDS)
    assert not duplicates & set(classification.FORMIQ_DUPLICATES)
    # kept in the lists the movement pattern is read from
    assert duplicates <= activities


def test_each_duplicate_names_the_exercise_kept_and_that_suits_what_the_duplicate_did(
    parsed, later_seed, activities, source_migration
):
    imported = {item.name: {str(use) for use in item.uses} for item in parsed.exercises}
    formiqs = {
        a["name"]: formiq_uses(source_migration, a["name"], a["movement_pattern"])
        for a in later_seed.STRENGTH_EXERCISES + later_seed.ACTIVITIES
    } | {a["name"]: set(a["uses"]) for a in activities.NEW_ACTIVITIES}
    names = {item.source_id: item.name for item in parsed.exercises}
    warm_up = classification.WARM_UP_CARDIO | classification.WARM_UP_DRILLS
    cool_down = classification.COOL_DOWN_CARDIO | classification.COOL_DOWN_STRETCHES

    for source_id, kept in classification.ACTIVITY_DUPLICATES.items():
        assert kept != names[source_id], source_id
        assert kept in formiqs or kept in imported, (source_id, kept)
        # what the duplicate was for, the one kept in its place is still for
        suited = {
            use
            for use, listed in (("WARM_UP", warm_up), ("COOL_DOWN", cool_down))
            if source_id in listed
        }
        assert suited <= (formiqs[kept] if kept in formiqs else imported[kept]), source_id


# --- movement patterns ---


@pytest.mark.parametrize(
    ("source_id", "category", "pattern"),
    [
        ("Bicycling", "cardio", MovementPattern.CARDIO),
        ("Rope_Jumping", "cardio", MovementPattern.CARDIO),
        ("Wrist_Circles", "stretching", MovementPattern.MOBILITY),
        ("Childs_Pose", "stretching", MovementPattern.STRETCH),
        # foam rolling is listed as a drill and a stretch: a drill
        ("Hamstring-SMR", "stretching", MovementPattern.MOBILITY),
        # a hidden duplicate of a drill or a stretch has none: a search by pattern would offer
        # it, and it cannot be proposed
        ("Cat_Stretch", "stretching", None),
        ("Standing_Hip_Circles", "stretching", None),
        # a cardio record is CARDIO, a hidden duplicate or not
        ("Walking_Treadmill", "cardio", MovementPattern.CARDIO),
        # the rest are not classified
        ("Pullups", "strength", None),
        ("Lying_Hamstring", "stretching", None),
    ],
)
def test_examples_of_the_movement_pattern(source_id, category, pattern):
    assert classification.movement_pattern_of(source_id, category) is pattern


def test_every_imported_activity_that_suits_a_section_has_a_movement_pattern(parsed):
    patterns = {item.source_id: item.movement_pattern for item in parsed.exercises}
    duplicates = set(classification.ACTIVITY_DUPLICATES)

    for source_id in classification.WARM_UP_DRILLS - duplicates:
        assert patterns[source_id] is MovementPattern.MOBILITY, source_id
    stretches = classification.COOL_DOWN_STRETCHES - classification.WARM_UP_DRILLS
    for source_id in stretches - duplicates:
        assert patterns[source_id] is MovementPattern.STRETCH, source_id
    for item in parsed.exercises:
        if {WARM_UP, COOL_DOWN} & set(item.uses):
            assert item.movement_pattern is not None, item.source_id
    # 66 records are drills or stretches, 63 of them reach the catalog (Arm Circles, Inchworm
    # and Child's Pose are Formiq's own exercises already, so their records are skipped), and 11
    # of those are hidden duplicates, left without a pattern: 52 are given one
    listed = classification.WARM_UP_DRILLS | classification.COOL_DOWN_STRETCHES
    assert len(listed) == 66
    assert len(listed - duplicates) == 55
    assert sum(patterns[s] is not None for s in listed) == 55
    assert len(duplicates & listed) == 11


# --- Formiq's description of the easy cardio records ---


def test_formiqs_description_is_for_every_easy_cardio_record_with_machine_steps(
    parsed, by_id
):
    """The visible easy cardio records, and the two hidden duplicates of them: a saved plan
    or a read by id still shows a hidden one, with the menu and the calorie estimate."""
    visible = classification.WARM_UP_IDS | classification.COOL_DOWN_IDS
    hidden_cardio = {
        source_id
        for source_id in classification.ACTIVITY_DUPLICATES
        if by_id[source_id]["category"] == "cardio"
    }
    machine = re.compile(r"calories|select the desired", re.IGNORECASE)
    machine_steps = {
        source_id
        for source_id in visible | hidden_cardio
        if by_id[source_id]["category"] == "cardio"
        and machine.search(" ".join(by_id[source_id]["instructions"]))
    }
    # every other visible record has a generated summary (tests/unit/test_generated_descriptions.py)
    written = {
        item.source_id
        for item in parsed.exercises
        if item.description and item.description == descriptions.DESCRIPTIONS.get(item.source_id)
    }

    assert hidden_cardio == {"Bicycling_Stationary", "Walking_Treadmill"}
    assert set(descriptions.DESCRIPTIONS) <= visible | hidden_cardio
    assert written == set(descriptions.DESCRIPTIONS)
    # every easy cardio record whose steps are only the machine's is described
    assert machine_steps <= set(descriptions.DESCRIPTIONS)
    for source_id, text in descriptions.DESCRIPTIONS.items():
        assert by_id[source_id]["category"] == "cardio", source_id
        assert is_described_as_expected(text), source_id
        assert descriptions.description_of(source_id) == text
    assert descriptions.description_of("Pullups") is None


def test_a_described_record_is_kept_as_it_was(parsed, by_id):
    for item in parsed.exercises:
        assert item.record == by_id[item.source_id]


# --- the migration's data ---


def test_the_new_activities_are_14_warm_ups_and_7_cool_downs(activities):
    uses = [tuple(activity["uses"]) for activity in activities.NEW_ACTIVITIES]

    assert (uses.count(("WARM_UP",)), uses.count(("COOL_DOWN",))) == (14, 7)
    assert len(uses) == 21


def test_the_new_activities_are_light_classified_and_say_what_they_work(
    activities, seed, later_seed, source_migration
):
    muscles = set(seed.MUSCLE_GROUPS) | set(source_migration.MUSCLE_GROUPS)
    equipment = set(seed.EQUIPMENT) | set(later_seed.EQUIPMENT) | set(source_migration.EQUIPMENT)

    for activity in activities.NEW_ACTIVITIES:
        name = activity["name"]
        assert activity["difficulty"] == "BEGINNER", name
        assert set(activity["muscles"]) <= muscles, name
        assert set(activity["muscles"].values()) <= {"PRIMARY", "SECONDARY"}, name
        assert "PRIMARY" in activity["muscles"].values(), name
        assert set(activity["equipment"]) <= equipment, name
        assert is_described_as_expected(activity["description"]), name
        # a drill or easy cardio warms up; a stretch or easy cardio cools down
        allowed = {
            ("WARM_UP",): {"MOBILITY", "CARDIO"},
            ("COOL_DOWN",): {"STRETCH", "CARDIO"},
        }[tuple(activity["uses"])]
        assert activity["movement_pattern"] in allowed, name


def test_the_new_names_clash_with_no_exercise_the_catalog_or_the_dataset_has(
    activities, seed, later_seed, parsed
):
    names = [activity["name"] for activity in activities.NEW_ACTIVITIES]
    taken = {comparable_name(e["name"]) for e in seed.EXERCISES + later_seed.EXERCISES} | {
        comparable_name(item.name) for item in parsed.exercises
    }

    assert len({comparable_name(name) for name in names}) == len(names)
    assert not {comparable_name(name) for name in names} & taken


def test_the_updated_descriptions_extend_what_the_later_seed_wrote(
    activities, later_seed, source_migration
):
    written = {a["name"]: a for a in later_seed.STRENGTH_EXERCISES + later_seed.ACTIVITIES}
    activity_names = {
        name
        for name, a in written.items()
        if {"WARM_UP", "COOL_DOWN"} & formiq_uses(source_migration, name, a["movement_pattern"])
    }

    assert len(activity_names) == 26
    assert set(activities.OLD_DESCRIPTIONS) == activity_names == set(activities.ADDITIONS)
    for name, old in activities.OLD_DESCRIPTIONS.items():
        assert old == written[name]["description"], name
        assert is_described_as_expected(f"{old} {activities.ADDITIONS[name]}"), name


def test_the_new_warm_ups_work_the_muscles_that_had_no_drill(activities):
    drills = [
        a
        for a in activities.NEW_ACTIVITIES
        if a["uses"] == ["WARM_UP"] and a["movement_pattern"] != "CARDIO"
    ]

    def primary(muscle, *, without_equipment=False):
        return [
            a["name"]
            for a in drills
            if a["muscles"].get(muscle) == "PRIMARY" and not (without_equipment and a["equipment"])
        ]

    for muscle in ("Triceps", "Biceps", "Chest", "Core"):
        assert primary(muscle), muscle
    # the chest, triceps and core need nothing; a biceps drill needs a light band
    for muscle in ("Triceps", "Chest", "Core"):
        assert primary(muscle, without_equipment=True), muscle
    assert primary("Biceps", without_equipment=True) == []


# --- saved plans and sessions ---


def test_hiding_a_duplicate_does_not_change_the_section_a_saved_plan_gives_its_exercise():
    """The recovery summary reads the section from the plan exercise, not from the exercise's
    uses, so a warm-up or cool-down that was hidden is still warm-up or cool-down work."""
    hidden = Exercise(name="Walking, Treadmill", uses=[])

    assert _section(hidden, WorkoutPlanExercise(section="WARM_UP")) is WARM_UP
    assert _section(hidden, WorkoutPlanExercise(section="COOL_DOWN")) is COOL_DOWN


def test_outside_a_plan_an_exercise_that_suits_no_section_is_counted_as_main_work():
    """Unchanged, and the same for any exercise Formiq has not classified: a hidden duplicate
    logged in a session that has no plan is counted as main work (docs/warm-up-cool-down.md)."""
    unplanned = _section(Exercise(name="Walking, Treadmill", uses=[]), None)

    assert unplanned is WorkoutSection.MAIN_WORKOUT
