"""The catalog covers what the coach needs to build a whole workout, once the
pinned free-exercise-db dataset is imported (the imported_catalog fixture, in conftest.py):
main exercises, warm-up and cool-down activities by Formiq's classification
(each exercise's uses), for the major muscle groups and with little or no
equipment. It also records the gaps that remain.

They import into a transaction that is rolled back, never commit, and require
the local PostgreSQL container to be running.
"""

from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.ai import ToolCall
from app.catalog import classification, descriptions
from app.models import Equipment, Exercise, User, WorkoutPlan, WorkoutPlanExercise
from app.repositories.exercise_repository import LOAD_MUSCLES_AND_EQUIPMENT
from app.schemas import ExerciseFilters, ExerciseResponse, WorkoutPlanResponse
from app.services import (
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.tools import FormiqTools

MAJOR_MUSCLE_GROUPS = (
    "Chest",
    "Upper Back",
    "Lats",
    "Shoulders",
    "Biceps",
    "Triceps",
    "Core",
    "Glutes",
    "Quadriceps",
    "Hamstrings",
    "Calves",
)


@pytest.fixture
def catalog(imported_session):
    """The active exercises, with their muscles and equipment."""
    return imported_session.scalars(
        select(Exercise).options(*LOAD_MUSCLES_AND_EQUIPMENT).where(Exercise.is_active)
    ).all()


def used_for(catalog, section):
    return [exercise for exercise in catalog if section in exercise.uses]


def muscles(exercise, role=None):
    return {link.muscle_group.name for link in exercise.muscles if role in (None, link.role)}


def is_cardio(exercise):
    return exercise.movement_pattern == "CARDIO"


def test_each_section_has_the_measured_coverage(catalog):
    counts = {
        section: (
            len(used_for(catalog, section)),
            sum(e.source == "FORMIQ" for e in used_for(catalog, section)),
            sum(not e.equipment for e in used_for(catalog, section)),
        )
        for section in ("WARM_UP", "MAIN_WORKOUT", "COOL_DOWN")
    }

    # (in all, Formiq's own, needing no equipment). Before the 13 duplicate activities were
    # hidden and 21 activities added, the warm-up was (38, 16, 26) and the cool-down
    # (69, 17, 51); the main workout has not changed.
    assert counts == {
        "WARM_UP": (48, 30, 36),
        "MAIN_WORKOUT": (747, 27, 90),
        "COOL_DOWN": (65, 24, 49),
    }


def test_warm_up_and_cool_down_activities_are_light_and_say_what_they_work(catalog):
    for exercise in used_for(catalog, "WARM_UP") + used_for(catalog, "COOL_DOWN"):
        assert exercise.difficulty == "BEGINNER", exercise.name
        assert muscles(exercise, "PRIMARY"), exercise.name


def test_anyone_can_warm_up_and_cool_down_without_equipment(catalog):
    # easy cardio suits any workout, and needs nothing
    for section in ("WARM_UP", "COOL_DOWN"):
        assert {e.name for e in used_for(catalog, section) if is_cardio(e) and not e.equipment} >= {
            "Brisk Walk",
            "Marching in Place",
        }


@pytest.mark.parametrize("muscle_group", MAJOR_MUSCLE_GROUPS)
def test_every_major_muscle_group_has_main_exercises_and_a_stretch(catalog, muscle_group):
    assert [e for e in used_for(catalog, "MAIN_WORKOUT") if muscle_group in muscles(e, "PRIMARY")]
    stretches = [
        e.name
        for e in used_for(catalog, "COOL_DOWN")
        if not is_cardio(e) and muscle_group in muscles(e)
    ]
    assert len(stretches) >= 2, stretches


# Warm-up drills (not easy cardio, which suits any workout) that work each major muscle group
# as a main muscle, at least: the coach warms a workout up with drills that work what its main
# exercises train. The triceps had none, the biceps and the chest one or none as a main muscle.
WARM_UP_DRILLS_AS_A_MAIN_MUSCLE = {
    "Chest": 2,
    "Upper Back": 2,
    "Lats": 2,
    "Shoulders": 2,
    "Biceps": 1,
    "Triceps": 2,
    "Core": 4,
    "Glutes": 2,
    "Quadriceps": 2,
    "Hamstrings": 2,
    "Calves": 2,
}
# the major muscle groups with no warm-up drill that needs no equipment: the biceps drill needs a
# light band, and nothing else that needs none works the biceps at all
NO_EQUIPMENT_WARM_UP_GAPS = {"Biceps"}


def drills_for(catalog, muscle_group, role=None):
    return [
        e
        for e in used_for(catalog, "WARM_UP")
        if not is_cardio(e) and muscle_group in muscles(e, role)
    ]


def test_the_measured_floors_cover_every_major_muscle_group():
    assert set(WARM_UP_DRILLS_AS_A_MAIN_MUSCLE) == set(MAJOR_MUSCLE_GROUPS)


@pytest.mark.parametrize(("muscle_group", "floor"), WARM_UP_DRILLS_AS_A_MAIN_MUSCLE.items())
def test_every_major_muscle_group_has_warm_up_drills_that_work_it_as_a_main_muscle(
    catalog, muscle_group, floor
):
    drills = [e.name for e in drills_for(catalog, muscle_group, "PRIMARY")]

    assert len(drills) >= floor, drills


@pytest.mark.parametrize("muscle_group", MAJOR_MUSCLE_GROUPS)
def test_every_major_muscle_group_has_two_warm_up_drills_that_work_it(catalog, muscle_group):
    assert len(drills_for(catalog, muscle_group)) >= 2


@pytest.mark.parametrize("muscle_group", MAJOR_MUSCLE_GROUPS)
def test_every_major_muscle_group_but_the_known_gap_has_a_warm_up_drill_without_equipment(
    catalog, muscle_group
):
    drills = [e.name for e in drills_for(catalog, muscle_group) if not e.equipment]

    assert bool(drills) is (muscle_group not in NO_EQUIPMENT_WARM_UP_GAPS), drills


@pytest.mark.parametrize("muscle_group", MAJOR_MUSCLE_GROUPS)
def test_every_major_muscle_group_has_two_stretches_that_work_it_as_a_main_muscle(
    catalog, muscle_group
):
    stretches = [
        e.name
        for e in used_for(catalog, "COOL_DOWN")
        if not is_cardio(e) and muscle_group in muscles(e, "PRIMARY")
    ]

    assert len(stretches) >= 2, stretches


def test_a_gentle_cool_down_walk_needs_nothing(catalog):
    walk = next(e for e in catalog if e.name == "Easy Walk")

    # a cool-down only: the warm-up has the brisk walk
    assert (walk.uses, walk.movement_pattern, walk.equipment) == (["COOL_DOWN"], "CARDIO", [])


@pytest.mark.parametrize(
    ("muscle_group", "count"),
    [
        ("Chest", 14),
        ("Core", 38),
        ("Quadriceps", 15),
        ("Glutes", 9),
        ("Triceps", 5),
        ("Shoulders", 2),
        ("Hamstrings", 2),
        # gaps: pulling and arm work need something to pull or lift (a pull-up
        # needs a bar, though its record says "body only")
        ("Lats", 0),
        ("Upper Back", 0),
        ("Biceps", 0),
    ],
)
def test_main_exercises_that_need_no_equipment(catalog, muscle_group, count):
    found = [
        e
        for e in used_for(catalog, "MAIN_WORKOUT")
        if not e.equipment and muscle_group in muscles(e, "PRIMARY")
    ]

    assert len(found) == count


@pytest.mark.parametrize(
    ("pattern", "allowed"),
    [
        ("SQUAT", set()),
        ("HINGE", set()),
        ("LUNGE", set()),
        ("HORIZONTAL_PUSH", set()),
        ("VERTICAL_PUSH", set()),
        ("ROTATION", set()),
        # pulling needs something to pull: a band is the least
        ("HORIZONTAL_PULL", {"Resistance Band"}),
    ],
)
def test_formiqs_main_patterns_can_be_trained_with_little_or_no_equipment(
    catalog, pattern, allowed
):
    assert [
        exercise.name
        for exercise in used_for(catalog, "MAIN_WORKOUT")
        if exercise.movement_pattern == pattern
        and {item.name for item in exercise.equipment} <= allowed
    ]


def test_every_piece_of_equipment_has_an_exercise(imported_session, catalog):
    used = {item.name for exercise in catalog for item in exercise.equipment}

    assert set(imported_session.scalars(select(Equipment.name).where(Equipment.is_active))) == used


# --- Formiq's corrections of the imported records ---


def by_source_id(catalog):
    return {exercise.source_id: exercise for exercise in catalog if exercise.source_id}


@pytest.mark.parametrize(
    ("source_id", "equipment"),
    [
        ("Pullups", {"Pull-up Bar"}),
        ("Chin-Up", {"Pull-up Bar"}),
        ("V-Bar_Pullup", {"Pull-up Bar", "Other Equipment"}),
        ("Wide-Grip_Rear_Pull-Up", {"Pull-up Bar"}),
        ("Hanging_Leg_Raise", {"Pull-up Bar"}),
        ("Bench_Dips", {"Bench"}),
        ("Dips_-_Triceps_Version", {"Other Equipment"}),
        ("Body_Tricep_Press", {"Barbell", "Squat Rack"}),
    ],
)
def test_an_exercise_its_record_calls_body_only_needs_its_equipment(
    catalog, source_id, equipment
):
    exercise = by_source_id(catalog)[source_id]

    assert {item.name for item in exercise.equipment} == equipment
    # the upstream record is kept as it was
    assert exercise.source_record["equipment"] == "body only"
    assert exercise.uses == ["MAIN_WORKOUT"]


@pytest.mark.parametrize(
    ("source_id", "formiqs"),
    [
        ("Bodyweight_Walking_Lunge", "Walking Lunge"),
        ("Pushups", "Push-Up"),
        ("Seated_Cable_Rows", "Seated Cable Row"),
        ("Standing_Cable_Wood_Chop", "Cable Woodchop"),
        ("Triceps_Pushdown", "Cable Triceps Pushdown"),
    ],
)
def test_an_imported_copy_of_formiqs_own_exercise_suits_no_section(catalog, source_id, formiqs):
    copy = by_source_id(catalog)[source_id]
    own = next(exercise for exercise in catalog if exercise.name == formiqs)

    # never in a workout beside Formiq's own; still readable by id
    assert copy.uses == []
    assert copy.is_active
    assert "MAIN_WORKOUT" in own.uses
    assert {item.name for item in copy.equipment} == {item.name for item in own.equipment}


# --- the duplicates of a warm-up or cool-down activity, and the movement patterns ---


def test_a_duplicate_activity_suits_no_section_but_stays_in_the_catalog_readable_by_id(
    imported_session, catalog
):
    imported = by_source_id(catalog)
    service = ExerciseCatalogService(imported_session)

    assert len(classification.ACTIVITY_DUPLICATES) == 13
    for source_id, kept in classification.ACTIVITY_DUPLICATES.items():
        duplicate = imported[source_id]
        twin = next(exercise for exercise in catalog if exercise.name == kept)
        # never in a workout beside the one kept; not deleted, not deactivated
        assert duplicate.uses == [], source_id
        assert duplicate.is_active, source_id
        assert twin.uses and twin.id != duplicate.id, source_id
        # the exercise a saved plan names is still the same one
        assert service.get_exercise_by_id(duplicate.id) is duplicate
        assert ExerciseResponse.model_validate(duplicate).uses == []
        # the record is kept as it was
        assert duplicate.source_record["id"] == source_id


def test_no_section_offers_a_duplicate_activity(imported_session, catalog):
    """What the catalog lists for a section is what the coach chooses from."""
    service = ExerciseCatalogService(imported_session)
    imported = by_source_id(catalog)
    hidden = {imported[source_id].id for source_id in classification.ACTIVITY_DUPLICATES}
    offered = {
        section: {e.id for e in service.list_exercises(ExerciseFilters(use=section))}
        for section in ("WARM_UP", "MAIN_WORKOUT", "COOL_DOWN")
    }

    assert all(offered.values())
    assert not hidden & set().union(*offered.values())
    # and the exercises kept in their place are offered
    for kept in ("Hip Circles", "Standing Calf Stretch", "Brisk Walk", "Easy Stationary Cycling"):
        exercise = next(e for e in catalog if e.name == kept)
        assert any(exercise.id in ids for ids in offered.values()), kept


def test_every_imported_activity_that_suits_a_section_has_a_movement_pattern(catalog):
    activities = [
        exercise
        for exercise in catalog
        if exercise.source == "FREE_EXERCISE_DB"
        and {"WARM_UP", "COOL_DOWN"} & set(exercise.uses)
    ]

    assert len(activities) == 18 + 41 - 4
    assert all(exercise.movement_pattern for exercise in activities)
    patterns = {exercise.movement_pattern for exercise in activities}
    assert patterns == {"CARDIO", "MOBILITY", "STRETCH"}


def test_52_imported_activities_were_given_a_mobility_or_stretch_pattern(catalog):
    imported = by_source_id(catalog)
    # the activities the lists name (more records are given these patterns by hand, as the
    # records no section uses: tests/unit/test_movement_patterns.py)
    listed = classification.WARM_UP_DRILLS | classification.COOL_DOWN_STRETCHES
    patterned = [
        exercise
        for exercise in catalog
        if exercise.source == "FREE_EXERCISE_DB"
        and exercise.source_id in listed
        and exercise.movement_pattern in ("MOBILITY", "STRETCH")
    ]
    drills = {
        e.movement_pattern for e in patterned if e.source_id in classification.WARM_UP_DRILLS
    }
    hidden = [
        imported[source_id]
        for source_id in classification.ACTIVITY_DUPLICATES
        if imported[source_id].source_record["category"] == "stretching"
    ]

    # 63 drills and stretches were in the catalog without one; the 11 that are hidden duplicates
    # stay without, so that a search by pattern (which has no section to leave them out by)
    # never offers what cannot be proposed
    assert len(patterned) == 63 - 11
    assert all(exercise.uses for exercise in patterned)
    assert drills == {"MOBILITY"}
    assert len(hidden) == 11
    assert all(exercise.movement_pattern is None for exercise in hidden)


def test_the_easy_cardio_records_the_dataset_describes_by_machine_have_formiqs_description(catalog):
    imported = by_source_id(catalog)

    for source_id, text in descriptions.DESCRIPTIONS.items():
        exercise = imported[source_id]
        assert exercise.description == text, source_id
        assert "Suggested dose" in exercise.description
        # the description replaces the record's steps (a machine's menu and its calorie
        # estimate); the record keeps them, unchanged
        assert exercise.instructions == []
        assert exercise.source_record["instructions"]
        assert exercise.source_record["id"] == source_id
    # every other imported exercise has a generated summary instead (tests/unit/
    # test_generated_descriptions.py), and keeps its record's steps
    written = {
        e.source_id
        for e in catalog
        if e.source == "FREE_EXERCISE_DB"
        and e.description
        and e.description == descriptions.DESCRIPTIONS.get(e.source_id)
    }
    assert written == set(descriptions.DESCRIPTIONS)


def test_a_saved_plan_that_holds_a_hidden_duplicate_still_reads_it(imported_session, catalog):
    """A plan saved while the duplicate was a warm-up or cool-down option: it keeps the
    exercise it named, in its section."""
    imported = by_source_id(catalog)
    walk = imported["Walking_Treadmill"]
    stretch = imported["Cat_Stretch"]
    user = User(email="hidden-duplicate@example.com")
    imported_session.add(user)
    imported_session.flush()
    plan = WorkoutPlan(
        user_id=user.id,
        name="Saved before the duplicates were hidden",
        status="PLANNED",
        exercises=[
            WorkoutPlanExercise(
                exercise_id=walk.id, exercise_order=1, section="WARM_UP", sets=1, reps=1
            ),
            WorkoutPlanExercise(
                exercise_id=stretch.id, exercise_order=2, section="COOL_DOWN", sets=1, reps=1
            ),
        ],
    )
    imported_session.add(plan)
    imported_session.flush()
    imported_session.expire_all()

    stored = WorkoutPlanService(imported_session).get_plan(user.id, plan.id)
    response = WorkoutPlanResponse.model_validate(stored)

    read = [(item.exercise_id, item.section, item.exercise.name) for item in response.exercises]
    assert read == [
        (walk.id, "WARM_UP", "Walking, Treadmill"),
        (stretch.id, "COOL_DOWN", "Cat Stretch"),
    ]
    # what the catalog says about them is still there: the hidden stretch keeps its record's
    # steps, and the hidden cardio record shows Formiq's description, never the machine's menu
    # and calorie estimate (the live QA of 2026-10-19 found them on the cardio records)
    shown = {item.exercise.name: item.exercise for item in response.exercises}
    assert shown["Cat Stretch"].instructions
    assert shown["Walking, Treadmill"].instructions == []
    assert "Suggested dose" in shown["Walking, Treadmill"].description
    assert "calorie" not in shown["Walking, Treadmill"].model_dump_json().lower()


def test_a_search_for_no_equipment_finds_nothing_that_needs_some(imported_session):
    """What the coach finds for a user without equipment: no pull-up, dip or
    hanging exercise, and so no pulling exercise at all; with a pull-up bar,
    the pull-ups."""
    tools = FormiqTools(
        users=UserService(imported_session),
        profiles=UserProfileService(imported_session),
        plans=WorkoutPlanService(imported_session),
        sessions=WorkoutSessionService(imported_session),
        catalog=ExerciseCatalogService(imported_session),
        end_read=Mock(),
    )

    def search(**arguments):
        (result,) = tools.run([ToolCall(name="search_exercises", arguments=arguments)], user_id=1)
        return result["output"]

    corrected = {"Pullups", "Chin-Up", "V-Bar Pullup", "Bench Dips", "Dips - Triceps Version"}
    for muscle in ("Lats", "Upper Back", "Triceps", "Chest", "Core"):
        found = search(use="MAIN_WORKOUT", muscle=muscle, available_equipment=[])
        names = {item["name"] for item in found["exercises"]}
        assert all(item["equipment"] == [] for item in found["exercises"]), muscle
        assert not names & (corrected | {"Pushups", "Bodyweight Walking Lunge"}), muscle
    for muscle in ("Lats", "Upper Back"):
        assert search(use="MAIN_WORKOUT", muscle=muscle, available_equipment=[])[
            "total_matches"
        ] == 0
    with_a_bar = search(use="MAIN_WORKOUT", muscle="Lats", available_equipment=["Pull-up Bar"])
    assert {"Pullups", "Chin-Up"} <= {item["name"] for item in with_a_bar["exercises"]}


# --- the audit of the exercise fields (docs/exercise-fields.md) ---


def audit(catalog):
    """The exercises of the three kinds the audit tells apart: Formiq's own, the imported ones
    the catalog shows, and the hidden duplicates."""
    own = [e for e in catalog if e.source == "FORMIQ"]
    imported = [e for e in catalog if e.source == "FREE_EXERCISE_DB"]
    hidden = [e for e in imported if e.source_id in classification.HIDDEN_DUPLICATE_IDS]
    shown = [e for e in imported if e.source_id not in classification.HIDDEN_DUPLICATE_IDS]
    return own, shown, hidden


def test_formiqs_own_exercises_have_every_field(catalog):
    own, _, _ = audit(catalog)

    assert len(own) == 71
    for exercise in own:
        assert (exercise.description or "").strip(), exercise.name
        assert exercise.movement_pattern, exercise.name
        assert exercise.uses, exercise.name
        assert exercise.difficulty, exercise.name
        assert any(link.role == "PRIMARY" for link in exercise.muscles), exercise.name


def test_every_exercise_the_catalog_shows_has_its_fields_but_the_ones_left_on_purpose(catalog):
    _, shown, _ = audit(catalog)

    assert len(shown) == 845
    # the description, the muscles and the level: every one
    for exercise in shown:
        assert (exercise.description or "").strip(), exercise.name
        assert exercise.difficulty, exercise.name
        assert any(link.role == "PRIMARY" for link in exercise.muscles), exercise.name
    # the movement pattern: all but the dozen drills, throws and holds that fit none
    no_pattern = sorted(e.source_id for e in shown if e.movement_pattern is None)
    assert len(no_pattern) == 17
    assert "Wind_Sprints" in no_pattern and "Rack_Delivery" in no_pattern
    # the sections: 70 records no section uses, on purpose (docs/exercise-fields.md)
    assert sum(not e.uses for e in shown) == 70
    # the steps: all but five records whose own record has none, three of which are
    # described by hand, and the other two say so
    no_steps = {e.source_id for e in shown if not (e.source_record or {}).get("instructions")}
    assert no_steps == {
        "Iron_Cross", "One-Arm_Kettlebell_Swings", "Push_Press", "Side_Bridge", "Side_Jackknife",
    }  # fmt: skip
    # the images are not in this audit: they are files, which a database has only when its
    # images directory holds them (the dataset's are not cleared for redistribution)


def test_the_hidden_duplicates_keep_the_fields_they_had(catalog):
    _, _, hidden = audit(catalog)

    assert len(hidden) == 18
    for exercise in hidden:
        assert exercise.uses == [], exercise.name
        # never shown by a search, so no summary: but the two whose cardio record would show a
        # calorie estimate have Formiq's text, and every cardio record is CARDIO
        assert bool(exercise.description) == (exercise.source_id in descriptions.REPLACES_STEPS)
        assert exercise.movement_pattern in (None, "CARDIO"), exercise.name
