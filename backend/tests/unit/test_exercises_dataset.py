"""Reading, validating and mapping the exercises-dataset records
(app.catalog.exercises_dataset). No database: the import itself is applied by the
same importer as free-exercise-db's (tests/integration/test_exercise_import.py),
and this source's integration tests come with its dry-run.
"""

import copy
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime

import pytest

from app.catalog import exercises_dataset as ed
from app.catalog.descriptions import REPLACES_STEPS
from app.catalog.exercises_dataset import (
    SOURCE_FILE,
    SOURCE_SHA256,
    SourceFileError,
    load_records,
    parse_records,
)
from app.catalog.free_exercise_db import ParsedSource, SourceExercise
from app.models import Equipment, Exercise, ExerciseMuscle, MuscleGroup
from app.schemas import ExerciseResponse
from app.schemas.exercise import Difficulty, ExerciseSource, MuscleRole
from app.services.exercise_import_service import comparable_name
from tests.migrations import (
    LATER_SEED_REVISION,
    SEED_REVISION,
    SOURCE_REVISION,
    TREADMILL_REVISION,
    migration_module,
)

RECORD = {
    "id": "0001",
    "name": "air squat",
    "category": "upper legs",
    "body_part": "upper legs",
    "equipment": "body weight",
    "instructions": {
        "en": "Stand with your feet apart. Lower your hips. Stand up.",
        "es": "Ponte de pie con los pies separados. Baja las caderas. Levántate.",
    },
    "instruction_steps": {
        "en": ["Stand with your feet apart.", "Lower your hips.", "Stand up."],
        "es": ["Ponte de pie con los pies separados.", "Baja las caderas.", "Levántate."],
    },
    "muscle_group": "glutes",
    "secondary_muscles": ["glutes", "hamstrings"],
    "target": "quads",
    "media_id": "AbCdEfG",
    "image": "images/0001-AbCdEfG.jpg",
    "gif_url": "videos/0001-AbCdEfG.gif",
    "attribution": "© Gym visual — https://gymvisual.com/",
    "created_at": "2026-03-18T12:31:32.854798+00:00",
}


def record(**changes):
    value = copy.deepcopy(RECORD)
    for key, change in changes.items():
        if change is ...:
            del value[key]
        else:
            value[key] = change
    return value


def only(records):
    """The one exercise the records parse to."""
    parsed = parse_records(records)
    assert parsed.rejected == []
    (exercise,) = parsed.exercises
    return exercise


def rejection(records):
    """The one rejection the records give, and the parse it came from."""
    parsed = parse_records(records)
    assert parsed.exercises == []
    (rejected,) = parsed.rejected
    return rejected, parsed


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
    assert len(dataset) == 1324
    # the provenance record names the same commit and checksums
    directory = SOURCE_FILE.parent
    provenance = (directory / "SOURCE.md").read_text()
    assert ed.SOURCE_VERSION in provenance
    assert SOURCE_SHA256 in provenance
    for name in ("exercises.schema.json", "LICENSE", "NOTICE.md"):
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() in provenance
    # the licence travels with the data, and the media terms with it
    assert (directory / "LICENSE").read_text().startswith("MIT License")
    assert "Gym visual" in (directory / "NOTICE.md").read_text()
    assert ed.SOURCE == ExerciseSource.EXERCISES_DATASET


def test_no_image_or_gif_is_vendored():
    names = {path.name for path in SOURCE_FILE.parent.iterdir()}
    assert names == {"exercises.json", "exercises.schema.json", "LICENSE", "NOTICE.md", "SOURCE.md"}


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


# --- what the pinned dataset gives ---


def test_every_record_is_accounted_for_exactly_once(dataset, parsed):
    assert isinstance(parsed, ParsedSource)
    assert all(isinstance(item, SourceExercise) for item in parsed.exercises)
    imported = [item.source_id for item in parsed.exercises]
    rejected = [item.source_id for item in parsed.rejected]
    assert None not in rejected
    assert len(imported) + len(rejected) == len(dataset) == 1324
    assert sorted(imported + rejected) == sorted(item["id"] for item in dataset)
    # in source id order, whatever the file's order
    assert imported == sorted(imported)
    assert all(item.reasons for item in parsed.rejected)


