"""Helpers for the tests that import the pinned exercises-dataset into the test
database's catalog (test_exercises_dataset_catalog.py and
test_exercises_dataset_seeds_only.py)."""

from sqlalchemy import select, text

from app.catalog import exercises_dataset as ed
from app.models import Exercise
from app.repositories.exercise_repository import LOAD_MUSCLES_AND_EQUIPMENT
from app.services.exercise_import_service import ExerciseImportService

SOURCE = "EXERCISES_DATASET"


def run_dataset_import(session, records, images_dir, *, dry_run=False):
    return ExerciseImportService(session).import_source(
        ed.parse_records(records),
        source=ed.SOURCE,
        version=ed.SOURCE_VERSION,
        discovered=len(records),
        images_dir=images_dir,
        dry_run=dry_run,
    )


def dataset_exercise(session, source_id):
    return session.scalars(
        select(Exercise)
        .options(*LOAD_MUSCLES_AND_EQUIPMENT)
        .where(Exercise.source == SOURCE, Exercise.source_id == source_id)
    ).one()


def table_counts(session):
    return {
        table: session.scalar(text(f"select count(*) from {table}"))
        for table in ("exercises", "exercise_muscles", "exercise_equipment")
    }
