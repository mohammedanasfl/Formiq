"""Looking an exercise up by the words of its name (search_exercises' name), the fix of the live
QA of 2026-10-19: the coach said "Standing hip circles are not in the Formiq catalog" about an
exercise the catalog keeps, since no tool could look one up by name."""

import pytest
from pydantic import ValidationError

from app.catalog.classification import (
    ACTIVITY_DUPLICATES,
    DUPLICATE_OF,
    FORMIQ_DUPLICATES,
    HIDDEN_DUPLICATE_IDS,
)
from app.tools.exercise_names import name_matches, name_words
from app.tools.schemas import SearchExercisesInput


def test_the_words_of_a_name_are_lower_case_singular_and_without_filler():
    assert name_words("Hip Circles") == ["hip", "circle"]
    assert name_words("The Cat-Cow exercise") == ["cat", "cow"]
    assert name_words("Push-Ups") == ["push", "up"]
    assert name_words("Dumbbell Press") == ["dumbbell", "press"]
    assert name_words("a drill") == []
    assert name_words("Walking on a treadmill") == ["walking", "treadmill"]


@pytest.mark.parametrize(
    ("name", "query"),
    [
        ("Hip Circles", "hip circle"),
        ("Hip Circles", "HIP CIRCLES"),
        ("Hip Circles", "hip"),
        ("Cat-Cow", "cat cow"),
        ("Cat-Cow", "cat-cow"),
        ("Cat-Cow", "catcow"),
        ("Push-Up", "pushup"),
        ("Push-Up", "pushups"),
        ("Push-Up", "push up"),
        ("Dumbbell Biceps Curl", "biceps curl"),
        ("Dumbbell Biceps Curl", "curl dumbbell"),
        ("Kneeling Hip Flexor Stretch", "kneeling hip flexor"),
        ("Child's Pose", "childs pose"),
        ("Walking, Treadmill", "walking on a treadmill"),
        ("Ankle On The Knee", "ankle on the knee"),
    ],
)
def test_a_name_with_every_word_of_the_query_matches(name, query):
    assert name_matches(name, query)


@pytest.mark.parametrize(
    ("name", "query"),
    [
        ("Hip Circles", "standing hip circles"),
        ("Cat-Cow", "cat stretch"),
        ("Push-Up", "pull up"),
        ("Hip Circles", "ship"),
        ("Bench Press", "bench pres sing"),
        ("Hip Circles", ""),
        ("Hip Circles", "the exercise"),
        ("Arm Circles", "armchair"),
    ],
)
def test_a_name_without_a_word_of_the_query_does_not_match(name, query):
    assert not name_matches(name, query)


def test_a_short_word_is_never_found_inside_another_word():
    # "up" starts a word of "Push-Up" and of "Upright Row", never the middle of one
    assert name_matches("Push-Up", "up")
    assert not name_matches("Cup Press", "up")


def test_the_input_takes_a_name_alone_as_the_one_filter():
    assert SearchExercisesInput(name="hip circle").name == "hip circle"
    assert SearchExercisesInput(name="  cat cow  ").name == "cat cow"
    assert SearchExercisesInput(name="hip circle", use="WARM_UP", muscle="Glutes").name


@pytest.mark.parametrize("bad", ["", " ", "a", "x" * 61, 3, ["hip"]])
def test_the_input_refuses_a_name_that_is_no_words(bad):
    with pytest.raises(ValidationError):
        SearchExercisesInput(name=bad)


def test_every_hidden_duplicate_names_the_exercise_the_catalog_keeps():
    """A search by the hidden name finds this one: it must be there, and different."""
    assert DUPLICATE_OF == {**FORMIQ_DUPLICATES, **ACTIVITY_DUPLICATES}
    assert HIDDEN_DUPLICATE_IDS == frozenset(DUPLICATE_OF)
    assert len(DUPLICATE_OF) == 18
    assert not set(FORMIQ_DUPLICATES) & set(ACTIVITY_DUPLICATES)
    for source_id, kept in DUPLICATE_OF.items():
        assert kept.strip() == kept and kept, source_id
        assert kept.casefold().replace(" ", "_") != source_id.casefold(), source_id