def test_the_counts_of_the_pinned_dataset(parsed):
    assert len(parsed.exercises) == 731
    assert len(parsed.rejected) == 593
    first = Counter(ed.reason_of(item.reasons[0]) for item in parsed.rejected)
    assert first == {
        ed.AMBIGUOUS_EQUIPMENT: 495,
        ed.UNUSABLE_EQUIPMENT_VALUE: 51,
        ed.UNMAPPED_PRIMARY_MUSCLE: 45,
        ed.DUPLICATE_NAME: 2,
    }
    # a record can have several reasons: eight are also held for a primary muscle
    anyone = Counter(ed.reason_of(reason) for item in parsed.rejected for reason in item.reasons)
    assert anyone == {
        ed.AMBIGUOUS_EQUIPMENT: 495,
        ed.UNMAPPED_PRIMARY_MUSCLE: 53,
        ed.UNUSABLE_EQUIPMENT_VALUE: 51,
        ed.DUPLICATE_NAME: 2,
    }
    assert sum(1 for item in parsed.rejected if len(item.reasons) > 1) == 8
    assert parsed.unknown_fields == set()
    assert parsed.unresolved == {
        "equipment": {"assisted", "weighted"},
        "primary muscles": {"cardiovascular system", "serratus anterior", "spine"},
        "secondary muscles": {
            "ankle stabilizers",
            "ankles",
            "back",
            "feet",
            "hip flexors",
            "shins",
        },
    }


def test_the_records_held_for_a_duplicate_name_are_the_later_of_each_pair(parsed, by_id):
    held = [r for r in parsed.rejected if ed.DUPLICATE_NAME in {ed.reason_of(x) for x in r.reasons}]
    assert [item.source_id for item in held] == ["0577", "0656"]
    # the lowest id keeps the name, and the reason names it
    assert "record 0576" in held[0].reasons[0]
    assert "record 0655" in held[1].reasons[0]
    assert by_id["0577"]["name"] == by_id["0576"]["name"]


def test_the_importable_exercises_by_equipment(parsed):
    needs = Counter((item.equipment[0] if item.equipment else None) for item in parsed.exercises)
    assert needs == {
        None: 176,
        "Cable Machine": 110,
        "Dumbbell": 105,
        "Machine": 93,
        "Barbell": 86,
        "Resistance Band": 44,
        "Kettlebell": 35,
        "Smith Machine": 23,
        "Other Equipment": 22,
        "Exercise Ball": 17,
        "Medicine Ball": 12,
        "EZ Curl Bar": 8,
    }


def test_an_importable_record_with_a_missing_secondary_muscle_group_says_so(parsed):
    warned = [item for item in parsed.exercises if item.warnings]
    assert len(warned) == 66
    assert all(w.startswith("secondary muscle ") for item in warned for w in item.warnings)
    assert all("not linked" in w for item in warned for w in item.warnings)


# --- provenance, and what is kept of the record ---


def test_the_external_id_and_the_record_are_kept(parsed, by_id):
    for item in parsed.exercises:
        assert item.record["id"] == item.source_id
        original = by_id[item.source_id]
        assert item.record["name"] == original["name"]
        # every field is kept, as it was, but the instructions
        for field in ed.FIELDS - {"instructions", "instruction_steps"}:
            assert item.record[field] == original[field]
        assert set(item.record) == ed.FIELDS


def test_only_the_english_instructions_are_kept(parsed, by_id):
    for item in parsed.exercises:
        original = by_id[item.source_id]
        assert item.record["instructions"] == {"en": original["instructions"]["en"]}
        assert item.record["instruction_steps"] == {"en": original["instruction_steps"]["en"]}
        assert item.record["instruction_steps"]["en"]
    # the nine other languages are in the file, which is hashed, not in the database
    assert all(len(item["instruction_steps"]) == 10 for item in by_id.values())


