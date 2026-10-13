"""Importing the pinned free-exercise-db dataset into the catalog
(app.services.exercise_import_service), on the test database: what it adds,
skips and reports, that every source field is kept, that running it again
changes nothing, that an update keeps the exercise's id and never touches a
user's data, and that a dry run changes nothing.

The import runs in a transaction that is rolled back
(the imported_catalog fixture, in conftest.py), and requires the local PostgreSQL
container to be running.
"""

import copy

import pytest
from sqlalchemy import func, select

from app.catalog import free_exercise_db
from app.catalog.free_exercise_db import SOURCE_VERSION
from app.models import Exercise, ExerciseMuscle, User, WorkoutPlan, WorkoutPlanExercise
from app.repositories.exercise_repository import LOAD_MUSCLES_AND_EQUIPMENT
from app.schemas import ExerciseResponse
from app.services.exercise_import_service import comparable_name
from tests.integration.imported_catalog import run_import, snapshot

# the upstream records whose exercise Formiq already has, by another spelling or the same
SAME_AS_FORMIQS = {
    "Arm_Circles": "Arm Circles",
    "Band_Pull_Apart": "Band Pull-Apart",
    "Bodyweight_Squat": "Bodyweight Squat",
    "Childs_Pose": "Child's Pose",
    "Dumbbell_Bench_Press": "Dumbbell Bench Press",
    "Dumbbell_Shoulder_Press": "Dumbbell Shoulder Press",
    "Goblet_Squat": "Goblet Squat",
    "Inchworm": "Inchworm",
    "Leg_Press": "Leg Press",
    "One-Arm_Dumbbell_Row": "One-Arm Dumbbell Row",
    "Romanian_Deadlift": "Romanian Deadlift",
    "Smith_Machine_Squat": "Smith Machine Squat",
    "Worlds_Greatest_Stretch": "World's Greatest Stretch",
}


def imported_exercise(session, source_id):
    return session.scalars(
        select(Exercise)
        .options(*LOAD_MUSCLES_AND_EQUIPMENT)
        .where(Exercise.source == "FREE_EXERCISE_DB", Exercise.source_id == source_id)
    ).one()


def exercise_count(session):
    return session.scalar(select(func.count()).select_from(Exercise))


def test_the_import_reports_what_it_did(imported_catalog):
    summary = imported_catalog.summary

    assert (summary.source, summary.version, summary.dry_run) == (
        "FREE_EXERCISE_DB",
        SOURCE_VERSION,
        False,
    )
    assert summary.discovered == 876
    assert (len(summary.imported), summary.updated, summary.unchanged) == (863, [], [])
    assert {source_id for source_id, _ in summary.skipped} == set(SAME_AS_FORMIQS)
    assert summary.rejected == []
    assert (summary.unresolved, summary.unknown_fields) == ({}, [])
    assert len(summary.incomplete) == 10
    # three of the listed images are in the images directory
    assert (summary.images_registered, summary.images_missing) == (3, 1717)
    assert summary.not_in_source == []
    assert summary.uses == {"WARM_UP": 22, "MAIN_WORKOUT": 725, "COOL_DOWN": 52}


def test_an_exercise_formiq_already_has_is_skipped_never_duplicated(
    imported_catalog, imported_session
):
    reasons = dict(imported_catalog.summary.skipped)

    for source_id, formiq_name in SAME_AS_FORMIQS.items():
        assert (
            f"the catalog already has Formiq's own exercise {formiq_name!r}" in reasons[source_id]
        )
    names = [comparable_name(name) for name in imported_session.scalars(select(Exercise.name))]
    assert len(names) == len(set(names))


def test_formiqs_own_exercises_are_left_as_they_were(imported_catalog, imported_session):
    assert snapshot(imported_session, "FORMIQ") == imported_catalog.formiq_before


