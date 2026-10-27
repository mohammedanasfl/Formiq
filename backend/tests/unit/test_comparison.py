"""How a workout compares with a saved plan, and how long it takes
(app.tools.comparison): the one comparison the coach's tools and the API both
answer with. Pure: saved plans are stand-ins, no database."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.schemas.workout_plan import PlanSection
from app.tools.comparison import (
    Row,
    compare_workouts,
    plan_minutes,
    plan_rows,
    prescription,
    prescription_of,
    proposed_rows,
    section_minutes,
    tool_changes,
    workout_changes,
    workout_minutes,
)
from app.tools.schemas import ProposedExerciseOutput

WARM_UP = PlanSection.WARM_UP
MAIN = PlanSection.MAIN_WORKOUT
COOL_DOWN = PlanSection.COOL_DOWN
DAY = date(2026, 10, 23)


def saved(order, name, section="MAIN_WORKOUT", sets=3, reps=10, seconds=None, rest=60, weight=None):
    """An exercise of a saved plan, as the database holds it (the section as text)."""
    return SimpleNamespace(
        id=order,
        exercise_order=order,
        section=section,
        exercise_id=100 + order,
        exercise=SimpleNamespace(name=name),
        sets=sets,
        reps=None if seconds else reps,
        duration_seconds=seconds,
        rest_seconds=rest,
        weight_kg=weight,
    )


def plan(*items, name="Leg Day", day=DAY, plan_id=41):
    return SimpleNamespace(id=plan_id, name=name, scheduled_date=day, exercises=list(items))


def row(name, section=MAIN, sets=3, reps=10, seconds=None, rest=60, weight=None):
    return Row(section, name, sets, None if seconds else reps, seconds, rest, weight)


# --- what a prescription says ---


def test_a_prescription_is_given_as_numbers_and_as_one_line():
    result = prescription_of(row("Goblet Squat", weight=20.0))

    assert result.model_dump() == {
        "sets": 3,
        "reps": 10,
        "duration_seconds": None,
        "rest_seconds": 60,
        # a saved plan's weight is a number a client can compare, not text
        "weight_kg": 20.0,
        "summary": "3 sets of 10 reps at 20 kg, 60 s rest",
    }
    assert isinstance(result.weight_kg, float)
    assert prescription_of(row("Walk", WARM_UP, sets=1, seconds=180, rest=None)).summary == (
        "1 set of 180 s"
    )
    assert prescription(row("Plank", seconds=30, rest=0)) == "3 sets of 30 s"


# --- the comparison ---


def test_the_same_workout_is_identical_and_lists_what_both_have():
    result = compare_workouts(
        [row("Push-Up"), row("Bird Dog", rest=45)],
        "Leg Day",
        DAY,
        plan(saved(1, "Push-Up"), saved(2, "Bird Dog", rest=45)),
    )

    assert result.identical is True
    assert (result.added, result.removed, result.changed) == ([], [], [])
    assert result.unchanged == ["Push-Up", "Bird Dog"]
    assert (result.name_changed, result.scheduled_date_changed) == (False, False)
    assert (result.compared_with_plan_id, result.compared_with_plan_name) == (41, "Leg Day")
    assert result.compared_with_scheduled_date == DAY


def test_dropping_a_saved_weight_is_a_change_a_proposal_sets_none():
    # the saved plan lifts 20 kg; the proposal prescribes the same sets, reps and rest and no weight
    result = compare_workouts(
        [row("Goblet Squat")], "Leg Day", DAY, plan(saved(1, "Goblet Squat", weight=20.0))
    )

    assert result.identical is False
    (change,) = result.changed
    assert (change.section, change.exercise_name) == (MAIN, "Goblet Squat")
    assert change.before.weight_kg == 20.0
    assert change.after.weight_kg is None
    assert (change.before.sets, change.before.reps, change.before.rest_seconds) == (3, 10, 60)
    assert (change.after.sets, change.after.reps, change.after.rest_seconds) == (3, 10, 60)
    assert change.before.summary == "3 sets of 10 reps at 20 kg, 60 s rest"
    assert change.after.summary == "3 sets of 10 reps, 60 s rest"


@pytest.mark.parametrize(
    ("after", "numbers"),
    [
        (row("Push-Up", sets=4), (4, 10, None, 60)),
        (row("Push-Up", reps=12), (3, 12, None, 60)),
        (row("Push-Up", rest=90), (3, 10, None, 90)),
        (row("Push-Up", seconds=40, rest=60), (3, None, 40, 60)),
    ],
    ids=["sets", "reps", "rest", "timed"],
)
def test_an_exercise_prescribed_differently_is_changed(after, numbers):
    result = compare_workouts([after], "Leg Day", DAY, plan(saved(1, "Push-Up")))

    (change,) = result.changed
    assert (
        change.after.sets,
        change.after.reps,
        change.after.duration_seconds,
        change.after.rest_seconds,
    ) == numbers
    assert (change.before.sets, change.before.reps, change.before.rest_seconds) == (3, 10, 60)
    assert (result.added, result.removed, result.unchanged) == ([], [], [])


def test_exercises_are_matched_by_section_and_name_not_by_spelling():
    result = compare_workouts(
        [
            row("Pushups"),
            row("Brisk Walk", WARM_UP, sets=1, seconds=180, rest=None),
            row("Brisk Walk", COOL_DOWN, sets=1, seconds=180, rest=None),
        ],
        "Leg Day",
        DAY,
        plan(
            saved(1, "Push-Up"),
            saved(2, "Brisk Walk", "WARM_UP", sets=1, seconds=180, rest=None),
        ),
    )

    # "Pushups" is the saved "Push-Up"; the walk in the cool-down is not the one in the warm-up
    assert result.unchanged == ["Pushups", "Brisk Walk"]
    assert [(item.section, item.exercise_name) for item in result.added] == [
        (COOL_DOWN, "Brisk Walk")
    ]
    assert result.removed == []


def test_what_only_one_workout_has_is_added_or_removed_by_section():
    result = compare_workouts(
        [row("Push-Up"), row("Side Plank", seconds=30, rest=45)],
        "Leg Day",
        DAY,
        plan(saved(1, "Push-Up"), saved(2, "Bicycle Crunch", sets=2, reps=15, rest=30)),
    )

    (added,) = result.added
    assert (added.section, added.exercise_name, added.before) == (MAIN, "Side Plank", None)
    assert added.after.summary == "3 sets of 30 s, 45 s rest"
    (removed,) = result.removed
    assert (removed.exercise_name, removed.after) == ("Bicycle Crunch", None)
    assert removed.before.summary == "2 sets of 15 reps, 30 s rest"
    assert result.identical is False


def test_a_repeated_exercise_is_matched_one_to_one():
    result = compare_workouts(
        [row("Plank", seconds=30), row("Plank", seconds=30)],
        "Leg Day",
        DAY,
        plan(saved(1, "Plank", seconds=30)),
    )

    assert result.unchanged == ["Plank"]
    assert [item.exercise_name for item in result.added] == ["Plank"]


def test_the_name_and_the_day_are_compared_and_the_plans_day_is_given():
    result = compare_workouts(
        [row("Push-Up")], "Chest Day", date(2026, 10, 24), plan(saved(1, "Push-Up"))
    )

    assert (result.name_changed, result.scheduled_date_changed) == (True, True)
    assert result.identical is True  # the exercises are the same: name and day are apart
    assert result.compared_with_scheduled_date == DAY
    assert compare_workouts([row("Push-Up")], "Leg Day", None, plan(saved(1, "Push-Up"), day=None)
                            ).scheduled_date_changed is False


def test_a_saved_exercise_the_catalog_no_longer_names_is_still_compared():
    gone = saved(1, "x")
    gone.exercise = None

    assert plan_rows(plan(gone))[0].name == "exercise 101"


def test_the_coachs_tools_tell_the_same_comparison_as_lines():
    changes = compare_workouts(
        [row("Goblet Squat"), row("Side Plank", seconds=30)],
        "Leg Day",
        DAY,
        plan(saved(1, "Goblet Squat", weight=20.0), saved(2, "Bicycle Crunch")),
    )

    told = tool_changes(changes)

    assert told.model_dump(mode="json") == {
        "compared_with_plan_id": 41,
        "compared_with_plan_name": "Leg Day",
        "added": [
            {
                "section": "MAIN_WORKOUT",
                "exercise_name": "Side Plank",
                "before": None,
                "after": "3 sets of 30 s, 60 s rest",
            }
        ],
        "removed": [
            {
                "section": "MAIN_WORKOUT",
                "exercise_name": "Bicycle Crunch",
                "before": "3 sets of 10 reps, 60 s rest",
                "after": None,
            }
        ],
        "changed": [
            {
                "section": "MAIN_WORKOUT",
                "exercise_name": "Goblet Squat",
                "before": "3 sets of 10 reps at 20 kg, 60 s rest",
                "after": "3 sets of 10 reps, 60 s rest",
            }
        ],
        "unchanged": [],
        "name_changed": False,
        "scheduled_date_changed": False,
        "identical": False,
    }
    # and the function the tools call is that, not a second comparison
    assert workout_changes(
        [row("Goblet Squat"), row("Side Plank", seconds=30)],
        "Leg Day",
        DAY,
        plan(saved(1, "Goblet Squat", weight=20.0), saved(2, "Bicycle Crunch")),
    ) == told


def test_a_proposals_rows_set_no_weight():
    shown = [
        ProposedExerciseOutput(
            exercise_order=1, section=MAIN, exercise_id=7, exercise_name="Push-Up", equipment=[],
            sets=3, reps=10, duration_seconds=None, rest_seconds=60, notes="Slow",
        )
    ]  # fmt: skip

    assert proposed_rows(shown) == [Row(MAIN, "Push-Up", 3, 10, None, 60, None)]


# --- how long a workout takes ---


def test_a_saved_plan_takes_what_the_same_workout_proposed_would():
    items = [
        saved(1, "Brisk Walk", "WARM_UP", sets=1, seconds=180, rest=None),
        # 3 sets of 45 s and 60 s of rest
        saved(2, "Push-Up"),
        saved(3, "Brisk Walk", "COOL_DOWN", sets=1, seconds=180, rest=None),
    ]
    proposed = [
        ProposedExerciseOutput(
            exercise_order=item.exercise_order, section=PlanSection(item.section),
            exercise_id=item.exercise_id, exercise_name=item.exercise.name, equipment=[],
            sets=item.sets, reps=item.reps, duration_seconds=item.duration_seconds,
            rest_seconds=item.rest_seconds, notes=None,
        )
        for item in items
    ]  # fmt: skip

    assert workout_minutes(plan_rows(plan(*items))) == {WARM_UP: 3, MAIN: 6, COOL_DOWN: 3}
    assert plan_minutes(plan(*items)) == 12 == sum(workout_minutes(proposed).values())


def test_each_section_is_rounded_up_on_its_own():
    # two sections of 61 s each: 2 + 2 minutes, not 3 for 122 s
    items = [
        saved(1, "Walk", "WARM_UP", sets=1, seconds=61, rest=None),
        saved(2, "Walk", "COOL_DOWN", sets=1, seconds=61, rest=None),
    ]

    assert plan_minutes(plan(*items)) == 4


def test_a_main_exercise_without_a_rest_gets_the_default_and_an_activity_none():
    main = saved(1, "Push-Up", rest=None)
    walk = saved(2, "Walk", "WARM_UP", sets=1, seconds=60, rest=None)

    # 3 sets of 45 s and the default 90 s of rest: 405 s
    assert section_minutes(plan_rows(plan(main))) == 7
    assert section_minutes(plan_rows(plan(walk))) == 1
