"""Reading, validating and mapping the free-exercise-db records
(app.catalog.free_exercise_db), and Formiq's classification of them
(app.catalog.classification). No database: the import itself is tested in
tests/integration/test_exercise_import.py.
"""

import copy
import hashlib
import json

import pytest

from app.catalog import classification, free_exercise_db
from app.catalog import patterns as catalog_patterns
from app.catalog.free_exercise_db import (
    SOURCE_FILE,
    SOURCE_SHA256,
    SourceFileError,
    load_records,
    parse_records,
)
from app.schemas.exercise import Difficulty, MovementPattern, MuscleRole, WorkoutSection

RECORD = {
    "name": "Alternate Incline Dumbbell Curl",
    "force": "pull",
    "level": "beginner",
    "mechanic": "isolation",
    "equipment": "dumbbell",
    "primaryMuscles": ["biceps"],
    "secondaryMuscles": ["forearms"],
    "instructions": ["Sit down on an incline bench.", "Curl the right arm.", "Repeat."],
    "category": "strength",
    "images": [
        "Alternate_Incline_Dumbbell_Curl/0.jpg",
        "Alternate_Incline_Dumbbell_Curl/1.jpg",
    ],
    "id": "Alternate_Incline_Dumbbell_Curl",
}


def record(**changes):
    value = copy.deepcopy(RECORD)
    for key, change in changes.items():
        if change is ...:
            del value[key]
        else:
            value[key] = change
    return value


@pytest.fixture(scope="module")
def dataset():
    return load_records()


@pytest.fixture(scope="module")
def parsed(dataset):
    return parse_records(dataset)


@pytest.fixture(scope="module")
def by_id(dataset):
    return {item["id"]: item for item in dataset}


# --- the pinned file ---


def test_the_vendored_file_is_the_pinned_dataset(dataset):
    assert hashlib.sha256(SOURCE_FILE.read_bytes()).hexdigest() == SOURCE_SHA256
    assert len(dataset) == 876
    # the provenance record names the same commit and checksum
    provenance = (SOURCE_FILE.parent / "SOURCE.md").read_text()
    assert free_exercise_db.SOURCE_VERSION in provenance
    assert SOURCE_SHA256 in provenance
    assert (
        (SOURCE_FILE.parent / "LICENSE.md")
        .read_text()
        .startswith("This is free and unencumbered software released into the public domain.")
    )


def test_a_file_that_is_not_the_pinned_one_is_refused(tmp_path):
    changed = tmp_path / "exercises.json"
    changed.write_text(json.dumps([RECORD]))

    with pytest.raises(SourceFileError, match="not the pinned dataset file"):
        load_records(changed)
    # with its own checksum, it is read
    assert load_records(changed, sha256=hashlib.sha256(changed.read_bytes()).hexdigest()) == [
        RECORD
    ]


@pytest.mark.parametrize(
    ("content", "message"),
    [(b"{not json", "is not valid JSON"), (b'{"id": "x"}', "does not hold a list of records")],
)
def test_a_file_that_is_not_a_list_of_records_is_refused(tmp_path, content, message):
    path = tmp_path / "exercises.json"
    path.write_bytes(content)

    with pytest.raises(SourceFileError, match=message):
        load_records(path, sha256=hashlib.sha256(content).hexdigest())


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(SourceFileError, match="cannot read"):
        load_records(tmp_path / "missing.json")


# --- validation and mapping ---


def test_every_record_of_the_dataset_is_valid_and_mapped(parsed):
    assert len(parsed.exercises) == 876
    assert parsed.rejected == []
    assert parsed.unresolved == {}
    assert parsed.unknown_fields == set()
    # in source id order, whatever the file's order
    ids = [item.source_id for item in parsed.exercises]
    assert ids == sorted(ids)


def test_a_record_keeps_every_field_and_is_mapped_to_formiqs_catalog():
    (exercise,) = parse_records([record()]).exercises

    # the record itself, unchanged: every field, the steps and images in order
    assert exercise.record == RECORD
    assert exercise.source_id == "Alternate_Incline_Dumbbell_Curl"
    assert exercise.name == "Alternate Incline Dumbbell Curl"
    assert exercise.difficulty is Difficulty.BEGINNER
    # a curl is one joint: the rules of app.catalog.patterns say so
    assert exercise.movement_pattern is MovementPattern.ISOLATION
    assert exercise.muscles == {"Biceps": MuscleRole.PRIMARY, "Forearms": MuscleRole.SECONDARY}
    assert exercise.equipment == ["Dumbbell"]
    assert exercise.uses == [WorkoutSection.MAIN_WORKOUT]
    assert exercise.image_paths == RECORD["images"]
    assert exercise.description == (
        "A beginner single-joint exercise for the biceps, with the forearms helping. "
        "Equipment: dumbbell."
    )
    assert exercise.warnings == []


