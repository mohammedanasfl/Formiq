"""Every imported exercise has a description (docs/exercise-fields.md): written by hand for the
cardio records and for three main exercises whose records have no steps, generated for the rest
from what the catalog already holds of the exercise. Without a database; the catalog these give
a database is tested in tests/integration/test_exercise_import.py.
"""

import re
import pytest

from app.catalog import descriptions
from app.catalog.classification import HIDDEN_DUPLICATE_IDS
from app.catalog.free_exercise_db import load_records, parse_records
from app.models import Exercise
from app.schemas.exercise import MovementPattern

P = MovementPattern

# what no description may say: Formiq does not claim a benefit (docs/warm-up-cool-down.md)
CLAIMS = re.compile(
    r"\b(prevent\w*|injur\w*|sore\w*|recover\w*|burn\w*|calorie\w*|boost\w*|improv\w*|"
    r"performance|heal\w*|cure[sd]?|therap\w*|benefit\w*|strengthen\w*|build\w*|tone\w*|"
    r"lose|fat|weight loss)\b",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def dataset():
    return load_records()


@pytest.fixture(scope="module")
def parsed(dataset):
    return parse_records(dataset)


def generated(**fields):
    base = dict(
        difficulty="BEGINNER", pattern=None, category="strength", primary=[], secondary=[],
        equipment=[], has_steps=True,
    )  # fmt: skip
    return descriptions.generated_description(**{**base, **fields})


@pytest.mark.parametrize(
    ("fields", "text"),
    [
        (
            dict(difficulty="INTERMEDIATE", pattern=P.HORIZONTAL_PUSH, primary=["Chest"],
                 secondary=["Shoulders", "Triceps"], equipment=["Barbell", "Bench"]),
            "An intermediate horizontal pushing exercise for the chest, with the shoulders and "
            "triceps helping. Equipment: barbell, bench.",
        ),
        (
            dict(difficulty="BEGINNER", pattern=P.SQUAT, primary=["Quadriceps", "Glutes"]),
            "A beginner squat exercise for the quadriceps and glutes. No equipment.",
        ),
        (
            dict(difficulty="ADVANCED", pattern=P.VERTICAL_PUSH, category="olympic weightlifting",
                 primary=["Shoulders"], secondary=["Quadriceps", "Triceps"], equipment=["Barbell"]),
            "An advanced Olympic weightlifting exercise for the shoulders, with the quadriceps "
            "and triceps helping. Equipment: barbell.",
        ),
        (
            dict(difficulty="INTERMEDIATE", pattern=P.STRETCH, category="stretching",
                 primary=["Hamstrings"]),
            "An intermediate stretch for the hamstrings. No equipment.",
        ),
        (
            dict(difficulty="BEGINNER", pattern=None, category="plyometrics",
                 primary=["Quadriceps"], has_steps=False),
            "A beginner plyometric exercise for the quadriceps. No equipment. "
            "The source gives no steps for it.",
        ),
        (
            dict(difficulty="BEGINNER", pattern=None, category="strength", primary=[]),
            "A beginner exercise. No equipment.",
        ),
    ],
)
def test_a_generated_description_says_what_the_exercise_is(fields, text):
    assert generated(**fields) == text


def test_every_visible_imported_exercise_has_a_description_and_the_hidden_have_none(parsed):
    for item in parsed.exercises:
        if item.source_id in HIDDEN_DUPLICATE_IDS:
            # a hidden duplicate is never shown; two have the cardio text, since a saved plan or a
            # read by id would show their calorie estimate
            assert bool(item.description) == (item.source_id in descriptions.REPLACES_STEPS)
        else:
            assert item.description, item.source_id


def test_no_description_claims_a_benefit_or_a_number_of_calories(parsed):
    for item in parsed.exercises:
        assert item.description is None or not CLAIMS.search(item.description), (
            item.source_id,
            item.description,
        )
    for text in (*descriptions.DESCRIPTIONS.values(), *descriptions.MAIN_DESCRIPTIONS.values()):
        assert not CLAIMS.search(text.replace("Suggested dose", "Dose")), text


def test_a_generated_description_is_one_short_sentence_and_names_its_facts(parsed):
    hand_written = set(descriptions.DESCRIPTIONS) | set(descriptions.MAIN_DESCRIPTIONS)
    for item in parsed.exercises:
        if item.source_id in HIDDEN_DUPLICATE_IDS or item.source_id in hand_written:
            continue
        text = item.description
        assert len(text) <= 260, item.source_id
        assert text[0].isupper() and text.count(". ") <= 2, text
        level = item.difficulty.value.lower()
        assert text.startswith((f"A {level} ", f"An {level} ")), text
        for muscle, role in item.muscles.items():
            if role == "PRIMARY":
                assert muscle.lower() in text, (item.source_id, muscle)
        for name in item.equipment:
            assert name.lower() in text, (item.source_id, name)
        assert ("No equipment." in text) == (not item.equipment), text


def test_the_records_with_no_steps_say_how_to_do_them_or_that_there_are_none(parsed, dataset):
    no_steps = {
        item["id"]
        for item in dataset
        if not any(isinstance(step, str) and step.strip() for step in item.get("instructions", []))
    }
    by_source = {item.source_id: item for item in parsed.exercises}

    assert no_steps == {
        "Iron_Cross", "One-Arm_Kettlebell_Swings", "Push_Press", "Side_Bridge", "Side_Jackknife",
    }  # fmt: skip
    # three are described by hand, as a person says how the movement goes
    assert set(descriptions.MAIN_DESCRIPTIONS) == {
        "Push_Press", "One-Arm_Kettlebell_Swings", "Side_Bridge",
    }  # fmt: skip
    for source_id, text in descriptions.MAIN_DESCRIPTIONS.items():
        assert by_source[source_id].description == text
        assert len(text.split(". ")) >= 2
    # and for the other two the catalog says so, and invents no steps
    for source_id in ("Iron_Cross", "Side_Jackknife"):
        assert by_source[source_id].description.endswith("The source gives no steps for it.")


def test_only_the_machine_cardio_records_have_their_steps_replaced(parsed):
    assert descriptions.REPLACES_STEPS == set(descriptions.DESCRIPTIONS)
    assert descriptions.REPLACES_STEPS == {
        "Bicycling", "Bicycling_Stationary", "Jogging_Treadmill", "Recumbent_Bike",
        "Walking_Treadmill",
    }  # fmt: skip


def exercise(source_id, description, steps):
    record = {"id": source_id, "instructions": steps, "category": "strength"}
    return Exercise(
        name=source_id, difficulty="BEGINNER", description=description, source="FREE_EXERCISE_DB",
        source_id=source_id, source_record=record,
    )  # fmt: skip


def test_a_generated_description_never_hides_the_records_steps():
    """Instructions are the record's, unless the cardio description replaces a machine's menu."""
    steps = ["Lie on the bench.", "Press the bar up."]

    summary = "A beginner exercise for the chest. No equipment."
    assert exercise("Bench_Press", summary, steps).instructions == steps
    assert exercise("Recumbent_Bike", "Sit with your back supported.", steps).instructions == []
    assert exercise("Recumbent_Bike", None, steps).instructions == steps
    # Formiq's own exercise: no record, no steps
    own = Exercise(name="Own", difficulty="BEGINNER", description="Do it.", source="FORMIQ")
    assert own.instructions == []


def test_the_model_reads_nothing_it_would_have_to_import_back():
    """app.models reads app.catalog.descriptions, which imports nothing of Formiq's."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(descriptions))
    imported = [
        node.module or "" for node in ast.walk(tree) if isinstance(node, (ast.ImportFrom, ast.Import))
    ]
    assert all(not name.startswith("app") for name in imported)