def test_the_steps_are_kept_unchanged_whatever_they_say(parsed, by_id):
    # 43 records' steps carry upstream doses ("hold for 20-30 seconds"): they stay the
    # source's words, in the steps, and are never made a dose of Formiq's
    for item in parsed.exercises:
        original = by_id[item.source_id]
        assert item.record["instruction_steps"]["en"] == original["instruction_steps"]["en"]
    dose = re.compile(r"\b\d+\s*(seconds?|minutes?)\b")
    dosed = [
        item
        for item in parsed.exercises
        if dose.search(" ".join(item.record["instruction_steps"]["en"]))
    ]
    assert dosed
    assert all(item.uses == [] for item in dosed)


def test_english_record_changes_nothing_else():
    original = record(extra="kept")
    kept = ed.english_record(original)

    assert kept["instructions"] == {"en": original["instructions"]["en"]}
    assert kept["instruction_steps"] == {"en": original["instruction_steps"]["en"]}
    assert {k: v for k, v in kept.items() if k not in ("instructions", "instruction_steps")} == {
        k: v for k, v in original.items() if k not in ("instructions", "instruction_steps")
    }
    # the record it was made from is not changed
    assert set(original["instruction_steps"]) == {"en", "es"}


def test_an_unknown_field_is_kept_and_reported():
    parsed = parse_records([record(extra="kept")])

    assert parsed.unknown_fields == {"extra"}
    assert parsed.exercises[0].record["extra"] == "kept"


def test_the_exercise_model_reads_the_steps_where_this_source_keeps_them():
    steps = ["Stand.", "Squat."]
    exercise = Exercise(
        source="EXERCISES_DATASET",
        source_id="0001",
        source_record={"instruction_steps": {"en": steps, "es": ["De pie."]}, "category": "waist"},
    )

    assert exercise.instructions == steps
    # its category is a body part, not a kind of training: none is shown
    assert exercise.category is None
    # a malformed record reads as no steps, not as a crash
    for broken in (None, {}, {"instruction_steps": []}, {"instruction_steps": {"en": "x"}}):
        assert Exercise(source="EXERCISES_DATASET", source_record=broken).instructions == []
    mixed = {"instruction_steps": {"en": ["a", 3, "b"]}}
    assert Exercise(source="EXERCISES_DATASET", source_record=mixed).instructions == ["a", "b"]


def test_free_exercise_dbs_steps_and_category_are_read_as_before():
    exercise = Exercise(
        source="FREE_EXERCISE_DB",
        source_id="Barbell_Curl",
        source_record={"instructions": ["Curl."], "category": "strength"},
    )
    assert exercise.instructions == ["Curl."]
    assert exercise.category == "strength"


def test_free_exercise_dbs_replaced_steps_stay_replaced_and_another_sources_ids_never_are():
    source_id = next(iter(REPLACES_STEPS))
    free = Exercise(
        source="FREE_EXERCISE_DB",
        source_id=source_id,
        description="Formiq's own",
        source_record={"instructions": ["a menu"], "category": "cardio"},
    )
    assert free.instructions == []
    # the same id string in another source's record is just an id
    other = Exercise(
        source="EXERCISES_DATASET",
        source_id=source_id,
        description="x",
        source_record={"instruction_steps": {"en": ["Step."]}},
    )
    assert other.instructions == ["Step."]


def test_an_imported_exercise_validates_as_the_api_response():
    item = only([record()])
    exercise = Exercise(
        id=1500,
        name=item.name,
        description=item.description,
        difficulty=item.difficulty,
        movement_pattern=item.movement_pattern,
        uses=item.uses,
        image_paths=item.image_paths,
        source=ed.SOURCE,
        source_id=item.source_id,
        source_version=ed.SOURCE_VERSION,
        source_record=item.record,
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        muscles=[
            ExerciseMuscle(muscle_group=MuscleGroup(id=14, name="Quadriceps"), role="PRIMARY")
        ],
        equipment=[],
    )

    response = ExerciseResponse.model_validate(exercise).model_dump(mode="json")

    assert response["source"] == "EXERCISES_DATASET"
    assert (response["source_id"], response["source_version"]) == ("0001", ed.SOURCE_VERSION)
    assert response["difficulty"] == "UNRATED"
    assert response["instructions"] == record()["instruction_steps"]["en"]
    assert response["category"] is None
    assert (response["images"], response["uses"], response["movement_pattern"]) == ([], [], None)
    assert response["equipment"] == []


# --- nothing made up, no media ---


