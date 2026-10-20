"""How a search ranks warm-up and cool-down activities once main exercises have been found
(app.tools.formiq_tools.most_relevant): the ones a proposal can use come first."""

from types import SimpleNamespace

from app.schemas.exercise import MovementPattern, MuscleRole, WorkoutSection
from app.tools.formiq_tools import most_relevant

WARM_UP = WorkoutSection.WARM_UP
PRIMARY, SECONDARY = MuscleRole.PRIMARY, MuscleRole.SECONDARY


def activity(name, primary, secondary=(), pattern=MovementPattern.MOBILITY):
    muscles = [
        SimpleNamespace(role=role, muscle_group=SimpleNamespace(name=muscle))
        for role, group in ((PRIMARY, primary), (SECONDARY, secondary))
        for muscle in group
    ]
    return SimpleNamespace(
        id=len(name), name=name, movement_pattern=pattern, muscles=muscles, uses=["WARM_UP"],
        source="FORMIQ", category=None,
    )


def ranked(exercises, main=None, muscle=None):
    return [item.name for item in most_relevant(exercises, use=WARM_UP, muscle=muscle, main=main)]


CARDIO = activity("Walk", ["Calves"], pattern=MovementPattern.CARDIO)
CHEST = activity("Chest drill", ["Chest"])
SHOULDER_ONLY_SECONDARY = activity("Hip drill", ["Glutes"], ["Shoulders"])
ANKLES = activity("Ankle drill", ["Calves"])
# the chest and triceps exercises, with the muscles they train, primary or secondary
PUSH = {1: frozenset({"Chest", "Triceps", "Shoulders"})}


def test_activities_a_main_exercise_suits_come_before_ones_none_suits():
    everything = [ANKLES, SHOULDER_ONLY_SECONDARY, CHEST, CARDIO]

    assert ranked(everything, main=PUSH) == ["Walk", "Chest drill", "Hip drill", "Ankle drill"]


def test_without_main_exercises_the_order_is_the_one_it_was():
    everything = [ANKLES, SHOULDER_ONLY_SECONDARY, CHEST, CARDIO]

    assert ranked(everything) == ranked(everything, main={}) == ranked(everything, main=None)
    assert ranked(everything)[0] == "Walk"


def test_easy_cardio_is_first_whatever_the_main_exercises_are():
    assert ranked([CHEST, CARDIO], main={1: frozenset({"Quadriceps"})})[0] == "Walk"


def test_a_muscle_asked_for_comes_before_what_the_main_exercises_suit():
    """The search said what it wants: the primary muscle it names first, then fit."""
    biceps = activity("Biceps drill", ["Biceps"])
    chest_with_biceps_secondary = activity("Chest drill 2", ["Chest"], ["Biceps"])

    order = ranked([chest_with_biceps_secondary, biceps], main=PUSH, muscle="Biceps")

    # the biceps one is first although no main exercise trains the biceps
    assert order == ["Biceps drill", "Chest drill 2"]


def test_the_order_is_the_same_for_the_same_matches():
    everything = [ANKLES, SHOULDER_ONLY_SECONDARY, CHEST, CARDIO]

    assert ranked(everything, main=PUSH) == ranked(list(reversed(everything)), main=PUSH)


def made(name, uses, source="FORMIQ", pattern=MovementPattern.STRETCH):
    item = activity(name, ["Hamstrings"], pattern=pattern)
    item.uses, item.source = uses, source
    return item


def test_what_no_section_uses_comes_after_what_a_section_does():
    """A stretch Formiq keeps but uses for no section cannot go into a workout, so a search with
    no section lists it last, whatever its name or pattern says (docs/exercise-fields.md)."""
    exercises = [
        made("A stretch no section uses", []),
        made("B stretch for the warm-up", ["WARM_UP"]),
        made("C stretch for the cool-down", ["COOL_DOWN"]),
    ]

    ranked_names = [
        item.name for item in most_relevant(exercises, use=None, muscle=None)
    ]

    assert ranked_names == [
        "B stretch for the warm-up", "C stretch for the cool-down", "A stretch no section uses",
    ]  # fmt: skip


def test_formiqs_own_main_exercises_come_before_the_imported_ones_outside_a_warm_up():
    """Every imported exercise has a pattern now, so the pattern no longer tells Formiq's own,
    which it wrote and described, from them: the source does."""
    own = made("Z own press", ["MAIN_WORKOUT"], pattern=MovementPattern.HORIZONTAL_PUSH)
    imported = made(
        "A imported press", ["MAIN_WORKOUT"], source="FREE_EXERCISE_DB",
        pattern=MovementPattern.HORIZONTAL_PUSH,
    )  # fmt: skip

    main = most_relevant([imported, own], use=WorkoutSection.MAIN_WORKOUT, muscle=None)
    anywhere = most_relevant([imported, own], use=None, muscle=None)

    assert [item.name for item in main] == ["Z own press", "A imported press"]
    assert [item.name for item in anywhere] == ["Z own press", "A imported press"]


def test_formiqs_own_activities_do_not_come_before_the_imported_ones_in_a_warm_up():
    """The imported drills and stretches rank with Formiq's own, as they did when they were
    given patterns: docs/warm-up-cool-down.md."""
    own = made("Z own drill", ["WARM_UP"], pattern=MovementPattern.MOBILITY)
    imported = made(
        "A imported drill", ["WARM_UP"], source="FREE_EXERCISE_DB", pattern=MovementPattern.MOBILITY
    )  # fmt: skip

    ranked_names = [item.name for item in most_relevant([own, imported], use=WARM_UP, muscle=None)]

    assert ranked_names == ["A imported drill", "Z own drill"]


def test_standard_lifts_come_before_plyometric_olympic_and_strongman_ones_outside_a_warm_up():
    """Jumps, skips and Olympic lifts have patterns now, and would crowd the squats and lunges out
    of the few a pattern search returns, so the standard lifts come first (docs/exercise-fields.md)."""
    def imported(name, category):
        item = made(
            name, ["MAIN_WORKOUT"], source="FREE_EXERCISE_DB", pattern=MovementPattern.SQUAT
        )
        item.category = category
        return item

    exercises = [
        imported("A box jump", "plyometrics"),
        imported("B hang clean", "olympic weightlifting"),
        imported("C stone lift", "strongman"),
        imported("D back squat", "strength"),
        imported("E powerlifting squat", "powerlifting"),
    ]

    main = most_relevant(exercises, use=WorkoutSection.MAIN_WORKOUT, muscle=None)

    assert [item.name for item in main] == [
        "D back squat", "E powerlifting squat", "A box jump", "B hang clean", "C stone lift",
    ]  # fmt: skip
    # a warm-up search is ranked on its own terms: the category of an activity says nothing
    warm_up = most_relevant(exercises, use=WARM_UP, muscle=None)
    assert [item.name for item in warm_up] == [item.name for item in exercises]
