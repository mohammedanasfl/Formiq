"""Importing the pinned exercises-dataset into the catalog
(app.services.exercise_import_service), on the test database, on top of the catalog the
development database is expected to hold (Formiq's seeds and free-exercise-db): what it
adds, skips and rejects, that what is stored is the record's English text and Formiq's
mapping and nothing made up, that no image is registered, that the other sources are left
exactly as they were, that running it again changes nothing, and that an update keeps the
exercise's id and a user's plan.

Every import runs in a transaction that is rolled back (the imported_catalog fixture, in
conftest.py), so the test database keeps only the seeds, and requires the local PostgreSQL
container to be running. The tests that need a catalog of the seeds alone are in
test_exercises_dataset_seeds_only.py: this module's transaction stays open for its whole
run, and exercises.name is unique, so a second connection could not insert the same names.
"""

import copy
import re
from collections import Counter
from dataclasses import dataclass

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import cli
from app.catalog import exercises_dataset as ed
from app.models import Exercise, User, WorkoutPlan, WorkoutPlanExercise
from app.repositories.exercise_repository import LOAD_MUSCLES_AND_EQUIPMENT
from app.schemas import ExerciseResponse
from app.services.exercise_import_service import comparable_name
from tests.integration.exercises_dataset_helpers import (
    SOURCE,
    dataset_exercise,
    run_dataset_import,
    table_counts,
)
from tests.integration.imported_catalog import snapshot

OTHER_SOURCES = ("FORMIQ", "FREE_EXERCISE_DB")


@pytest.fixture(scope="module")
def dataset_records():
    """The pinned file's records: refused if it is not the pinned file (its SHA-256)."""
    return ed.load_records()


@pytest.fixture(scope="module")
def no_images(tmp_path_factory):
    """An images directory with nothing in it: the dataset has no image to register."""
    return tmp_path_factory.mktemp("no-exercise-images")


@dataclass
class DatasetImport:
    summary: object
    # Formiq's own and free-exercise-db's exercises just before the import, as snapshot() has them
    others_before: dict


@pytest.fixture(scope="module")
def dataset_import(imported_catalog, dataset_records, no_images):
    """The catalog as the development one is expected to be, Formiq's seeds and
    free-exercise-db, with exercises-dataset imported on top of it, once per test
    module, inside the imported_catalog fixture's transaction (rolled back after
    the module)."""
    with Session(
        bind=imported_catalog.connection, join_transaction_mode="create_savepoint"
    ) as session:
        others_before = {source: snapshot(session, source) for source in OTHER_SOURCES}
        summary = run_dataset_import(session, dataset_records, no_images)
    return DatasetImport(summary, others_before)


# --- on the catalog the development database is expected to hold (seeds + free-exercise-db) ---


def test_the_import_reports_what_it_did(dataset_import, dataset_records):
    summary = dataset_import.summary

    assert (summary.source, summary.version, summary.dry_run) == (SOURCE, ed.SOURCE_VERSION, False)
    assert summary.discovered == 1324
    assert (len(summary.imported), summary.updated, summary.unchanged) == (647, [], [])
    # the 731 the mapper accepts: 647 new, 84 whose name the catalog already has
    assert len(summary.skipped) == 84
    owners = Counter(reason.split(" exercise ")[0] for _, reason in summary.skipped)
    assert owners == {
        "the catalog already has Formiq's own": 7,
        "the catalog already has another": 77,
    }
    assert len(summary.rejected) == 593
    assert cli.rejected_by_reason(summary.rejected) == [
        f"    by reason: {ed.AMBIGUOUS_EQUIPMENT}: 495",
        f"    by reason: {ed.DUPLICATE_NAME}: 2",
        f"    by reason: {ed.UNMAPPED_PRIMARY_MUSCLE}: 53",
        f"    by reason: {ed.UNUSABLE_EQUIPMENT_VALUE}: 51",
    ]
    # nothing the catalog lacked, no field the mapper does not know
    assert "catalog" not in summary.unresolved
    assert summary.unknown_fields == []
    # the warnings of the records that were accepted (imported or skipped)
    accepted = ed.parse_records(dataset_records).exercises
    assert len(summary.incomplete) == sum(len(item.warnings) for item in accepted)
    # no image is registered or looked for
    assert (summary.images_registered, summary.images_missing) == (0, 0)
    assert summary.not_in_source == []