def test_nothing_is_made_up(parsed):
    for item in parsed.exercises:
        # the source has no level; none is guessed
        assert item.difficulty == Difficulty.UNRATED
        # nothing classifies it for a section, a pattern or a description
        assert item.uses == []
        assert item.movement_pattern is None
        assert item.description is None
        # and the record has no field for a dose or a level
        assert not {"difficulty", "level", "sets", "reps", "rest"} & set(item.record)


def test_no_image_or_gif_is_registered(parsed, by_id):
    assert all(item.image_paths == [] for item in parsed.exercises)
    # the references stay in the record as text that is never followed
    for item in parsed.exercises:
        original = by_id[item.source_id]
        for field in ("image", "gif_url", "media_id", "attribution"):
            assert isinstance(item.record[field], str)
            assert item.record[field] == original[field]
    # the module never looks for an image file
    assert not hasattr(ed, "resolve_image")
    assert "images_dir" not in ed.parse_records.__code__.co_varnames


# --- names ---


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("3/4 sit-up", "3/4 Sit-Up"),
        ("45° side bend", "45° Side Bend"),
        ("ez barbell spider curl", "EZ Barbell Spider Curl"),
        ("sled 45° leg press (side pov)", "Sled 45° Leg Press (Side POV)"),
        ("jm bench press", "JM Bench Press"),
        ("sz-bar curl", "SZ-Bar Curl"),
        ("l-sit on floor", "L-Sit On Floor"),
        ("push-up (on stability ball)", "Push-Up (On Stability Ball)"),
        ("stationary bike run v. 3", "Stationary Bike Run V. 3"),
        ("the 3rd rep", "The 3rd Rep"),
        ("  air squat  ", "Air Squat"),
    ],
)
def test_a_name_is_shown_in_title_case_with_its_acronyms(name, shown):
    assert ed.display_name(name) == shown


def test_a_name_shown_has_the_words_it_had(parsed, by_id):
    for item in parsed.exercises:
        original = by_id[item.source_id]["name"]
        corrected = ed.MALFORMED_NAMES.get(item.source_id, (original, original))[1]
        assert comparable_name(item.name) == comparable_name(corrected)
        assert item.name == item.name.strip()
        assert item.name[0].isalnum()


def test_names_are_compared_as_the_importer_compares_them(dataset):
    for item in dataset:
        assert ed.comparable_name(item["name"]) == comparable_name(item["name"])


def test_the_four_malformed_names_are_corrected_explicitly(dataset, parsed, by_id):
    odd = {
        item["id"]: item["name"]
        for item in dataset
        if not ed.NAME_CHARACTERS.fullmatch(item["name"])
    }
    # exactly the four records the audit found, and nothing else is repaired
    assert odd == {source_id: bad for source_id, (bad, _) in ed.MALFORMED_NAMES.items()}
    assert set(odd) == {"0738", "0739", "0740", "1464"}
    shown = {item.source_id: item.name for item in parsed.exercises}
    assert shown["0738"] == "Sled 45° Calf Press"
    assert shown["0739"] == "Sled 45° Leg Press"
    assert shown["0740"] == "Sled 45° Leg Wide Press"
    assert shown["1464"] == "Sled 45° Leg Press (Back POV)"
    for source_id, (bad, good) in ed.MALFORMED_NAMES.items():
        assert bad.replace("в°", "°") == good
        # the original name is kept in the record
        assert by_id[source_id]["name"] == bad
        assert next(i for i in parsed.exercises if i.source_id == source_id).record["name"] == bad


def test_a_malformed_name_that_is_not_one_of_the_four_is_rejected_not_repaired():
    for changes in (
        {"name": "sled 45в° leg press"},  # the right fault, but not a listed record's
        {"id": "0738", "name": "sled 45в° leg press"},  # a listed record, but another name
        {"name": "squat 💪"},
    ):
        rejected, _ = rejection([record(**changes)])
        assert ed.reason_of(rejected.reasons[0]) == ed.INVALID_NAME
        assert "unexpected character" in rejected.reasons[0]