def test_the_actual_records_keep_their_steps_and_images_in_order(parsed, by_id):
    for exercise in parsed.exercises:
        original = by_id[exercise.source_id]
        assert exercise.record == original
        assert exercise.record["instructions"] == original["instructions"]
        assert exercise.image_paths == original["images"]


def test_an_unknown_field_is_kept_and_reported():
    parsed = parse_records([record(aliases=["Incline Curl"])])

    (exercise,) = parsed.exercises
    assert exercise.record["aliases"] == ["Incline Curl"]
    assert parsed.unknown_fields == {"aliases"}


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"id": ...}, "missing fields: id"),
        ({"images": ..., "category": ...}, "missing fields: category, images"),
        ({"id": "../etc/passwd"}, "id must be 1 to 100 letters"),
        ({"name": "  "}, "name must be non-blank text"),
        ({"name": "x" * 151}, "name is longer than 150 characters"),
        ({"force": 3}, "force must be text or null"),
        ({"primaryMuscles": []}, "primaryMuscles is empty"),
        ({"secondaryMuscles": "biceps"}, "secondaryMuscles must be a list of text"),
        ({"instructions": [1, 2]}, "instructions must be a list of text"),
        ({"images": ["../../secret.jpg"]}, "an image path is not '<exercise id>/<n>."),
        ({"images": ["/etc/passwd"]}, "an image path is not"),
        ({"images": ["Other_Exercise/0.jpg"]}, "outside the exercise's own directory"),
        ({"images": "Alternate_Incline_Dumbbell_Curl/0.jpg"}, "images must be a list"),
    ],
)
def test_a_malformed_record_is_rejected_with_its_reason(changes, reason):
    parsed = parse_records([record(**changes)])

    assert parsed.exercises == []
    (rejected,) = parsed.rejected
    assert reason in "; ".join(rejected.reasons)


@pytest.mark.parametrize(
    ("changes", "field", "value"),
    [
        ({"level": "elite"}, "level", "elite"),
        ({"category": "yoga"}, "category", "yoga"),
        ({"equipment": "trampoline"}, "equipment", "trampoline"),
        ({"primaryMuscles": ["obliques"]}, "muscles", "obliques"),
        ({"secondaryMuscles": ["forearms", "hip flexors"]}, "muscles", "hip flexors"),
    ],
)
def test_a_value_without_a_formiq_mapping_is_rejected_and_reported(changes, field, value):
    parsed = parse_records([record(**changes)])

    # never imported with the value dropped
    assert parsed.exercises == []
    assert parsed.unresolved == {field: {value}}
    assert value in parsed.rejected[0].reasons[0]


def test_a_repeated_id_or_name_is_rejected():
    parsed = parse_records(
        [
            record(),
            record(name="Another Name"),
            record(id="Another_Id", name="alternate incline dumbbell curl", images=[]),
        ]
    )

    assert [item.source_id for item in parsed.exercises] == ["Alternate_Incline_Dumbbell_Curl"]
    assert sorted(reason for item in parsed.rejected for reason in item.reasons) == [
        "another record has the id 'Alternate_Incline_Dumbbell_Curl'",
        "another record has the name 'alternate incline dumbbell curl'",
    ]


def test_a_record_that_is_not_an_object_is_rejected():
    parsed = parse_records(["Push-Up", record()])

    assert len(parsed.exercises) == 1
    assert (parsed.rejected[0].index, parsed.rejected[0].reasons) == (
        0,
        ["the record is not an object"],
    )


def test_an_incomplete_record_is_imported_with_a_warning(parsed):
    warnings = {item.source_id: item.warnings for item in parsed.exercises if item.warnings}

    assert warnings == {
        "Barbell_Squat_To_A_Bench": ["a blank instruction step"],
        "Clean": ["a blank instruction step"],
        "Iron_Cross": ["no instructions"],
        "One-Arm_Kettlebell_Swings": ["no instructions"],
        "Push_Press": ["no instructions"],
        "Side_Bridge": ["no instructions"],
        "Side_Jackknife": ["no instructions"],
        "Kettlebell_Halo": ["no images"],
        "Kettlebell_Halo_With_Overhead_Extension": ["no images"],
        "Kettlebell_Overhead_Triceps_Extension": ["no images"],
    }


