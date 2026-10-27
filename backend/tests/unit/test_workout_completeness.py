"""Formiq's rules for a complete workout (app.tools.completeness), and the
duration estimate they rest on: pure functions, tested without a database.

The exercises are stand-ins with a catalog exercise's name and muscles.
"""

from types import SimpleNamespace

import pytest

from app.schemas.coach import BodyRegion, SessionFocus
from app.schemas.workout_plan import PlanSection
from app.tools.completeness import (
    FOCUS_RULES,
    REGION_ACCESSORIES,
    REGION_MUSCLES,
    assess,
    countable,
    covered_by,
    is_beginner,
    is_short,
    minimum_minutes,
    minimum_warm_up_minutes,
    name_key,
    regions_of,
    required_exercises,
    trainable,
)
from app.tools.comparison import section_minutes
from app.tools.schemas import ProposedExerciseOutput

LOWER = BodyRegion.LOWER_BODY
PUSH = BodyRegion.UPPER_PUSH
PULL = BodyRegion.UPPER_PULL
CORE = BodyRegion.CORE


def muscle(name, role="PRIMARY"):
    return SimpleNamespace(muscle_group=SimpleNamespace(name=name), role=role)


def stand_in(name, *primary, secondary=()):
    return SimpleNamespace(
        name=name,
        muscles=[muscle(item) for item in primary]
        + [muscle(item, "SECONDARY") for item in secondary],
    )


# as the catalog has them: primary muscles first
SQUAT = stand_in("Bodyweight Squat", "Glutes", "Quadriceps", secondary=["Core", "Hamstrings"])
LUNGE = stand_in("Walking Lunge", "Glutes", "Quadriceps", secondary=["Hamstrings", "Calves"])
BRIDGE = stand_in("Glute Bridge", "Glutes", secondary=["Core", "Hamstrings"])
PUSH_UP = stand_in("Push-Up", "Chest", secondary=["Front Deltoid", "Triceps", "Core"])
PRESS = stand_in("Dumbbell Shoulder Press", "Shoulders", secondary=["Triceps"])
ROW = stand_in("Resistance Band Row", "Upper Back", secondary=["Lats", "Biceps"])
BIRD_DOG = stand_in("Bird Dog", "Core", secondary=["Lower Back", "Glutes"])
NECK = stand_in("Neck Flexion", "Neck")


def main(*exercises, sets=3):
    return [(exercise, sets) for exercise in exercises]


# --- regions ---


def test_every_catalog_muscle_but_the_neck_is_in_one_region():
    catalog = {
        "Abductors", "Adductors", "Biceps", "Calves", "Chest", "Core", "Forearms",
        "Front Deltoid", "Glutes", "Hamstrings", "Lats", "Lower Back", "Neck", "Obliques",
        "Quadriceps", "Rear Deltoid", "Shoulders", "Triceps", "Upper Back",
    }  # fmt: skip
    placed = [
        name
        for regions in (REGION_MUSCLES, REGION_ACCESSORIES)
        for muscles in regions.values()
        for name in muscles
    ]

    assert len(placed) == len(set(placed))
    assert set(placed) == catalog - {"Neck"}


@pytest.mark.parametrize(
    ("exercise", "regions"),
    [
        # by the primary muscles only: a squat's core and hamstrings only assist
        (SQUAT, {LOWER}),
        (PUSH_UP, {PUSH}),
        (ROW, {PULL}),
        (BIRD_DOG, {CORE}),
        # a compound lift trains every region of its primary muscles
        (stand_in("Clean and Press", "Quadriceps", "Shoulders"), {LOWER, PUSH}),
        # never by a secondary muscle, even with no primary one
        (stand_in("Odd One", secondary=["Biceps"]), set()),
        (NECK, set()),
        (stand_in("Unlisted"), set()),
    ],
)
def test_an_exercise_trains_the_regions_of_its_primary_muscles(exercise, regions):
    assert regions_of(exercise) == regions


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        ("Push-Up", "Pushups", True),
        ("Push-Up", "push up", True),
        ("Bodyweight Squat", "Bodyweight Squats", True),
        ("Push-Up", "Push-Up Wide", False),
        ("Incline Push-Up", "Push-Up", False),
        ("Bodyweight Squat", "Goblet Squat", False),
    ],
)
def test_exercises_of_the_same_name_are_one(first, second, same):
    assert (name_key(first) == name_key(second)) is same