def test_a_name_another_record_has_is_rejected_and_the_lowest_id_keeps_it():
    first = record(id="0576", name="lever chest press")
    second = record(id="0577", name="Lever  Chest-Press")
    # whatever the order in the file
    for records in ([first, second], [second, first]):
        parsed = parse_records(records)
        assert [item.source_id for item in parsed.exercises] == ["0576"]
        (rejected,) = parsed.rejected
        assert rejected.source_id == "0577"
        assert ed.reason_of(rejected.reasons[0]) == ed.DUPLICATE_NAME
        assert "record 0576" in rejected.reasons[0]


def test_a_held_record_does_not_take_its_name():
    held = record(id="0001", equipment="weighted")
    free = record(id="0002")

    parsed = parse_records([held, free])

    assert [item.source_id for item in parsed.exercises] == ["0002"]
    assert [item.source_id for item in parsed.rejected] == ["0001"]


def test_a_repeated_id_is_rejected():
    parsed = parse_records([record(), record(name="another squat")])

    assert len(parsed.exercises) == 1
    (rejected,) = parsed.rejected
    assert "another record has the id '0001'" in rejected.reasons[0]


# --- validation ---


@pytest.mark.parametrize(
    ("changes", "kind", "text"),
    [
        ({"media_id": ...}, ed.INVALID_RECORD, "missing fields: media_id"),
        ({"id": "12"}, ed.INVALID_RECORD, "id must be four digits"),
        ({"id": 12}, ed.INVALID_RECORD, "id must be four digits"),
        ({"name": "   "}, ed.INVALID_NAME, "non-blank"),
        ({"name": 5}, ed.INVALID_NAME, "non-blank"),
        ({"name": "a" * 151}, ed.INVALID_NAME, "longer than 150"),
        ({"body_part": "feet"}, ed.INVALID_RECORD, "unknown body_part"),
        ({"category": ""}, ed.INVALID_RECORD, "category must be non-blank text"),
        ({"image": "../etc/passwd.jpg"}, ed.INVALID_RECORD, "image is not the path"),
        ({"gif_url": "videos/a.png"}, ed.INVALID_RECORD, "gif_url is not the path"),
        ({"instructions": {"es": "x"}}, ed.INVALID_RECORD, "instructions.en"),
        ({"instructions": "text"}, ed.INVALID_RECORD, "instructions.en"),
        ({"instruction_steps": {"en": "text"}}, ed.INVALID_RECORD, "instruction_steps.en"),
        ({"instruction_steps": {"en": [1]}}, ed.INVALID_RECORD, "instruction_steps.en"),
        ({"secondary_muscles": "glutes"}, ed.INVALID_RECORD, "secondary_muscles must be"),
        ({"target": " "}, ed.INVALID_RECORD, "target must be non-blank text"),
        ({"equipment": 5}, ed.INVALID_RECORD, "equipment must be non-blank text"),
        ({"created_at": 5}, ed.INVALID_RECORD, "created_at must be text"),
    ],
)
def test_a_malformed_record_is_rejected_with_its_reason(changes, kind, text):
    rejected, _ = rejection([record(**changes)])

    assert ed.reason_of(rejected.reasons[0]) == kind
    assert text in " ".join(rejected.reasons)


def test_a_record_that_is_not_an_object_is_rejected():
    rejected, _ = rejection(["not a record"])

    assert (rejected.index, rejected.source_id) == (0, None)
    assert rejected.reasons == [f"{ed.INVALID_RECORD}: not an object"]


def test_an_incomplete_record_is_imported_with_a_warning():
    empty = only([record(instruction_steps={"en": []})])
    blank = only([record(instruction_steps={"en": ["Stand.", " "]})])

    assert empty.warnings == ["no instructions"]
    assert blank.warnings == ["a blank instruction step"]


# --- equipment ---


def catalog_equipment():
    names = set()
    for revision in (SEED_REVISION, LATER_SEED_REVISION, SOURCE_REVISION):
        names |= set(migration_module(revision).EQUIPMENT)
    return names | {migration_module(TREADMILL_REVISION).NAME}


def test_every_equipment_value_has_a_mapping_or_a_reason_and_none_is_both(dataset):
    values = {item["equipment"] for item in dataset}

    assert values == set(ed.EQUIPMENT) | set(ed.UNUSABLE_EQUIPMENT)
    assert not set(ed.EQUIPMENT) & set(ed.UNUSABLE_EQUIPMENT)
    assert len(values) == 28


