"""The free-exercise-db dataset: reading, validating and mapping its records to
Formiq's catalog. Nothing here touches the database
(app.services.exercise_import_service applies the result).

The dataset is the pinned copy in backend/data/free-exercise-db (see SOURCE.md
there): it is read from disk, never fetched. Each record is checked against
the upstream schema, and every value Formiq maps (level, category, muscles,
equipment) must have a mapping here: a record with a value that has none is
rejected and the value reported, never dropped. The record itself is kept as
it was, every field included, those Formiq does not use and any field it does
not know.
"""

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.catalog.classification import uses_of
from app.catalog.images import is_image_path
from app.schemas.exercise import (
    Difficulty,
    ExerciseSource,
    MovementPattern,
    MuscleRole,
    WorkoutSection,
)

SOURCE = ExerciseSource.FREE_EXERCISE_DB
SOURCE_URL = "https://github.com/yuhonas/free-exercise-db"
# the upstream commit the vendored file is from, and that file's SHA-256
SOURCE_VERSION = "f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5"
SOURCE_SHA256 = "5bb747e3fc658f095a60dcbf6d53c96627acdcc6ffb6fffde86f7e26995d40bf"
SOURCE_FILE = Path(__file__).resolve().parents[2] / "data" / "free-exercise-db" / "exercises.json"

# The upstream schema's fields (schema.json). force may be left out; the others
# are required, though equipment and mechanic may be null.
FIELDS = frozenset(
    {
        "id",
        "name",
        "force",
        "level",
        "mechanic",
        "equipment",
        "primaryMuscles",
        "secondaryMuscles",
        "instructions",
        "category",
        "images",
    }
)
REQUIRED_FIELDS = FIELDS - {"force"}

SOURCE_ID = re.compile(r"[0-9A-Za-z_-]{1,100}")
MAX_NAME_LENGTH = 150

LEVELS = {
    "beginner": Difficulty.BEGINNER,
    "intermediate": Difficulty.INTERMEDIATE,
    "expert": Difficulty.ADVANCED,
}
CATEGORIES = frozenset(
    {
        "strength",
        "stretching",
        "cardio",
        "powerlifting",
        "olympic weightlifting",
        "strongman",
        "plyometrics",
    }
)
# Upstream muscles to Formiq's muscle groups. Formiq's Upper Back is "the
# trapezius, rhomboids and other muscles between the shoulder blades", so both
# middle back and traps are Upper Back; the record keeps the upstream names.
MUSCLES = {
    "abdominals": "Core",
    "abductors": "Abductors",
    "adductors": "Adductors",
    "biceps": "Biceps",
    "calves": "Calves",
    "chest": "Chest",
    "forearms": "Forearms",
    "glutes": "Glutes",
    "hamstrings": "Hamstrings",
    "lats": "Lats",
    "lower back": "Lower Back",
    "middle back": "Upper Back",
    "neck": "Neck",
    "quadriceps": "Quadriceps",
    "shoulders": "Shoulders",
    "traps": "Upper Back",
    "triceps": "Triceps",
}
# Upstream equipment to Formiq's. "body only" needs none. A null equipment
# names none either, but says nothing about whether the exercise needs any
# (app.catalog.classification).
NO_EQUIPMENT = "body only"
EQUIPMENT = {
    NO_EQUIPMENT: None,
    "bands": "Resistance Band",
    "barbell": "Barbell",
    "cable": "Cable Machine",
    "dumbbell": "Dumbbell",
    "e-z curl bar": "EZ Curl Bar",
    "exercise ball": "Exercise Ball",
    "foam roll": "Foam Roller",
    "kettlebells": "Kettlebell",
    "machine": "Machine",
    "medicine ball": "Medicine Ball",
    "other": "Other Equipment",
}


class SourceFileError(ValueError):
    """The source file cannot be read as the pinned dataset."""


@dataclass(frozen=True)
class SourceExercise:
    """A valid upstream record, mapped to Formiq's catalog."""

    source_id: str
    name: str
    difficulty: Difficulty
    # CARDIO for the cardio category; Formiq has not classified the rest
    movement_pattern: MovementPattern | None
    # Formiq muscle group names and roles, primary first
    muscles: dict[str, MuscleRole]
    # Formiq equipment names; empty when the record names none
    equipment: list[str]
    uses: list[WorkoutSection]
    # the record's image paths, in order
    image_paths: list[str]
    # the record exactly as the file has it
    record: dict[str, Any]
    # what is missing from an otherwise valid record, such as instructions
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RejectedRecord:
    # its position in the file, and its id when it has a usable one
    index: int
    source_id: str | None
    reasons: list[str]


@dataclass
class ParsedSource:
    exercises: list[SourceExercise]
    rejected: list[RejectedRecord]
    # values without a Formiq mapping, by field
    unresolved: dict[str, set[str]]
    # fields the upstream schema does not have, kept in the records
    unknown_fields: set[str]