# A grip carry, curls, a pushdown and calf raises: each belongs to a region by
# its primary muscle, an accessory of it, but covers none
CARRY = stand_in("Farmer's Carry", "Forearms", secondary=["Upper Back", "Core"])
CURL = stand_in("Dumbbell Biceps Curl", "Biceps", secondary=["Forearms"])
PUSHDOWN = stand_in("Cable Triceps Pushdown", "Triceps")
CALF_RAISE = stand_in("Standing Calf Raise", "Calves")


@pytest.mark.parametrize(
    ("exercise", "belongs", "covers"),
    [
        (CARRY, {PULL}, set()),
        (CURL, {PULL}, set()),
        (PUSHDOWN, {PUSH}, set()),
        (CALF_RAISE, {LOWER}, set()),
        (stand_in("Hip Adduction", "Adductors"), {LOWER}, set()),
        # a main mover covers its region
        (ROW, {PULL}, {PULL}),
        (stand_in("Pullups", "Lats", secondary=["Biceps", "Upper Back"]), {PULL}, {PULL}),
        (stand_in("Reverse Flyes", "Rear Deltoid"), {PULL}, {PULL}),
        (PRESS, {PUSH}, {PUSH}),
        (stand_in("Romanian Deadlift", "Glutes", "Hamstrings", secondary=["Lower Back"]),
         {LOWER}, {LOWER}),
        (stand_in("Hyperextensions", "Lower Back"), {CORE}, {CORE}),
        # a secondary main mover never covers: push-ups work the core too
        (PUSH_UP, {PUSH}, {PUSH}),
        (stand_in("Dips", "Triceps", secondary=["Chest", "Shoulders"]), {PUSH}, set()),
    ],
)  # fmt: skip
def test_only_a_primary_main_mover_covers_a_region(exercise, belongs, covers):
    assert regions_of(exercise) == belongs
    assert covered_by(exercise) == covers


def test_accessory_exercises_never_complete_a_full_body_workout():
    # a carry and curls are no pull, calf raises no lower body
    accessories = assess(
        SessionFocus.FULL_BODY, main(CALF_RAISE, PUSH_UP, CARRY, CURL, BIRD_DOG), None
    )
    # they still count as exercises, and belong in an upper-body workout
    arms = assess(SessionFocus.UPPER_BODY, main(PUSH_UP, ROW, CURL, PUSHDOWN), None)

    assert accessories.missing == {LOWER, PULL}
    assert accessories.trained == {PUSH, CORE}
    assert accessories.counted == 5
    assert accessories.off_focus == []
    assert (arms.missing, arms.counted, arms.off_focus) == (set(), 4, [])


def test_an_accessory_outside_the_focus_does_not_belong_in_it():
    push = assess(SessionFocus.PUSH, main(PUSH_UP, PRESS, PUSHDOWN, CURL), None)

    assert push.off_focus == [CURL]
    assert push.counted == 3


def test_what_the_pool_covers_is_what_its_main_movers_train():
    assert not trainable([CARRY, CURL, PUSH_UP], PULL)
    assert trainable([CARRY, ROW], PULL)
    assert countable([CARRY, CURL, PUSH_UP], SessionFocus.PULL) == 2


# --- how many main exercises a focus needs ---