def test_equipment_maps_only_to_the_catalogs_own_equipment():
    targets = {name for name in ed.EQUIPMENT.values() if name}

    assert targets <= catalog_equipment()
    # nothing but body weight needs none
    assert [value for value, name in ed.EQUIPMENT.items() if name is None] == ["body weight"]


@pytest.mark.parametrize(
    ("value", "needs"),
    [
        ("dumbbell", ["Dumbbell"]),
        ("barbell", ["Barbell"]),
        ("olympic barbell", ["Barbell"]),
        ("ez barbell", ["EZ Curl Bar"]),
        ("cable", ["Cable Machine"]),
        ("band", ["Resistance Band"]),
        ("resistance band", ["Resistance Band"]),
        ("stability ball", ["Exercise Ball"]),
        ("leverage machine", ["Machine"]),
        ("elliptical machine", ["Machine"]),
        ("trap bar", ["Other Equipment"]),
        ("roller", ["Other Equipment"]),
        ("rope", ["Other Equipment"]),
        ("body weight", []),
    ],
)
def test_equipment_is_mapped_through_the_table(value, needs):
    # a record whose text names no other gear
    assert only([record(equipment=value)]).equipment == needs


@pytest.mark.parametrize("value", ["weighted", "assisted"])
def test_a_value_that_is_not_a_piece_of_equipment_holds_the_record(value, parsed, by_id):
    rejected, outcome = rejection([record(equipment=value)])

    assert ed.reason_of(rejected.reasons[0]) == ed.UNUSABLE_EQUIPMENT_VALUE
    assert value in rejected.reasons[0]
    assert outcome.unresolved == {"equipment": {value}}
    # every record of the pinned file with it is held, none is imported
    ids = {i for i, item in by_id.items() if item["equipment"] == value}
    assert ids
    assert not ids & {item.source_id for item in parsed.exercises}
    assert ids <= {item.source_id for item in parsed.rejected}


def test_an_unknown_equipment_value_is_never_mapped_to_body_weight():
    rejected, outcome = rejection([record(equipment="trampoline")])

    assert ed.reason_of(rejected.reasons[0]) == ed.UNKNOWN_EQUIPMENT
    assert outcome.unresolved == {"equipment": {"trampoline"}}


def test_body_weight_is_not_taken_for_no_equipment_when_the_text_names_gear(by_id):
    # the dataset's own README example: a pull-up filed under body weight
    named = (("pull-up", "0652"), ("inverted row", "0499"), ("monster walk", "0628"))
    for name, source_id in named:
        assert by_id[source_id]["equipment"] == "body weight"
        rejected, _ = rejection([by_id[source_id]])
        assert ed.reason_of(rejected.reasons[0]) == ed.AMBIGUOUS_EQUIPMENT, name


def test_unnamed_gear_is_read_from_the_name_and_the_steps():
    assert ed.unnamed_gear("air squat", ["Stand."], "body weight") == []
    assert ed.unnamed_gear("bench dip", ["Sit."], "body weight") == ["bench"]
    assert ed.unnamed_gear("air squat", ["Sit on a bench or chair."], "body weight") == [
        "bench",
        "chair",
    ]
    assert ed.unnamed_gear("dumbbell incline press", ["Press."], "dumbbell") == ["incline"]
    assert ed.unnamed_gear("barbell step-up", ["Step."], "barbell") == ["step"]
    assert ed.unnamed_gear("lunge", ["Step forward."], "body weight") == []
    # a whole word only
    assert ed.unnamed_gear("boxing", ["Stand on the tableau."], "body weight") == []
    assert ed.unnamed_gear("air squat", ["Hold a pole."], "body weight") == ["pole"]


