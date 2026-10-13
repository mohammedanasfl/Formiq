"""Helpers for the tests that import the pinned free-exercise-db dataset into
the test database's catalog (the imported_catalog and imported_session
fixtures, in conftest.py)."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.free_exercise_db import (
    SOURCE,
    SOURCE_VERSION,
    parse_records,
)
from app.models import Exercise
from app.repositories.exercise_repository import LOAD_MUSCLES_AND_EQUIPMENT
from app.services.exercise_import_service import ExerciseImportService, ImportSummary

# images present: both of one exercise, and only the second of another
PRESENT_IMAGES = ("3_4_Sit-Up/0.jpg", "3_4_Sit-Up/1.jpg", "Air_Bike/1.jpg")


@dataclass
class ImportedCatalog:
    connection: object
    records: list
    summary: ImportSummary
    images_dir: object
    # Formiq's own exercises before the import, as snapshot() has them
    formiq_before: dict


def snapshot(session: Session, source: str) -> dict:
    """Every exercise of the source, by name, with what the import could change."""
    exercises = session.scalars(
        select(Exercise).options(*LOAD_MUSCLES_AND_EQUIPMENT).where(Exercise.source == source)
    )
    found = {}
    for exercise in exercises:
        found[exercise.name] = {
            "id": exercise.id,
            "description": exercise.description,
            "difficulty": exercise.difficulty,
            "movement_pattern": exercise.movement_pattern,
            "uses": list(exercise.uses),
            "image_paths": list(exercise.image_paths),
            "source_id": exercise.source_id,
            "source_record": exercise.source_record,
            "muscles": {link.muscle_group_id: link.role for link in exercise.muscles},
            "equipment": [item.id for item in exercise.equipment],
            "is_active": exercise.is_active,
        }
    return found


def run_import(session: Session, records: list, images_dir, *, dry_run: bool = False):
    return ExerciseImportService(session).import_source(
        parse_records(records),
        source=SOURCE,
        version=SOURCE_VERSION,
        discovered=len(records),
        images_dir=images_dir,
        dry_run=dry_run,
    )
