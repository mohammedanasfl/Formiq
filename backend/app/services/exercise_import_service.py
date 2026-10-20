"""Imports an upstream exercise dataset into the catalog
(python -m app.cli import-exercises).

The import is idempotent. An upstream record is matched by its source and
source id, never by name: it is added once, updated when its record or
Formiq's mapping of it changed, and left alone otherwise, so running it again
changes nothing. It writes only the imported exercises and their muscle and
equipment links: Formiq's own exercises, and every user's plans, sessions and
history, are never changed. An imported exercise keeps its Formiq id, so the
plans and sessions that use it still do.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.catalog.free_exercise_db import ParsedSource
from app.catalog.images import resolve_image
from app.models import Exercise, ExerciseMuscle
from app.repositories import EquipmentRepository, ExerciseRepository, MuscleGroupRepository
from app.schemas.exercise import ExerciseSource, WorkoutSection


def comparable_name(name: str) -> str:
    """The name without case, spaces or punctuation: "Band Pull Apart" and
    "Band Pull-Apart" are the same exercise."""
    return re.sub(r"[^0-9a-z]", "", name.casefold())


@dataclass
class ImportSummary:
    source: str
    version: str
    dry_run: bool
    discovered: int
    # source ids
    imported: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    # (source id, why)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    # values without a Formiq mapping, by field
    unresolved: dict[str, list[str]] = field(default_factory=dict)
    # upstream fields Formiq does not know, kept in the records
    unknown_fields: list[str] = field(default_factory=list)
    # (source id, what is missing) for valid but incomplete records
    incomplete: list[tuple[str, str]] = field(default_factory=list)
    images_registered: int = 0
    # image paths the records list whose file is not in the images directory
    images_missing: int = 0
    # imported earlier, but no longer in the source; left as they are
    not_in_source: list[str] = field(default_factory=list)
    # the catalog's exercises from this source, by section they suit
    uses: dict[str, int] = field(default_factory=dict)


class ExerciseImportService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.exercises = ExerciseRepository(session)
        self.muscle_groups = MuscleGroupRepository(session)
        self.equipment = EquipmentRepository(session)

    def import_source(
        self,
        parsed: ParsedSource,
        *,
        source: ExerciseSource,
        version: str,
        discovered: int,
        images_dir: Path,
        dry_run: bool,
    ) -> ImportSummary:
        """Applies the parsed records, in one transaction: committed, or rolled
        back for a dry run (or on any error), so a dry run reports exactly
        what the import would do and changes nothing."""
        summary = ImportSummary(
            source=source,
            version=version,
            dry_run=dry_run,
            discovered=discovered,
            unresolved={name: sorted(values) for name, values in sorted(parsed.unresolved.items())},
            unknown_fields=sorted(parsed.unknown_fields),
        )
        summary.rejected = [
            (record.source_id or f"record {record.index}", "; ".join(record.reasons))
            for record in parsed.rejected
        ]
        try:
            self._apply(parsed, source, version, images_dir, summary)
            if dry_run:
                self.session.rollback()
            else:
                self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return summary

    def _apply(
        self,
        parsed: ParsedSource,
        source: ExerciseSource,
        version: str,
        images_dir: Path,
        summary: ImportSummary,
    ) -> None:
        muscle_groups = {group.name: group.id for group in self.muscle_groups.find()}
        equipment = {item.name: item for item in self.equipment.find()}
        catalog = self.exercises.find_all()
        imported = {e.source_id: e for e in catalog if e.source == source}
        by_name = {comparable_name(e.name): e for e in catalog}
        in_source: set[str] = set()
        # mapping targets the catalog does not have
        absent: set[str] = set()

        for item in parsed.exercises:
            in_source.add(item.source_id)
            for warning in item.warnings:
                summary.incomplete.append((item.source_id, warning))
            missing = [
                f"muscle group {name!r}" for name in item.muscles if name not in muscle_groups
            ] + [f"equipment {name!r}" for name in item.equipment if name not in equipment]
            if missing:
                summary.rejected.append(
                    (item.source_id, f"Formiq's catalog has no {', no '.join(missing)}")
                )
                absent.update(missing)
                continue
            exercise = imported.get(item.source_id)
            same_name = by_name.get(comparable_name(item.name))
            if same_name is not None and same_name is not exercise:
                owner = "Formiq's own" if same_name.source == ExerciseSource.FORMIQ else "another"
                summary.skipped.append(
                    (
                        item.source_id,
                        (
                            f"the catalog already has {owner} exercise {same_name.name!r} "
                            f"(id {same_name.id})"
                        ),
                    )
                )
                continue

            image_paths = [p for p in item.image_paths if resolve_image(images_dir, p)]
            summary.images_registered += len(image_paths)
            summary.images_missing += len(item.image_paths) - len(image_paths)
            values = {
                "name": item.name,
                "description": item.description,
                "difficulty": item.difficulty,
                "movement_pattern": item.movement_pattern,
                "uses": [str(use) for use in item.uses],
                "image_paths": image_paths,
                "source": source,
                "source_id": item.source_id,
                "source_version": version,
                "source_record": item.record,
            }
            muscles = {muscle_groups[name]: role for name, role in item.muscles.items()}
            # in the order the exercise's links are read back
            needs = sorted((equipment[name] for name in item.equipment), key=lambda e: e.id)

            if exercise is None:
                exercise = self.exercises.create(Exercise(**values))
                self._set_links(exercise, muscles, needs)
                summary.imported.append(item.source_id)
            elif self._changed(exercise, values, muscles, needs):
                if by_name.get(comparable_name(exercise.name)) is exercise:
                    del by_name[comparable_name(exercise.name)]
                for name, value in values.items():
                    setattr(exercise, name, value)
                self._set_links(exercise, muscles, needs)
                summary.updated.append(item.source_id)
            else:
                summary.unchanged.append(item.source_id)
            by_name[comparable_name(item.name)] = exercise

        if absent:
            summary.unresolved["catalog"] = sorted(absent)
        summary.not_in_source = sorted(set(imported) - in_source)
        counts = Counter(
            use
            for exercise in self.exercises.find_all()
            if exercise.source == source
            for use in exercise.uses
        )
        summary.uses = {section: counts[section] for section in WorkoutSection}

    @staticmethod
    def _changed(exercise: Exercise, values: dict, muscles: dict, needs: list) -> bool:
        return (
            any(getattr(exercise, name) != value for name, value in values.items())
            or {link.muscle_group_id: link.role for link in exercise.muscles} != muscles
            or [item.id for item in exercise.equipment] != [item.id for item in needs]
        )

    def _set_links(self, exercise: Exercise, muscles: dict, needs: list) -> None:
        """Replaces the exercise's muscle and equipment links with these."""
        if exercise.muscles:
            # the old links are deleted before the new ones, which may have the
            # same keys, are added
            exercise.muscles.clear()
            self.session.flush()
        exercise.muscles = [
            ExerciseMuscle(muscle_group_id=group_id, role=role)
            for group_id, role in muscles.items()
        ]
        exercise.equipment = list(needs)
        self.session.flush()