def test_what_the_equipment_value_names_is_not_ambiguous():
    assert ed.unnamed_gear("barbell curl", ["Grip the bar, with plates on it."], "barbell") == []
    assert ed.unnamed_gear("dumbbell curl", ["Hold a dumbbell."], "dumbbell") == []
    assert ed.unnamed_gear("band row", ["Hold the band."], "band") == []
    assert ed.unnamed_gear("cable row", ["Hold the bar, rope or strap."], "cable") == []
    assert ed.unnamed_gear("ball crunch", ["Lie on the exercise ball."], "stability ball") == []
    # but another piece of gear is
    assert ed.unnamed_gear("dumbbell press", ["Lie on a bench."], "dumbbell") == ["bench"]
    assert ed.unnamed_gear("band pull-up", ["Hang from a pull-up bar."], "band") == ["bar"]
    assert ed.unnamed_gear("dumbbell curl", ["Sit on the exercise ball."], "dumbbell") == ["ball"]


def test_a_machines_own_seat_and_bench_are_not_other_gear():
    steps = ["Sit on the bench of the machine and hold the bar."]
    for value in ed.MACHINES:
        assert ed.unnamed_gear("lever incline chest press", steps, value) == []
    # a cable is not a machine in this sense: its bench is a bench
    assert ed.unnamed_gear("cable bench press", steps, "cable") == ["bench"]


def test_the_importable_exercises_that_need_no_equipment_name_no_gear(parsed, by_id):
    # an independent, plainer check than the table that held the others
    plain = re.compile(
        r"\b(bench|chair|box|bars?|rings?|towel|band|dumbbells?|barbell|kettlebell|rope|strap|"
        r"platform|rack|incline|decline)\b",
        re.IGNORECASE,
    )
    free = [item for item in parsed.exercises if not item.equipment]
    assert len(free) == 176
    for item in free:
        original = by_id[item.source_id]
        assert original["equipment"] == "body weight"
        text = original["name"] + " " + " ".join(original["instruction_steps"]["en"])
        assert not plain.search(text), original["name"]


def test_the_records_held_for_ambiguous_equipment_by_the_value_they_say(parsed, by_id):
    held = Counter(
        by_id[item.source_id]["equipment"]
        for item in parsed.rejected
        if any(ed.reason_of(reason) == ed.AMBIGUOUS_EQUIPMENT for reason in item.reasons)
    )
    assert held == {
        "body weight": 122,
        "dumbbell": 188,
        "barbell": 70,
        "cable": 47,
        "smith machine": 25,
        "ez barbell": 15,
        "band": 12,
        "kettlebell": 6,
        "resistance band": 4,
        "stability ball": 3,
        "medicine ball": 1,
        "rope": 1,
        "bosu ball": 1,
    }
    assert sum(held.values()) == 495
    # no machine is held for its own seat
    assert not held.keys() & ed.MACHINES


def test_every_ambiguous_reason_names_the_gear(parsed):
    for item in parsed.rejected:
        for reason in item.reasons:
            if ed.reason_of(reason) == ed.AMBIGUOUS_EQUIPMENT:
                assert re.fullmatch(
                    r"ambiguous equipment: the record says '[^']+' but its text names [a-z ,]+",
                    reason,
                )


# --- muscles ---


def catalog_muscle_groups():
    return set(migration_module(SEED_REVISION).MUSCLE_GROUPS) | set(
        migration_module(SOURCE_REVISION).MUSCLE_GROUPS
    )


def test_every_muscle_value_has_an_entry_and_every_entry_is_used(dataset):
    values = {item["target"] for item in dataset} | {
        muscle for item in dataset for muscle in item["secondary_muscles"]
    }

    assert values == set(ed.MUSCLES)


def test_muscles_map_only_to_the_catalogs_own_groups():
    assert {name for name in ed.MUSCLES.values() if name} <= catalog_muscle_groups()


@pytest.mark.parametrize(
    ("value", "group"),
    [
        ("abs", "Core"),
        ("pectorals", "Chest"),
        ("delts", "Shoulders"),
        ("quads", "Quadriceps"),
        ("traps", "Upper Back"),
        ("rhomboids", "Upper Back"),
        ("rear deltoids", "Rear Deltoid"),
        ("levator scapulae", "Neck"),
        # contained in a group, by judgement
        ("brachialis", "Biceps"),
        ("rotator cuff", "Shoulders"),
        ("groin", "Adductors"),
        ("grip muscles", "Forearms"),
        # none
        ("spine", None),
        ("serratus anterior", None),
        ("cardiovascular system", None),
        ("hip flexors", None),
        ("back", None),
    ],
)
def test_muscles_are_mapped_through_the_table(value, group):
    assert ed.MUSCLES[value] == group


