"""Equipment as people name it (app.tools.equipment): one name a tool is given,
and what the user said about their equipment in the conversation.

Both readings are deterministic and match whole names only, so these tests
pin the phrasings they cover, and the near misses they must not read as
equipment.
"""

import pytest

from app.tools.equipment import (
    NO_EQUIPMENT,
    EquipmentName,
    equipment_key,
    read_equipment_name,
    singular,
    stated_equipment,
)

# the keys of the seeded catalog's equipment
CATALOG = [
    equipment_key(name)
    for name in (
        "Barbell", "Dumbbell", "Kettlebell", "Bench", "Squat Rack", "Cable Machine",
        "Smith Machine", "Leg Press Machine", "Pull-up Bar", "Resistance Band",
        "Stationary Bike", "Rowing Machine", "Machine", "Medicine Ball", "Exercise Ball",
        "Foam Roller", "EZ Curl Bar", "Other Equipment",
    )
]  # fmt: skip


def read(name):
    return read_equipment_name(name, CATALOG)


def stated(*texts):
    return stated_equipment(texts, CATALOG)


# --- one name, as a tool is given it ---


@pytest.mark.parametrize(
    ("name", "key"),
    [
        # the catalog's own name, in any case, spacing or hyphenation
        ("Dumbbell", "dumbbell"),
        ("  pull-up_BAR ", "pull up bar"),
        # plurals
        ("dumbbells", "dumbbell"),
        ("Kettlebells", "kettlebell"),
        ("benches", "bench"),
        ("resistance bands", "resistance band"),
        ("medicine balls", "medicine ball"),
        # common phrasing around a piece
        ("a pair of dumbbells", "dumbbell"),
        ("two heavy kettlebells", "kettlebell"),
        ("adjustable dumbbells", "dumbbell"),
        ("my bench", "bench"),
        # other names for a piece
        ("bands", "resistance band"),
        ("a loop band", "resistance band"),
        ("cable", "cable machine"),
        ("cables", "cable machine"),
        ("cable machine", "cable machine"),
        ("pullup bar", "pull up bar"),
        ("chin-up bars", "pull up bar"),
        ("doorway pull up bar", "pull up bar"),
        ("power rack", "squat rack"),
        ("Swiss ball", "exercise ball"),
        ("EZ bar", "ez curl bar"),
        ("exercise bike", "stationary bike"),
        ("rower", "rowing machine"),
        ("leg press", "leg press machine"),
    ],
)
def test_a_name_reads_as_the_catalog_piece_it_means(name, key):
    assert read(name) == EquipmentName(key)


@pytest.mark.parametrize(
    "name",
    [
        "bodyweight",
        "Body-Weight",
        "body only",
        "no equipment",
        "without equipment",
        "None",
        "nothing",
        "nothing available",
        "bodyweight only",
        "just my body weight",
        "equipment-free",
        "without gear",
    ],
)
def test_a_name_for_no_equipment_reads_as_none_at_all(name):
    assert read(name) == EquipmentName(NO_EQUIPMENT)


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("no dumbbells", "dumbbell"),
        ("not a bench", "bench"),
        ("without a pull-up bar", "pull up bar"),
        ("no access to a cable machine", "cable machine"),
        ("don't have kettlebells", "kettlebell"),
    ],
)
def test_a_negated_name_says_the_user_lacks_the_piece(name, key):
    assert read(name) == EquipmentName(key, negated=True)


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("maybe a kettlebell", "kettlebell"),
        ("dumbbells if available", "dumbbell"),
        ("possibly bands", "resistance band"),
        ("a bench if possible", "bench"),
    ],
)
def test_a_doubtful_name_says_the_user_may_not_have_the_piece(name, key):
    assert read(name) == EquipmentName(key, doubtful=True)


@pytest.mark.parametrize(
    "name",
    [
        # two pieces, or a piece and something else: never a partial match
        "dumbbell bench",
        "dumbbells and a bench",
        "band saw",
        "benchmark",
        "barbells plates",
        # not catalog equipment, or too vague to be a piece
        "mat",
        "yoga mat",
        "bar",
        "weights",
        "equipment",
        "Dumbells",
        "not bodyweight",
    ],
)
def test_a_name_that_is_no_piece_reads_as_nothing(name):
    assert read(name).key is None


@pytest.mark.parametrize(
    ("word", "one"),
    [
        ("dumbbells", "dumbbell"),
        ("benches", "bench"),
        ("boxes", "box"),
        ("press", "press"),
        ("bus", "bus"),
        ("chess", "chess"),
        ("bar", "bar"),
    ],
)
def test_only_regular_plurals_are_made_singular(word, one):
    assert singular(word) == one


# --- what the user said ---