@pytest.mark.parametrize(
    ("focus", "max_minutes", "required"),
    [
        (SessionFocus.FULL_BODY, None, 4),
        (SessionFocus.FULL_BODY, 60, 5),
        (SessionFocus.FULL_BODY, 30, 4),
        (SessionFocus.FULL_BODY, 29, 2),
        (SessionFocus.FULL_BODY, 10, 2),
        (SessionFocus.UPPER_BODY, None, 3),
        # a longer session needs more exercises (required_exercises), from 34 minutes
        (SessionFocus.UPPER_BODY, 33, 3),
        (SessionFocus.UPPER_BODY, 34, 4),
        (SessionFocus.LOWER_BODY, 45, 5),
        (SessionFocus.PUSH, None, 3),
        (SessionFocus.PULL, None, 3),
        # an abs workout of three is a list of suggestions: four, as a full body
        (SessionFocus.CORE, None, 4),
        (SessionFocus.CORE, 20, 2),
        (SessionFocus.CORE, 60, 5),
    ],
)
def test_the_minimum_depends_on_the_focus_and_a_short_session(focus, max_minutes, required):
    assert required_exercises(focus, max_minutes) == required
    assert is_short(max_minutes) is (max_minutes is not None and max_minutes < 30)


def test_a_full_body_workout_of_three_exercises_is_short_of_its_focus():
    # the proposal the dev database kept: squat, bird dog and lunge, called full body
    assessment = assess(SessionFocus.FULL_BODY, main(SQUAT, BIRD_DOG, LUNGE), None)

    assert assessment.trained == {LOWER, CORE}
    assert assessment.missing == {PUSH, PULL}
    assert (assessment.counted, assessment.required) == (3, 4)
    assert assessment.off_focus == []


def test_a_complete_full_body_workout():
    assessment = assess(SessionFocus.FULL_BODY, main(SQUAT, PUSH_UP, ROW, BIRD_DOG), None)

    assert assessment.trained == set(BodyRegion)
    assert assessment.missing == set()
    assert (assessment.counted, assessment.required) == (4, 4)


def test_a_short_session_needs_fewer_exercises_never_less_coverage():
    two = assess(SessionFocus.FULL_BODY, main(SQUAT, PUSH_UP), 20)
    three = assess(SessionFocus.FULL_BODY, main(SQUAT, PUSH_UP, ROW), 20)

    # two exercises are enough in 20 minutes, but not without a pull
    assert (two.counted, two.required) == (2, 2)
    assert two.missing == {PULL}
    assert (three.counted, three.missing) == (3, set())


def test_a_focused_workout_is_judged_by_its_own_focus():
    legs = assess(SessionFocus.LOWER_BODY, main(SQUAT, LUNGE, BRIDGE), None)
    upper = assess(SessionFocus.UPPER_BODY, main(PUSH_UP, PRESS, ROW), None)
    push_only = assess(SessionFocus.UPPER_BODY, main(PUSH_UP, PRESS, PUSH_UP), None)

    # no push or pull needed for legs, and no legs for the upper body
    assert (legs.missing, legs.counted, legs.required) == (set(), 3, 3)
    assert (upper.missing, upper.counted) == (set(), 3)
    assert push_only.missing == {PULL}


def test_an_exercise_outside_the_focus_does_not_belong_in_it():
    assessment = assess(SessionFocus.LOWER_BODY, main(SQUAT, LUNGE, BRIDGE, PUSH_UP), None)
    full_body = assess(SessionFocus.FULL_BODY, main(SQUAT, PUSH_UP, ROW, NECK), None)

    assert assessment.off_focus == [PUSH_UP]
    assert assessment.trained == {LOWER}
    # in a full-body workout, only an exercise of no region at all
    assert full_body.off_focus == [NECK]
    assert full_body.counted == 3


def test_a_core_exercise_goes_with_any_focus_but_counts_only_for_full_body_or_core():
    legs = assess(SessionFocus.LOWER_BODY, main(SQUAT, LUNGE, BIRD_DOG), None)
    full_body = assess(SessionFocus.FULL_BODY, main(SQUAT, PUSH_UP, ROW, BIRD_DOG), None)
    core = assess(SessionFocus.CORE, main(BIRD_DOG), None)

    assert legs.off_focus == []
    assert (legs.trained, legs.counted) == ({LOWER, CORE}, 2)
    assert full_body.counted == 4
    assert core.counted == 1