def test_the_primary_muscle_is_the_target_and_each_group_is_linked_once():
    both = record(target="biceps", secondary_muscles=["biceps", "forearms", "wrists"])
    muscles = only([both]).muscles

    # the target is primary, a group that is also secondary stays primary, and two
    # source muscles of one group are one link
    assert muscles == {"Biceps": MuscleRole.PRIMARY, "Forearms": MuscleRole.SECONDARY}
    assert only([record(target="delts", secondary_muscles=["deltoids"])]).muscles == {
        "Shoulders": MuscleRole.PRIMARY
    }
    assert only([record(target="quads", secondary_muscles=["traps", "rhomboids"])]).muscles == {
        "Quadriceps": MuscleRole.PRIMARY,
        "Upper Back": MuscleRole.SECONDARY,
    }


def test_muscle_group_is_not_read(dataset):
    # the field is always the first secondary muscle, so it adds nothing
    assert all(item["muscle_group"] == item["secondary_muscles"][0] for item in dataset)
    assert only([record(muscle_group="zzz")]).muscles == only([record()]).muscles


def test_every_importable_record_has_one_primary_muscle(parsed, by_id):
    for item in parsed.exercises:
        original = by_id[item.source_id]
        primary = [group for group, role in item.muscles.items() if role == MuscleRole.PRIMARY]
        assert primary == [ed.MUSCLES[original["target"]]]
        assert list(item.muscles)[0] == primary[0]


@pytest.mark.parametrize("target", ["cardiovascular system", "serratus anterior", "spine"])
def test_a_primary_muscle_with_no_group_holds_the_record(target):
    rejected, outcome = rejection([record(target=target)])

    assert ed.reason_of(rejected.reasons[0]) == ed.UNMAPPED_PRIMARY_MUSCLE
    assert outcome.unresolved == {"primary muscles": {target}}


def test_the_pinned_records_held_for_a_primary_muscle(parsed, by_id):
    held = [
        by_id[item.source_id]["target"]
        for item in parsed.rejected
        if any(ed.reason_of(reason) == ed.UNMAPPED_PRIMARY_MUSCLE for reason in item.reasons)
    ]
    assert Counter(held) == {"cardiovascular system": 29, "spine": 19, "serratus anterior": 5}
    # so no cardio record is imported: its only target is not a muscle
    assert all(by_id[item.source_id]["body_part"] != "cardio" for item in parsed.exercises)


def test_an_unknown_muscle_is_rejected_never_dropped_or_mapped():
    primary, outcome = rejection([record(target="rhomboideus")])
    secondary, other = rejection([record(secondary_muscles=["glutes", "ears"])])

    assert ed.reason_of(primary.reasons[0]) == ed.UNKNOWN_MUSCLE
    assert outcome.unresolved == {"muscles": {"rhomboideus"}}
    assert ed.reason_of(secondary.reasons[0]) == ed.UNKNOWN_MUSCLE
    assert other.unresolved == {"muscles": {"ears"}}


def test_a_secondary_muscle_with_no_group_is_left_unlinked_reported_and_kept():
    parsed = parse_records([record(secondary_muscles=["glutes", "hip flexors"])])

    (item,) = parsed.exercises
    assert item.muscles == {"Quadriceps": MuscleRole.PRIMARY, "Glutes": MuscleRole.SECONDARY}
    assert item.warnings == [
        "secondary muscle 'hip flexors' has no Formiq muscle group: not linked "
        "(the record keeps it)"
    ]
    assert parsed.unresolved == {"secondary muscles": {"hip flexors"}}
    assert item.record["secondary_muscles"] == ["glutes", "hip flexors"]


def test_every_reason_of_a_record_is_given():
    # held for its equipment and for its primary muscle at once
    rejected, _ = rejection([record(equipment="weighted", target="spine")])

    assert [ed.reason_of(reason) for reason in rejected.reasons] == [
        ed.UNUSABLE_EQUIPMENT_VALUE,
        ed.UNMAPPED_PRIMARY_MUSCLE,
    ]