def test_every_source_field_is_kept_and_the_ids_are_kept_apart(imported_catalog, imported_session):
    records = {record["id"]: record for record in imported_catalog.records}
    imported = imported_session.scalars(
        select(Exercise)
        .options(*LOAD_MUSCLES_AND_EQUIPMENT)
        .where(Exercise.source == "FREE_EXERCISE_DB")
    ).all()

    assert len(imported) == 863
    for exercise in imported:
        record = records[exercise.source_id]
        # the record itself, every field as it was: re-importable from the database
        assert exercise.source_record == record
        assert exercise.source_version == SOURCE_VERSION
        # the steps and images in their upstream order
        assert exercise.instructions == record["instructions"]
        assert exercise.category == record["category"]
        assert exercise.name == record["name"]
        # Formiq's id is its own; the upstream id is kept apart
        assert isinstance(exercise.id, int)
        assert exercise.source_id == record["id"] != str(exercise.id)
        assert exercise.description is None
        # the muscles and equipment the record names, in Formiq's catalog
        assert {link.muscle_group.name for link in exercise.muscles} == {
            free_exercise_db.MUSCLES[name]
            for name in record["primaryMuscles"] + record["secondaryMuscles"]
        }
        mapped = (
            free_exercise_db.EQUIPMENT.get(record["equipment"]) if record["equipment"] else None
        )
        assert [item.name for item in exercise.equipment] == ([mapped] if mapped else [])
        # a valid catalog entry
        ExerciseResponse.model_validate(exercise)


def test_images_are_registered_in_order_only_when_their_file_exists(imported_session):
    assert imported_exercise(imported_session, "3_4_Sit-Up").image_paths == [
        "3_4_Sit-Up/0.jpg",
        "3_4_Sit-Up/1.jpg",
    ]
    # its first image is not there: only the second is registered
    assert imported_exercise(imported_session, "Air_Bike").image_paths == ["Air_Bike/1.jpg"]
    # the record still lists both
    assert imported_exercise(imported_session, "Air_Bike").source_record["images"] == [
        "Air_Bike/0.jpg",
        "Air_Bike/1.jpg",
    ]
    with_images = imported_session.scalars(
        select(Exercise.source_id).where(func.cardinality(Exercise.image_paths) > 0)
    ).all()
    assert sorted(with_images) == ["3_4_Sit-Up", "Air_Bike"]


def test_running_it_again_changes_nothing(imported_catalog, imported_session):
    ids = {e.source_id: e.id for e in imported_session.scalars(select(Exercise))}
    before = snapshot(imported_session, "FREE_EXERCISE_DB")

    summary = run_import(imported_session, imported_catalog.records, imported_catalog.images_dir)

    assert (summary.imported, summary.updated) == ([], [])
    assert len(summary.unchanged) == 863
    assert len(summary.skipped) == 13
    assert {e.source_id: e.id for e in imported_session.scalars(select(Exercise))} == ids
    assert snapshot(imported_session, "FREE_EXERCISE_DB") == before


@pytest.fixture
def plan_with_imported_exercise(imported_session):
    """A user's plan that uses an imported exercise."""
    user = User(email="import-plan@example.com")
    imported_session.add(user)
    imported_session.flush()
    curl = imported_exercise(imported_session, "Alternate_Incline_Dumbbell_Curl")
    plan = WorkoutPlan(
        user_id=user.id,
        name="Arms",
        status="DRAFT",
        exercises=[WorkoutPlanExercise(exercise_id=curl.id, exercise_order=1, sets=3, reps=10)],
    )
    imported_session.add(plan)
    imported_session.flush()
    return plan, curl.id


def changed_records(records):
    """The records with one exercise changed upstream: its level, muscles and steps."""
    records = copy.deepcopy(records)
    curl = next(r for r in records if r["id"] == "Alternate_Incline_Dumbbell_Curl")
    curl["level"] = "intermediate"
    curl["secondaryMuscles"] = ["forearms", "shoulders"]
    curl["instructions"] = [*curl["instructions"], "A step added upstream."]
    return records