def test_two_upstream_muscles_for_one_formiq_group_keep_the_primary_role():
    # middle back and traps are both Formiq's Upper Back
    (exercise,) = parse_records(
        [record(primaryMuscles=["middle back"], secondaryMuscles=["traps", "lats"])]
    ).exercises

    assert exercise.muscles == {"Upper Back": MuscleRole.PRIMARY, "Lats": MuscleRole.SECONDARY}
    # the record keeps the upstream names
    assert exercise.record["secondaryMuscles"] == ["traps", "lats"]


@pytest.mark.parametrize(
    ("equipment", "mapped"),
    [("body only", []), (None, []), ("other", ["Other Equipment"]), ("bands", ["Resistance Band"])],
)
def test_equipment_is_mapped_explicitly(equipment, mapped):
    (exercise,) = parse_records([record(equipment=equipment)]).exercises

    assert exercise.equipment == mapped
    assert exercise.record["equipment"] == equipment


def test_every_upstream_value_has_a_mapping():
    schema = json.loads((SOURCE_FILE.parent / "schema.json").read_text())["properties"]

    assert set(schema["level"]["enum"]) == set(free_exercise_db.LEVELS)
    assert set(schema["category"]["enum"]) == free_exercise_db.CATEGORIES
    assert set(schema["equipment"]["enum"]) - {None} == set(free_exercise_db.EQUIPMENT)
    for muscles in ("primaryMuscles", "secondaryMuscles"):
        assert set(schema[muscles]["items"][0]["enum"]) == set(free_exercise_db.MUSCLES)
    assert set(schema) == free_exercise_db.FIELDS


def test_the_listed_activities_keep_their_patterns_and_the_rest_are_classified_by_rules(
    parsed, by_id
):
    patterns = {item.source_id: item.movement_pattern for item in parsed.exercises}
    classified = (
        classification.WARM_UP_DRILLS | classification.COOL_DOWN_STRETCHES
    ) - set(classification.ACTIVITY_DUPLICATES)

    # the lists decide the warm-up and cool-down activities: a drill or foam rolling is MOBILITY,
    # a held stretch STRETCH, and every cardio record is CARDIO
    for source_id in classified:
        assert patterns[source_id] in (MovementPattern.MOBILITY, MovementPattern.STRETCH)
    for source_id, item in by_id.items():
        if item["category"] == "cardio":
            assert patterns[source_id] is MovementPattern.CARDIO
    # a hidden duplicate of a drill or a stretch stays unclassified
    for source_id in classification.HIDDEN_DUPLICATE_IDS:
        assert patterns[source_id] in (None, MovementPattern.CARDIO), source_id
    # MOBILITY and STRETCH go beyond the lists only by hand (app.catalog.patterns.OTHER_PATTERNS)
    beyond = {
        source_id
        for source_id, p in patterns.items()
        if p in (MovementPattern.MOBILITY, MovementPattern.STRETCH)
    } - classified
    assert beyond == {
        source_id
        for source_id, p in catalog_patterns.OTHER_PATTERNS.items()
        if p in (MovementPattern.MOBILITY, MovementPattern.STRETCH)
    }
    # and every pattern is given to someone (tests/unit/test_movement_patterns.py has the counts)
    assert set(patterns.values()) == {None, *MovementPattern}


# --- Formiq's classification ---


def test_every_classified_id_is_in_the_dataset(by_id):
    listed = (
        classification.WARM_UP_IDS
        | classification.COOL_DOWN_IDS
        | classification.NO_EQUIPMENT_NEEDED
        | classification.EXTRA_MAIN_WORKOUT
        | set(classification.EQUIPMENT_NEEDED)
        | set(classification.EQUIPMENT_NAMED)
        | set(classification.FORMIQ_DUPLICATES)
        | set(classification.ACTIVITY_DUPLICATES)
    )

    assert listed - set(by_id) == set()


def test_warm_up_and_cool_down_activities_are_light_solo_and_need_no_unnamed_equipment(by_id):
    for source_id in classification.WARM_UP_IDS | classification.COOL_DOWN_IDS:
        item = by_id[source_id]
        assert item["level"] == "beginner", source_id
        assert item["category"] in {"stretching", "cardio"}, source_id
        assert not any("partner" in step.casefold() for step in item["instructions"]), source_id


def test_not_every_stretch_is_a_warm_up_or_cool_down(parsed, by_id):
    stretches = {s for s, item in by_id.items() if item["category"] == "stretching"}
    classified = {
        item.source_id
        for item in parsed.exercises
        if {WorkoutSection.WARM_UP, WorkoutSection.COOL_DOWN} & set(item.uses)
    }

    left_out = stretches - classified
    # partner stretches, intermediate ones, and those assessed as unsuitable
    assert {"Lying_Hamstring", "Seated_Glute", "Hamstring_Stretch", "Chin_To_Chest_Stretch"} <= (
        left_out
    )
    assert all(by_id[s]["level"] != "beginner" for s in stretches if "partner" in str(by_id[s]))