def test_what_is_stored_is_the_records_english_text_and_the_mapping_only(
    dataset_import, imported_session, dataset_records
):
    records = {record["id"]: record for record in dataset_records}
    parsed = {item.source_id: item for item in ed.parse_records(dataset_records).exercises}
    stored = imported_session.scalars(
        select(Exercise).options(*LOAD_MUSCLES_AND_EQUIPMENT).where(Exercise.source == SOURCE)
    ).all()

    assert len(stored) == 647
    assert {exercise.source_id for exercise in stored} == set(dataset_import.summary.imported)
    for exercise in stored:
        item, record = parsed[exercise.source_id], records[exercise.source_id]
        assert (exercise.name, exercise.source_version) == (item.name, ed.SOURCE_VERSION)
        # the provenance: the record as the file has it, with only the English instructions
        assert exercise.source_record == ed.english_record(record)
        assert set(exercise.source_record["instruction_steps"]) == {"en"}
        assert set(exercise.source_record["instructions"]) == {"en"}
        assert exercise.instructions == record["instruction_steps"]["en"] != []
        # nothing is guessed: no level, no pattern, no section, no description, no image
        assert exercise.difficulty == "UNRATED"
        assert exercise.movement_pattern is None
        assert exercise.description is None
        assert exercise.uses == []
        assert exercise.image_paths == []
        assert exercise.category is None
        assert exercise.is_active is True
        # the muscles and equipment the explicit tables give, the primary muscle first
        assert {link.muscle_group.name: str(link.role) for link in exercise.muscles} == {
            name: str(role) for name, role in item.muscles.items()
        }
        assert sorted(equipment.name for equipment in exercise.equipment) == sorted(item.equipment)
        assert "в°" not in exercise.name
        # a valid catalog entry: the API's enums accept the new source and UNRATED
        response = ExerciseResponse.model_validate(exercise)
        assert (response.source, response.difficulty, response.images) == (SOURCE, "UNRATED", [])


def test_no_image_is_registered(dataset_import, imported_session):
    registered = imported_session.scalar(
        select(func.count())
        .select_from(Exercise)
        .where(Exercise.source == SOURCE, func.cardinality(Exercise.image_paths) > 0)
    )

    assert registered == 0
    assert dataset_import.summary.images_registered == 0


def test_the_other_sources_are_left_exactly_as_they_were(dataset_import, imported_session):
    for source in OTHER_SOURCES:
        assert snapshot(imported_session, source) == dataset_import.others_before[source]


def test_a_name_the_catalog_has_is_skipped_never_merged(
    dataset_import, imported_session, dataset_records
):
    parsed = {item.source_id: item for item in ed.parse_records(dataset_records).exercises}
    names = [comparable_name(name) for name in imported_session.scalars(select(Exercise.name))]

    # a name is in the catalog once
    assert len(names) == len(set(names))
    assert len(dataset_import.summary.skipped) == 84
    for source_id, reason in dataset_import.summary.skipped:
        existing_id = int(re.search(r"\(id (\d+)\)", reason).group(1))
        existing = imported_session.get(Exercise, existing_id)
        # the exercise the catalog already had: of another source, with the same name
        assert existing.source in OTHER_SOURCES
        assert comparable_name(existing.name) == comparable_name(parsed[source_id].name)
        # and no exercise of the new source took its place
        assert not imported_session.scalars(
            select(Exercise).where(Exercise.source == SOURCE, Exercise.source_id == source_id)
        ).all()