def load_records(path: Path = SOURCE_FILE, *, sha256: str = SOURCE_SHA256) -> list[Any]:
    """The records of the source file, once it is the pinned file: its checksum
    is the recorded one, and it is a JSON list."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise SourceFileError(f"cannot read {path.name}: {error.strerror}") from None
    if hashlib.sha256(data).hexdigest() != sha256:
        raise SourceFileError(
            f"{path.name} is not the pinned dataset file (its SHA-256 differs from "
            f"{SOURCE_VERSION[:12]}'s); update SOURCE.md and SOURCE_SHA256 together"
        )
    try:
        records = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceFileError(f"{path.name} is not valid JSON: {error}") from None
    if not isinstance(records, list):
        raise SourceFileError(f"{path.name} does not hold a list of records")
    return records


def parse_records(records: list[Any]) -> ParsedSource:
    """Validates and maps every record, in source id order. A record is
    rejected for a missing or malformed field, a value Formiq has no mapping
    for, or an id or name another record already has."""
    exercises: list[SourceExercise] = []
    rejected: list[RejectedRecord] = []
    unresolved: dict[str, set[str]] = defaultdict(set)
    unknown_fields: set[str] = set()
    seen_ids: set[str] = set()
    seen_names: set[str] = set()

    def order(item: tuple[int, Any]) -> tuple[str, int]:
        index, record = item
        source_id = record.get("id") if isinstance(record, dict) else None
        return (source_id if isinstance(source_id, str) else "", index)

    for index, record in sorted(enumerate(records), key=order):
        if not isinstance(record, dict):
            rejected.append(RejectedRecord(index, None, ["the record is not an object"]))
            continue
        reasons, warnings = _check(record, unresolved)
        source_id = record.get("id") if _valid_id(record.get("id")) else None
        if source_id is not None and source_id in seen_ids:
            reasons.append(f"another record has the id {source_id!r}")
        name = record["name"].strip() if isinstance(record.get("name"), str) else None
        if name and name.casefold() in seen_names:
            reasons.append(f"another record has the name {name!r}")
        if reasons:
            rejected.append(RejectedRecord(index, source_id, reasons))
            continue
        seen_ids.add(source_id)
        seen_names.add(name.casefold())
        unknown_fields |= set(record) - FIELDS
        exercises.append(_mapped(record, name, warnings))
    return ParsedSource(exercises, rejected, dict(unresolved), unknown_fields)


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and SOURCE_ID.fullmatch(value) is not None


def _is_text_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _check(record: dict[str, Any], unresolved: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    """Why the record cannot be imported (none when it can), and the warnings
    of a valid but incomplete record."""
    reasons: list[str] = []
    warnings: list[str] = []
    if missing := sorted(REQUIRED_FIELDS - set(record)):
        reasons.append(f"missing fields: {', '.join(missing)}")

    if "id" in record and not _valid_id(record["id"]):
        reasons.append("id must be 1 to 100 letters, digits, '_' or '-'")
    if "name" in record:
        name = record["name"]
        if not isinstance(name, str) or not name.strip():
            reasons.append("name must be non-blank text")
        elif len(name.strip()) > MAX_NAME_LENGTH:
            reasons.append(f"name is longer than {MAX_NAME_LENGTH} characters")
    for optional_text in ("force", "mechanic"):
        if record.get(optional_text) is not None and not isinstance(record[optional_text], str):
            reasons.append(f"{optional_text} must be text or null")

    if "level" in record:
        if not isinstance(record["level"], str):
            reasons.append("level must be text")
        elif record["level"] not in LEVELS:
            unresolved["level"].add(record["level"])
            reasons.append(f"no Formiq difficulty for level {record['level']!r}")
    if "category" in record:
        if not isinstance(record["category"], str):
            reasons.append("category must be text")
        elif record["category"] not in CATEGORIES:
            unresolved["category"].add(record["category"])
            reasons.append(f"unknown category {record['category']!r}")
    if "equipment" in record:
        equipment = record["equipment"]
        if equipment is not None and not isinstance(equipment, str):
            reasons.append("equipment must be text or null")
        elif equipment is not None and equipment not in EQUIPMENT:
            unresolved["equipment"].add(equipment)
            reasons.append(f"no Formiq equipment for {equipment!r}")

    for muscles in ("primaryMuscles", "secondaryMuscles"):
        if muscles not in record:
            continue
        if not _is_text_list(record[muscles]):
            reasons.append(f"{muscles} must be a list of text")
            continue
        for muscle in record[muscles]:
            if muscle not in MUSCLES:
                unresolved["muscles"].add(muscle)
                reasons.append(f"no Formiq muscle group for {muscle!r}")
    if isinstance(record.get("primaryMuscles"), list) and not record["primaryMuscles"]:
        reasons.append("primaryMuscles is empty")

    if "instructions" in record:
        if not _is_text_list(record["instructions"]):
            reasons.append("instructions must be a list of text")
        elif not record["instructions"]:
            warnings.append("no instructions")
        elif any(not step.strip() for step in record["instructions"]):
            warnings.append("a blank instruction step")
    if "images" in record:
        images = record["images"]
        if not isinstance(images, list):
            reasons.append("images must be a list")
        elif not all(is_image_path(path) for path in images):
            reasons.append("an image path is not '<exercise id>/<n>.<jpg|jpeg|png|webp>'")
        elif _valid_id(record.get("id")) and any(
            not path.startswith(f"{record['id']}/") for path in images
        ):
            reasons.append("an image path is outside the exercise's own directory")
        elif not images:
            warnings.append("no images")
    return reasons, warnings


def _mapped(record: dict[str, Any], name: str, warnings: list[str]) -> SourceExercise:
    muscles: dict[str, MuscleRole] = {}
    # a muscle group that is both primary and secondary is primary
    roles = (("primaryMuscles", MuscleRole.PRIMARY), ("secondaryMuscles", MuscleRole.SECONDARY))
    for key, role in roles:
        for muscle in record[key]:
            muscles.setdefault(MUSCLES[muscle], role)
    equipment = EQUIPMENT.get(record["equipment"]) if record["equipment"] is not None else None
    return SourceExercise(
        source_id=record["id"],
        name=name,
        difficulty=LEVELS[record["level"]],
        movement_pattern=MovementPattern.CARDIO if record["category"] == "cardio" else None,
        muscles=muscles,
        equipment=[equipment] if equipment else [],
        uses=uses_of(record["id"], record["category"], record["equipment"]),
        image_paths=list(record["images"]),
        record=record,
        warnings=warnings,
    )
