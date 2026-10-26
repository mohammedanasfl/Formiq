"""The muscles a user's message names (app.tools.muscles): what a warm-up or cool-down
search ranks the activities by, so a model that searches the main workout without naming a
muscle ("back and biceps day") still gets the biceps drill first (live QA, 2026-10-19)."""

import pytest

from app.tools.muscles import MUSCLE_WORDS, muscles_named

CATALOG = frozenset(
    {
        "Chest", "Upper Back", "Lats", "Lower Back", "Shoulders", "Front Deltoid",
        "Rear Deltoid", "Biceps", "Triceps", "Forearms", "Core", "Obliques", "Glutes",
        "Quadriceps", "Hamstrings", "Calves", "Abductors", "Adductors", "Neck",
    }
)  # fmt: skip
LEGS = {"Quadriceps", "Hamstrings", "Glutes", "Calves"}
SHOULDERS = {"Shoulders", "Front Deltoid", "Rear Deltoid"}
UPPER_BODY = {"Chest", "Upper Back", "Lats", "Biceps", "Triceps", *SHOULDERS}


def named(text):
    return set(muscles_named(text, CATALOG))


@pytest.mark.parametrize(
    ("message", "muscles"),
    [
        ("I want a chest and triceps workout today, about 40 minutes", {"Chest", "Triceps"}),
        (
            "Back and biceps day today. I've got a pull-up bar, dumbbells and resistance bands",
            {"Upper Back", "Lats", "Biceps"},
        ),
        ("A core workout for today please", {"Core", "Obliques"}),
        ("Leg day today, about 45 minutes", LEGS),
        ("legs please", LEGS),
        ("quads, hamstrings and glutes", {"Quadriceps", "Hamstrings", "Glutes"}),
        ("pecs and delts", {"Chest", *SHOULDERS}),
        ("work my abs and calves", {"Core", "Calves"}),
        ("arms today", {"Biceps", "Triceps", "Forearms"}),
        ("upper body, no equipment", UPPER_BODY),
        ("lower body please", LEGS | {"Adductors", "Abductors"}),
        ("a push day", {"Chest", "Shoulders", "Front Deltoid", "Triceps"}),
        ("a pull workout", {"Upper Back", "Lats", "Rear Deltoid", "Biceps"}),
        ("lower back mobility", {"Lower Back"}),
        ("neck stretches", {"Neck"}),
        ("What warm-up drills do you have for my triceps?", {"Triceps"}),
    ],
)
def test_the_muscles_a_message_names(message, muscles):
    assert named(message) == muscles


@pytest.mark.parametrize(
    "message",
    [
        "a workout for today",
        "full body workout",
        "something quick, about 30 minutes",
        "I have a pull-up bar and a cable machine",
        "I'm back at the gym",
        "back to the gym after a break",
        "an armchair workout",
        "a push-up and a pull-up",
        # the name of an exercise is not a muscle to train (live QA, 2026-10-19: S8)
        "a full-body workout, and put Standing Hip Circles in my warm-up",
        "my hips are tight",
    ],
)
def test_a_message_that_names_no_muscle_names_none(message):
    assert named(message) == set()


@pytest.mark.parametrize(
    ("message", "muscles"),
    [
        ("chest and triceps, no legs", {"Chest", "Triceps"}),
        ("no legs or back today, just arms", {"Biceps", "Triceps", "Forearms"}),
        ("my shoulder hurts, do legs", LEGS),
        ("my shoulders are sore but chest is fine", {"Chest"}),
        ("lower back pain, upper body please", UPPER_BODY),
        ("I did legs yesterday, now chest", {"Chest"}),
        ("avoid shoulders, chest day", {"Chest"}),
        ("legs, without hamstrings", {"Quadriceps", "Glutes", "Calves"}),
        ("upper body, but my shoulders are sore", UPPER_BODY - SHOULDERS),
        ("I tweaked my back, so arms only", {"Biceps", "Triceps", "Forearms"}),
        ("without legs and chest, back day", {"Upper Back", "Lats"}),
    ],
)
def test_a_muscle_the_user_protects_is_never_named(message, muscles):
    """A negation reaches the muscles of its list ("no legs or back"), not past a comma or
    a "but"; a symptom after a muscle skips it. Only the ranking of a search is at stake,
    but a muscle that hurts must never come first."""
    assert named(message) == muscles


def test_a_name_the_catalog_does_not_have_is_dropped():
    assert muscles_named("chest and neck", {"Chest"}) == {"Chest"}
    assert muscles_named("chest", set()) == set()


def test_each_word_names_muscles_of_the_catalog():
    names = {name for muscles in MUSCLE_WORDS.values() for name in muscles}

    assert names <= CATALOG