def test_an_external_id_belongs_to_its_source(
    dataset_import, imported_session, dataset_records, no_images
):
    source_id = dataset_import.summary.imported[0]
    imported = dataset_exercise(imported_session, source_id)
    # another source's exercise whose id looks the same
    other = Exercise(
        name="Test Exercise With The Same Id",
        difficulty="BEGINNER",
        source="FREE_EXERCISE_DB",
        source_id=source_id,
    )
    imported_session.add(other)
    imported_session.flush()
    before = snapshot(imported_session, SOURCE)

    summary = run_dataset_import(imported_session, dataset_records, no_images)

    # the new source's exercise is still the one matched, and the other source's is not touched
    assert (summary.imported, summary.updated) == ([], [])
    assert source_id in summary.unchanged
    imported_session.expire_all()
    assert dataset_exercise(imported_session, source_id).id == imported.id
    assert snapshot(imported_session, SOURCE) == before
    assert (other.source, other.name) == ("FREE_EXERCISE_DB", "Test Exercise With The Same Id")
    # the database too refuses the same id twice within one source
    with pytest.raises(IntegrityError):
        with imported_session.begin_nested():
            imported_session.add(
                Exercise(
                    name="Test Second Exercise With The Same Id",
                    difficulty="UNRATED",
                    source=SOURCE,
                    source_id=source_id,
                )
            )
            imported_session.flush()


def test_running_it_again_changes_nothing(
    dataset_import, imported_session, dataset_records, no_images
):
    ids = {(e.source, e.source_id): e.id for e in imported_session.scalars(select(Exercise))}
    before = {source: snapshot(imported_session, source) for source in (*OTHER_SOURCES, SOURCE)}
    counts = table_counts(imported_session)

    summary = run_dataset_import(imported_session, dataset_records, no_images)

    assert (summary.imported, summary.updated) == ([], [])
    assert len(summary.unchanged) == 647
    assert len(summary.skipped) == 84
    assert len(summary.rejected) == 593
    imported_session.expire_all()
    after_ids = {(e.source, e.source_id): e.id for e in imported_session.scalars(select(Exercise))}
    assert after_ids == ids
    assert {
        source: snapshot(imported_session, source) for source in (*OTHER_SOURCES, SOURCE)
    } == before
    assert table_counts(imported_session) == counts


@pytest.fixture
def plan_with_imported_exercise(dataset_import, imported_session):
    """A user's plan that uses an exercise of the new source."""
    user = User(email="dataset-import-plan@example.com")
    imported_session.add(user)
    imported_session.flush()
    exercise = dataset_exercise(imported_session, dataset_import.summary.imported[0])
    plan = WorkoutPlan(
        user_id=user.id,
        name="Dataset",
        status="DRAFT",
        exercises=[
            WorkoutPlanExercise(exercise_id=exercise.id, exercise_order=1, sets=3, reps=10)
        ],
    )
    imported_session.add(plan)
    imported_session.flush()
    return plan, exercise.id, exercise.source_id


def test_a_changed_record_is_updated_in_place_and_a_plan_that_uses_it_is_untouched(
    imported_session, dataset_records, no_images, plan_with_imported_exercise
):
    plan, exercise_id, source_id = plan_with_imported_exercise
    records = copy.deepcopy(dataset_records)
    changed = next(record for record in records if record["id"] == source_id)
    changed["instruction_steps"]["en"] = [*changed["instruction_steps"]["en"], "A step added."]
    plan_rows = [(i.exercise_id, i.sets, i.reps) for i in plan.exercises]

    summary = run_dataset_import(imported_session, records, no_images)

    assert summary.updated == [source_id]
    assert (summary.imported, len(summary.unchanged)) == ([], 646)
    imported_session.expire_all()
    exercise = dataset_exercise(imported_session, source_id)
    # the same exercise, so the plan that uses it still does
    assert exercise.id == exercise_id
    assert exercise.instructions[-1] == "A step added."
    assert exercise.source_record == ed.english_record(changed)
    assert exercise.difficulty == "UNRATED"
    stored_plan = imported_session.get(WorkoutPlan, plan.id)
    assert [(i.exercise_id, i.sets, i.reps) for i in stored_plan.exercises] == plan_rows


def test_a_record_no_longer_in_the_source_is_reported_and_kept(
    dataset_import, imported_session, dataset_records, no_images
):
    source_id = dataset_import.summary.imported[0]
    records = [record for record in dataset_records if record["id"] != source_id]

    summary = run_dataset_import(imported_session, records, no_images)

    assert summary.not_in_source == [source_id]
    assert dataset_exercise(imported_session, source_id).is_active