@pytest.mark.parametrize(
    ("source_id", "uses"),
    [
        # a strength exercise with named equipment trains
        ("Alternate_Incline_Dumbbell_Curl", ["MAIN_WORKOUT"]),
        # without named equipment, only when its instructions need none
        ("Mountain_Climbers", ["MAIN_WORKOUT"]),
        ("Inverted_Row", []),
        # easy cardio warms up and cools down; jogging only warms up
        ("Recumbent_Bike", ["WARM_UP", "COOL_DOWN"]),
        ("Jogging_Treadmill", ["WARM_UP"]),
        ("Rope_Jumping", []),
        # a dynamic drill warms up, a held stretch cools down, foam rolling does both
        ("Arm_Circles", ["WARM_UP"]),
        ("Tricep_Side_Stretch", ["COOL_DOWN"]),
        ("Hamstring-SMR", ["WARM_UP", "COOL_DOWN"]),
        # a copy of an activity the catalog keeps under another name suits nothing
        ("Walking_Treadmill", []),
        ("Triceps_Stretch", []),
        # a core exercise filed under stretching is a main exercise
        ("Superman", ["MAIN_WORKOUT"]),
        # a pull-up trains, with the bar Formiq links it to
        ("Pullups", ["MAIN_WORKOUT"]),
        # a copy of Formiq's own exercise suits nothing
        ("Bodyweight_Walking_Lunge", []),
        ("Pushups", []),
        # a partner stretch suits nothing here
        ("Seated_Hamstring", []),
    ],
)
def test_examples_of_the_classification(parsed, source_id, uses):
    found = {item.source_id: item.uses for item in parsed.exercises}

    assert [str(use) for use in found[source_id]] == uses


def test_the_classification_counts(parsed):
    counts = {
        section: sum(section in item.uses for item in parsed.exercises)
        for section in WorkoutSection
    }

    # 24 warm-ups and 53 cool-downs before the 13 duplicates (ACTIVITY_DUPLICATES)
    # were hidden: 4 of them were warm-ups and 11 were cool-downs (2 were both)
    assert counts == {
        WorkoutSection.WARM_UP: 20,
        WorkoutSection.MAIN_WORKOUT: 729,
        WorkoutSection.COOL_DOWN: 42,
    }
    assert sum(not item.uses for item in parsed.exercises) == 76 + 13


@pytest.mark.parametrize("source_id", sorted(classification.EQUIPMENT_NEEDED))
def test_formiq_names_the_equipment_a_body_only_record_needs(parsed, by_id, source_id):
    item = next(item for item in parsed.exercises if item.source_id == source_id)

    assert by_id[source_id]["equipment"] == "body only"
    assert item.equipment == list(classification.EQUIPMENT_NEEDED[source_id])
    # the record is kept as it was
    assert item.record == by_id[source_id]


@pytest.mark.parametrize("source_id", sorted(classification.EQUIPMENT_NAMED))
def test_formiq_names_the_equipment_a_machine_record_means(parsed, by_id, source_id):
    """A treadmill record says "machine", and so does a recumbent bike's: the catalog
    names what they are, so a user who has one is found by that name."""
    item = next(item for item in parsed.exercises if item.source_id == source_id)

    assert by_id[source_id]["equipment"] == "machine"
    assert item.equipment == list(classification.EQUIPMENT_NAMED[source_id])
    assert item.equipment != ["Machine"]
    # the record is kept as it was
    assert item.record == by_id[source_id]


def test_the_hidden_duplicates_are_the_two_duplicate_lists(by_id):
    assert classification.HIDDEN_DUPLICATE_IDS == (
        set(classification.FORMIQ_DUPLICATES) | set(classification.ACTIVITY_DUPLICATES)
    )
    assert len(classification.HIDDEN_DUPLICATE_IDS) == 5 + 13
    assert classification.HIDDEN_DUPLICATE_IDS <= set(by_id)


def test_every_other_record_keeps_its_own_equipment(parsed, by_id):
    for item in parsed.exercises:
        corrected = set(classification.EQUIPMENT_NEEDED) | set(classification.EQUIPMENT_NAMED)
        if item.source_id in corrected:
            continue
        named = by_id[item.source_id]["equipment"]
        mapped = free_exercise_db.EQUIPMENT.get(named) if named else None
        assert item.equipment == ([mapped] if mapped else []), item.source_id