def test_a_changed_record_is_updated_in_place_and_user_data_is_untouched(
    imported_catalog, imported_session, plan_with_imported_exercise
):
    plan, curl_id = plan_with_imported_exercise
    records = changed_records(imported_catalog.records)
    plan_rows = [(i.exercise_id, i.sets, i.reps) for i in plan.exercises]

    summary = run_import(imported_session, records, imported_catalog.images_dir)

    assert summary.updated == ["Alternate_Incline_Dumbbell_Curl"]
    assert (len(summary.imported), len(summary.unchanged)) == (0, 862)
    imported_session.expire_all()
    curl = imported_exercise(imported_session, "Alternate_Incline_Dumbbell_Curl")
    # the same exercise, so the plan that uses it still does
    assert curl.id == curl_id
    assert (curl.difficulty, curl.instructions[-1]) == ("INTERMEDIATE", "A step added upstream.")
    assert {link.muscle_group.name: link.role for link in curl.muscles} == {
        "Biceps": "PRIMARY",
        "Forearms": "SECONDARY",
        "Shoulders": "SECONDARY",
    }
    assert curl.source_record == next(
        r for r in records if r["id"] == "Alternate_Incline_Dumbbell_Curl"
    )
    stored_plan = imported_session.get(WorkoutPlan, plan.id)
    assert [(i.exercise_id, i.sets, i.reps) for i in stored_plan.exercises] == plan_rows


def test_a_dry_run_reports_the_change_and_makes_none(imported_catalog, imported_session):
    before = snapshot(imported_session, "FREE_EXERCISE_DB")
    links = imported_session.scalar(select(func.count()).select_from(ExerciseMuscle))

    summary = run_import(
        imported_session,
        changed_records(imported_catalog.records),
        imported_catalog.images_dir,
        dry_run=True,
    )

    assert summary.dry_run is True
    assert summary.updated == ["Alternate_Incline_Dumbbell_Curl"]
    imported_session.expire_all()
    assert snapshot(imported_session, "FREE_EXERCISE_DB") == before
    assert imported_session.scalar(select(func.count()).select_from(ExerciseMuscle)) == links


def test_a_dry_run_of_the_first_import_adds_nothing(imported_catalog, imported_session):
    # every imported exercise gone, as before the first import
    imported_session.execute(
        Exercise.__table__.delete().where(Exercise.source == "FREE_EXERCISE_DB")
    )
    imported_session.commit()
    count = exercise_count(imported_session)

    summary = run_import(
        imported_session, imported_catalog.records, imported_catalog.images_dir, dry_run=True
    )

    assert len(summary.imported) == 863
    assert exercise_count(imported_session) == count


def test_a_record_no_longer_in_the_source_is_reported_and_kept(imported_catalog, imported_session):
    records = [r for r in imported_catalog.records if r["id"] != "Air_Bike"]

    summary = run_import(imported_session, records, imported_catalog.images_dir)

    assert summary.not_in_source == ["Air_Bike"]
    assert imported_exercise(imported_session, "Air_Bike").is_active


def test_a_mapping_the_catalog_lacks_is_rejected_and_reported(
    imported_catalog, imported_session, monkeypatch
):
    # Formiq maps "neck" to a muscle group the catalog does not have
    monkeypatch.setitem(free_exercise_db.MUSCLES, "neck", "Test Missing Neck")
    neck = [r for r in imported_catalog.records if "neck" in r["primaryMuscles"]]
    before = snapshot(imported_session, "FREE_EXERCISE_DB")

    summary = run_import(imported_session, neck, imported_catalog.images_dir)

    assert len(summary.rejected) == len(neck) > 0
    assert all(
        reason == "Formiq's catalog has no muscle group 'Test Missing Neck'"
        for _, reason in summary.rejected
    )
    assert summary.unresolved == {"catalog": ["muscle group 'Test Missing Neck'"]}
    # rejected, so left as they were: nothing dropped from them
    imported_session.expire_all()
    assert snapshot(imported_session, "FREE_EXERCISE_DB") == before