def test_repeats_and_single_sets_do_not_count():
    pushups = stand_in("Pushups", "Chest")
    padded = assess(SessionFocus.FULL_BODY, main(SQUAT, PUSH_UP, pushups, ROW) + [(LUNGE, 1)], None)

    # Push-Up and Pushups are one exercise, and one set of lunges is not enough
    assert (padded.counted, padded.required) == (3, 4)


def test_what_a_catalog_pool_offers():
    pool = [SQUAT, LUNGE, PUSH_UP, stand_in("Pushups", "Chest"), BIRD_DOG]

    assert trainable(pool, PUSH)
    assert not trainable(pool, PULL)
    assert countable(pool, SessionFocus.FULL_BODY) == 4
    assert countable(pool, SessionFocus.UPPER_BODY) == 1
    assert countable(pool, SessionFocus.PULL) == 0


@pytest.mark.parametrize("focus", list(SessionFocus))
def test_every_focus_has_a_rule_that_needs_its_own_regions(focus):
    rule = FOCUS_RULES[focus]

    assert rule.required <= rule.counted <= rule.allowed
    assert CORE in rule.allowed


# --- duration and experience ---


@pytest.mark.parametrize(
    ("max_minutes", "least"),
    [(None, 0), (10, 5), (25, 13), (30, 15), (60, 30), (90, 45), (180, 45)],
)
def test_a_workout_uses_at_least_half_the_time_the_user_has(max_minutes, least):
    assert minimum_minutes(max_minutes) == least


@pytest.mark.parametrize(("max_minutes", "least"), [(None, 3), (45, 3), (30, 3), (29, 0)])
def test_the_warm_up_is_at_least_three_minutes_unless_the_session_is_short(max_minutes, least):
    assert minimum_warm_up_minutes(max_minutes) == least


@pytest.mark.parametrize(
    ("experience", "beginner"),
    [
        ("beginner", True),
        ("BEGINNER", True),
        ("Complete beginner", True),
        ("intermediate", False),
        ("ADVANCED", False),
        (None, False),
    ],
)
def test_a_beginner_is_told_by_the_profiles_experience(experience, beginner):
    assert is_beginner(experience) is beginner


def item(section, sets, reps=None, duration=None, rest=None):
    return ProposedExerciseOutput(
        exercise_order=1,
        section=section,
        exercise_id=1,
        exercise_name="Test",
        equipment=[],
        sets=sets,
        reps=reps,
        duration_seconds=duration,
        rest_seconds=rest,
        notes=None,
    )


MAIN = PlanSection.MAIN_WORKOUT
WARM_UP = PlanSection.WARM_UP


@pytest.mark.parametrize(
    ("items", "minutes"),
    [
        # 3 sets of 45 s and 60 s of rest: 315 s, rounded up
        ([item(MAIN, 3, reps=10, rest=60)], 6),
        # 15 reps still take 45 s; 20 take 60 s at 3 s a rep
        ([item(MAIN, 3, reps=15, rest=60)], 6),
        ([item(MAIN, 3, reps=20, rest=60)], 6),
        ([item(MAIN, 3, reps=30, rest=60)], 8),
        # no rest given: 90 s, the default, for a main exercise
        ([item(MAIN, 3, reps=10)], 7),
        # a rest of 0 is no rest
        ([item(MAIN, 4, reps=10, rest=0)], 3),
        # a timed set lasts its duration; a warm-up activity has no rest
        ([item(WARM_UP, 1, duration=180)], 3),
        ([item(WARM_UP, 2, reps=10)], 2),
        # sets add up before rounding
        ([item(WARM_UP, 1, duration=150), item(WARM_UP, 1, reps=8)], 4),
        ([], 0),
    ],
)
def test_the_duration_estimate_counts_sets_reps_and_rest(items, minutes):
    assert section_minutes(items) == minutes