@pytest.mark.parametrize(
    ("text", "has"),
    [
        ("I only have dumbbells and resistance bands.", {"dumbbell", "resistance band"}),
        ("I have a pair of dumbbells at home", {"dumbbell"}),
        ("I've got a bench and a pull-up bar", {"bench", "pull up bar"}),
        ("We own kettlebells", {"kettlebell"}),
        ("Make me an upper-body workout with my dumbbells", {"dumbbell"}),
        ("Can you make me a workout using bands?", {"resistance band"}),
        ("Make me a dumbbell workout", {"dumbbell"}),
        ("Just bands", {"resistance band"}),
        # a plain list, answering what they have
        ("Dumbbells and a bench.", {"dumbbell", "bench"}),
        ("Dumbbells are all I have", {"dumbbell"}),
        ("Kettlebells are available", {"kettlebell"}),
    ],
)
def test_what_the_user_says_they_have(text, has):
    assert stated(text).has == has


@pytest.mark.parametrize(
    ("text", "lacks"),
    [
        ("I don't have dumbbells", {"dumbbell"}),
        ("I do not have a bench or a pull-up bar", {"bench", "pull up bar"}),
        ("No kettlebells here", {"kettlebell"}),
        ("I can't use the cable machine", {"cable machine"}),
        ("I have no access to a squat rack", {"squat rack"}),
        ("Without a bench, please", {"bench"}),
    ],
)
def test_what_the_user_says_they_lack(text, lacks):
    result = stated(text)

    assert (result.lacks, result.has) == (lacks, set())


@pytest.mark.parametrize(
    "text",
    [
        "I don't have any equipment.",
        "I have no equipment at home",
        "No equipment",
        "Bodyweight only please",
        "I train with just my body weight",
    ],
)
def test_saying_there_is_no_equipment_lacks_every_piece(text):
    result = stated(text)

    assert result.has_nothing_else
    assert result.lacked(CATALOG) == set(CATALOG)


@pytest.mark.parametrize(
    ("text", "has", "lacks"),
    [
        ("I don't have dumbbells, only bands", {"resistance band"}, {"dumbbell"}),
        ("No bench, just bands", {"resistance band"}, {"bench"}),
        ("I have dumbbells but no bench", {"dumbbell"}, {"bench"}),
        ("I don't have a bench, I have bands", {"resistance band"}, {"bench"}),
        ("I have no equipment except a pair of dumbbells", {"dumbbell"}, set()),
    ],
)
def test_having_some_and_lacking_others(text, has, lacks):
    result = stated(text)

    assert (result.has, result.lacks) == (has, lacks)


@pytest.mark.parametrize(
    "text",
    [
        "I only have dumbbells",
        "I have no equipment except dumbbells",
        "I have dumbbells. I don't have any other equipment.",
        "Dumbbells are all I have",
    ],
)
def test_only_some_pieces_lacks_the_rest(text):
    result = stated(text)

    assert result.has == {"dumbbell"}
    assert result.lacked(CATALOG) == set(CATALOG) - {"dumbbell"}


def test_having_a_piece_alone_says_nothing_about_the_rest():
    result = stated("I have dumbbells")

    assert result.lacked(CATALOG) == set()


@pytest.mark.parametrize(
    "text",
    [
        # questions and possibilities
        "What is a kettlebell good for?",
        "Should I buy a kettlebell?",
        "If I had a bench, what could I do?",
        "I'm thinking of getting resistance bands",
        "Can I use a kettlebell for this?",
        "Dumbbells?",
        # what they had
        "I used to have dumbbells",
        "I sold my barbell last year",
        # a piece in an exercise's name
        "What is a kettlebell swing?",
        "My bench press is weak",
        "How do I do dumbbell rows?",
        "Are band pull-aparts good?",
        # a word that names a piece only in a gym
        "I'm in a band",
        "I bike to work",
        # equipment in general
        "I have some equipment at home",
        "I go to a gym with lots of machines",
        # nothing about equipment
        "Create a workout that only trains my neck.",
        "I only have 20 minutes",
    ],
)
def test_mentioning_a_piece_is_not_having_or_lacking_it(text):
    result = stated(text)

    assert (result.has, result.lacks, result.has_nothing_else) == (set(), set(), False)


def test_a_later_statement_replaces_an_earlier_one():
    assert stated("I don't have dumbbells", "Actually I do have dumbbells now").has == {"dumbbell"}
    later = stated("I have dumbbells", "I don't have dumbbells anymore")
    assert (later.has, later.lacks) == (set(), {"dumbbell"})
    # no equipment at all, then a piece: that piece and nothing else
    some = stated("I don't have any equipment.", "Oh, I have a resistance band")
    assert some.has == {"resistance band"}
    assert some.lacked(CATALOG) == set(CATALOG) - {"resistance band"}


def test_saying_nothing_about_equipment_says_nothing():
    result = stated("What should I do today?", "Make it shorter")

    assert not result.said
    assert result.lacked(CATALOG) == set()
