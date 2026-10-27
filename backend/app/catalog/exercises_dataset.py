"""The exercises-dataset dataset (github.com/hasaneyldrm/exercises-dataset):
reading, validating and mapping its records to Formiq's catalog. Nothing here
touches the database (app.services.exercise_import_service applies the result),
and no image or GIF is ever read or registered.

The dataset is the pinned copy in backend/data/exercises-dataset (see SOURCE.md
there): it is read from disk, never fetched. It returns the same ParsedSource as
app.catalog.free_exercise_db, so one importer applies either.

What Formiq keeps of a record, and what it does not make up:

- The external id (source_id), the source (EXERCISES_DATASET) and the pinned
  commit (source_version). Formiq's own id is its own.
- The record as the file has it, except that only the English instructions are
  kept (source_record): the other nine languages stay in the pinned file, whose
  checksum is verified, and Formiq shows one language. Every other field is kept,
  the media references included, as text that is never followed.
- The name, normalized for display (Title Case, explicit corrections for the
  few malformed names); the original is in the record.
- Muscles and equipment, through the explicit tables below. A value without an
  entry is never guessed: the record is rejected and the value reported.
- No difficulty (the source has none, so UNRATED), no movement pattern, no
  section it suits (uses is empty, so the coach cannot put it in a proposed
  workout until Formiq classifies it), no description, no sets, reps or rest, and
  no image (image_paths stays empty).

A record is held back, with the reason, when it cannot be trusted to say what it
needs or trains:

- its equipment value is not a piece of equipment ("weighted", "assisted"), or
  has no entry in the table;
- its name or steps name gear that its equipment value does not ("body weight"
  with a pull-up bar, a dumbbell exercise on a bench): the coach filters by
  equipment, and a false "needs nothing else" would offer it to someone who
  cannot do it;
- its primary muscle has no Formiq muscle group, or is not in the table;
- its name is unusable, or another record has it.
"""

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.catalog.free_exercise_db import (
    ParsedSource,
    RejectedRecord,
    SourceExercise,
    SourceFileError,
)
from app.schemas.exercise import Difficulty, ExerciseSource, MuscleRole

SOURCE = ExerciseSource.EXERCISES_DATASET
SOURCE_URL = "https://github.com/hasaneyldrm/exercises-dataset"
# the upstream commit the vendored file is from, and that file's SHA-256
SOURCE_VERSION = "7455efae41b330c265e7cd4b78dfa848e7ce5ebd"
SOURCE_SHA256 = "656634224b8977b99a6d765470ee123260d4979715eaa4e7c0b7c8bb0d79f93d"
SOURCE_FILE = Path(__file__).resolve().parents[2] / "data" / "exercises-dataset" / "exercises.json"

# The published schema's fields (exercises.schema.json): every one is required.
FIELDS = frozenset(
    {
        "id",
        "name",
        "category",
        "body_part",
        "equipment",
        "instructions",
        "instruction_steps",
        "muscle_group",
        "secondary_muscles",
        "target",
        "media_id",
        "image",
        "gif_url",
        "attribution",
        "created_at",
    }
)
REQUIRED_FIELDS = FIELDS

SOURCE_ID = re.compile(r"[0-9]{4}")
IMAGE = re.compile(r"images/.+\.(?:jpg|jpeg|png)")
GIF = re.compile(r"videos/.+\.gif")
MAX_NAME_LENGTH = 150
# the one language Formiq keeps
LANGUAGE = "en"
BODY_PARTS = frozenset(
    {
        "back",
        "cardio",
        "chest",
        "lower arms",
        "lower legs",
        "neck",
        "shoulders",
        "upper arms",
        "upper legs",
        "waist",
    }
)

# --- the reasons a record is rejected: the text before the colon, which a
# report counts by (reason_of)
INVALID_RECORD = "invalid record"
INVALID_NAME = "invalid name"
DUPLICATE_NAME = "duplicate name"
UNUSABLE_EQUIPMENT_VALUE = "unusable equipment value"
UNKNOWN_EQUIPMENT = "unknown equipment value"
AMBIGUOUS_EQUIPMENT = "ambiguous equipment"
UNMAPPED_PRIMARY_MUSCLE = "unmapped primary muscle"
UNKNOWN_MUSCLE = "unknown muscle value"

# --- names

# The four names whose degree sign was read in the wrong character set ("в°"),
# by record id, each with the name as the file has it and as it should be.
# Corrected here and nowhere else: any other name with a character outside
# NAME_CHARACTERS is rejected, never repaired by guesswork.
MALFORMED_NAMES = {
    "0738": ("sled 45в° calf press", "sled 45° calf press"),
    "0739": ("sled 45в° leg press", "sled 45° leg press"),
    "0740": ("sled 45в° leg wide press", "sled 45° leg wide press"),
    "1464": ("sled 45в° leg press (back pov)", "sled 45° leg press (back pov)"),
}
NAME_CHARACTERS = re.compile(r"[0-9A-Za-z .,()/_°-]+")
# Words that are acronyms: Title Case would write "Ez" and "Pov".
ACRONYMS = {"ez": "EZ", "pov": "POV", "jm": "JM", "sz": "SZ"}
_WORD = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]+")


def display_name(name: str) -> str:
    """The name for display: each word capitalized (the catalog's convention:
    "Over A Bench"), the acronyms in capitals, the rest of the name as it is. It
    never changes the words: comparable_name is the same before and after."""

    def word(match: re.Match[str]) -> str:
        text = match.group(0)
        return ACRONYMS.get(text.casefold(), text[0].upper() + text[1:])

    return _WORD.sub(word, name.strip())


def comparable_name(name: str) -> str:
    """The name without case, spaces or punctuation, as the importer compares
    names (app.services.exercise_import_service.comparable_name): two records
    that have the same one are the same exercise to the catalog."""
    return re.sub(r"[^0-9a-z]", "", name.casefold())


# --- equipment

NO_EQUIPMENT = "body weight"
# Source equipment to Formiq's. "body weight" needs none, but only when nothing in
# the record says otherwise (unnamed_gear). A machine the source names more
# exactly than the catalog does is the catalog's "Machine"; equipment the catalog
# has no item for is "Other Equipment", as that item's description says.
EQUIPMENT: dict[str, str | None] = {
    NO_EQUIPMENT: None,
    "barbell": "Barbell",
    # a standard bar, as the catalog's Barbell
    "olympic barbell": "Barbell",
    "dumbbell": "Dumbbell",
    "kettlebell": "Kettlebell",
    "cable": "Cable Machine",
    "smith machine": "Smith Machine",
    "medicine ball": "Medicine Ball",
    "stationary bike": "Stationary Bike",
    "band": "Resistance Band",
    "resistance band": "Resistance Band",
    "stability ball": "Exercise Ball",
    "ez barbell": "EZ Curl Bar",
    "leverage machine": "Machine",
    "sled machine": "Machine",
    "skierg machine": "Machine",
    "stepmill machine": "Machine",
    "elliptical machine": "Machine",
    "upper body ergometer": "Machine",
    # A hex bar is not the catalog's Barbell, and "roller" is never called a foam roller in
    # the text of these records, so neither is assumed to be one.
    "trap bar": "Other Equipment",
    "roller": "Other Equipment",
    "wheel roller": "Other Equipment",
    "bosu ball": "Other Equipment",
    "rope": "Other Equipment",
    "hammer": "Other Equipment",
    "tire": "Other Equipment",
}
# Values that are not a piece of equipment to map: the record is held, with this reason.
UNUSABLE_EQUIPMENT: dict[str, str] = {
    "weighted": "it says an exercise is loaded, not with what",
    "assisted": "it means a machine for some records and a helper or a strap for others",
}
# The values that are a machine: its seat, bench and rack are part of it, so its
# text naming them says nothing about other gear.
MACHINES = frozenset(
    {
        "leverage machine",
        "sled machine",
        "skierg machine",
        "stepmill machine",
        "elliptical machine",
        "upper body ergometer",
        "stationary bike",
    }
)

# Gear a record's text may name, by label (whole words, any case). A record names
# the gear its equipment value is: that is what ACCOUNTED lists. Any other gear
# in its name or steps makes the record's equipment ambiguous (unnamed_gear).
GEAR: dict[str, str] = {
    "bar": r"bars?",
    "barbell": r"barbells?",
    "bench": r"benche?s?",
    "chair": r"chairs?",
    "box": r"box(?:es)?",
    "stool": r"stools?",
    "couch": r"couch|sofa",
    "table": r"tables?",
    "ledge": r"ledges?",
    "stairs": r"stairs?|staircase",
    "platform": r"platforms?",
    "elevated surface": r"elevated surfaces?",
    "rings": r"rings?",
    "suspension trainer": r"trx|suspension",
    "towel": r"towels?",
    "sliders": r"sliders?|gliding discs?",
    "rope": r"ropes?",
    "strap": r"straps?",
    "pole": r"poles?",
    "railing": r"railings?",
    "doorway": r"doorways?",
    "dumbbell": r"dumbbells?",
    "kettlebell": r"kettlebells?",
    "band": r"bands?",
    "plates": r"(?:weight )?plates?",
    "ball": r"(?:swiss|stability|exercise|medicine) balls?",
    "balance board": r"balance boards?",
    "bosu": r"bosu",
    "foam roller": r"foam rollers?",
    "rack": r"racks?",
    "preacher bench": r"preacher",
}
# Gear that only a name gives away: "incline" and "decline" are of a bench or an
# elevated surface, and a step-up needs a step; their steps say it in other words
# (which GEAR reads) or not at all.
NAME_GEAR: dict[str, str] = {
    "incline": r"incline",
    "decline": r"decline",
    "step": r"step[- ]?(?:ups?|downs?)",
}
_GEAR = {label: re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE) for label, pattern in GEAR.items()}
_NAME_GEAR = {
    label: re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE) for label, pattern in NAME_GEAR.items()
}
_WEIGHT_ACCOUNTED = {"bar", "barbell", "plates"}
# What each equipment value accounts for in the record's text
ACCOUNTED: dict[str, frozenset[str]] = {
    "barbell": frozenset(_WEIGHT_ACCOUNTED),
    "olympic barbell": frozenset(_WEIGHT_ACCOUNTED),
    "ez barbell": frozenset(_WEIGHT_ACCOUNTED),
    "trap bar": frozenset(_WEIGHT_ACCOUNTED),
    "smith machine": frozenset(_WEIGHT_ACCOUNTED),
    "dumbbell": frozenset({"dumbbell"}),
    "kettlebell": frozenset({"kettlebell"}),
    "cable": frozenset({"bar", "rope", "strap"}),
    "band": frozenset({"band"}),
    "resistance band": frozenset({"band"}),
    "stability ball": frozenset({"ball"}),
    "medicine ball": frozenset({"ball"}),
    "bosu ball": frozenset({"bosu", "ball"}),
    "rope": frozenset({"rope"}),
}


def unnamed_gear(name: str, steps: list[str], equipment: str) -> list[str]:
    """The gear, by label, that the record's name or English steps name and its
    equipment value does not: the record's equipment is then ambiguous. None for
    a machine, whose own seat, bench or rack is not another piece of gear."""
    if equipment in MACHINES:
        return []
    text = " ".join(steps)
    found = {
        label for label, pattern in _GEAR.items() if pattern.search(name) or pattern.search(text)
    }
    found |= {label for label, pattern in _NAME_GEAR.items() if pattern.search(name)}
    return sorted(found - ACCOUNTED.get(equipment, frozenset()))


# --- muscles

# Source muscles to Formiq's muscle groups, for the primary muscle (target) and
# the secondary ones alike. None: the source names a muscle or region Formiq has no
# group for, which holds a record whose primary muscle it is and is left unlinked
# (and reported) for a secondary one. Formiq's Upper Back is "the trapezius,
# rhomboids and other muscles between the shoulder blades". Of the sub-parts and
# neighbours named here, each is mapped to the group that contains it.
MUSCLES: dict[str, str | None] = {
    "abs": "Core",
    "abdominals": "Core",
    "lower abs": "Core",
    "core": "Core",
    "obliques": "Obliques",
    "pectorals": "Chest",
    "chest": "Chest",
    "upper chest": "Chest",
    "biceps": "Biceps",
    "brachialis": "Biceps",
    "triceps": "Triceps",
    "delts": "Shoulders",
    "deltoids": "Shoulders",
    "shoulders": "Shoulders",
    "rotator cuff": "Shoulders",
    "rear deltoids": "Rear Deltoid",
    "upper back": "Upper Back",
    "traps": "Upper Back",
    "trapezius": "Upper Back",
    "rhomboids": "Upper Back",
    "lats": "Lats",
    "latissimus dorsi": "Lats",
    "lower back": "Lower Back",
    "glutes": "Glutes",
    "quads": "Quadriceps",
    "quadriceps": "Quadriceps",
    "hamstrings": "Hamstrings",
    "adductors": "Adductors",
    "inner thighs": "Adductors",
    "groin": "Adductors",
    "abductors": "Abductors",
    "calves": "Calves",
    "soleus": "Calves",
    "forearms": "Forearms",
    "wrist flexors": "Forearms",
    "wrist extensors": "Forearms",
    "wrists": "Forearms",
    "hands": "Forearms",
    "grip muscles": "Forearms",
    "levator scapulae": "Neck",
    "sternocleidomastoid": "Neck",
    # no Formiq group, or too general to name one
    # "spine" is the target of lower-back extensions, and also of an exercise-ball
    # hug, upward-facing dog and a pelvic tilt: it is not read as the lower back
    "spine": None,
    "back": None,
    "serratus anterior": None,
    # not a muscle: the target of the cardio records
    "cardiovascular system": None,
    "hip flexors": None,
    "ankles": None,
    "feet": None,
    "ankle stabilizers": None,
    "shins": None,
}


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


def reason_of(reason: str) -> str:
    """The kind of a rejection reason: its text before the colon."""
    return reason.split(":", 1)[0]


def parse_records(records: list[Any]) -> ParsedSource:
    """Validates and maps every record, in source id order. A record is
    rejected, with every reason that applies, for a missing or malformed field, an
    unusable name or one another record has, equipment or a muscle that Formiq
    cannot map (or a record that does not say what equipment it needs), or an id
    another record has."""
    exercises: list[SourceExercise] = []
    rejected: list[RejectedRecord] = []
    unresolved: dict[str, set[str]] = defaultdict(set)
    unknown_fields: set[str] = set()
    seen_ids: set[str] = set()
    seen_names: dict[str, str] = {}

    def order(item: tuple[int, Any]) -> tuple[str, int]:
        index, record = item
        source_id = record.get("id") if isinstance(record, dict) else None
        return (source_id if isinstance(source_id, str) else "", index)

    for index, record in sorted(enumerate(records), key=order):
        if not isinstance(record, dict):
            rejected.append(RejectedRecord(index, None, [f"{INVALID_RECORD}: not an object"]))
            continue
        source_id = record.get("id") if _valid_id(record.get("id")) else None
        reasons, warnings, name = _check(record, unresolved)
        if source_id is not None and source_id in seen_ids:
            reasons.append(f"{INVALID_RECORD}: another record has the id {source_id!r}")
        if name is not None and comparable_name(name) in seen_names:
            reasons.append(
                f"{DUPLICATE_NAME}: record {seen_names[comparable_name(name)]} has the name "
                f"{name!r}"
            )
        # read for every record, so that a rejection names all its reasons
        muscles = {}
        if _is_text(record.get("target")) and _is_text_list(record.get("secondary_muscles")):
            muscles = _muscles(record, unresolved, reasons, warnings)
        if reasons:
            rejected.append(RejectedRecord(index, source_id, reasons))
            continue
        seen_ids.add(source_id)
        seen_names[comparable_name(name)] = source_id
        unknown_fields |= set(record) - FIELDS
        exercises.append(_mapped(record, name, muscles, warnings))
    return ParsedSource(exercises, rejected, dict(unresolved), unknown_fields)


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and SOURCE_ID.fullmatch(value) is not None


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_text_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _check(
    record: dict[str, Any], unresolved: dict[str, set[str]]
) -> tuple[list[str], list[str], str | None]:
    """Why the record cannot be imported (none when it can), the warnings of a
    valid but incomplete record, and its name for display (None when it has no
    usable one)."""
    reasons: list[str] = []
    warnings: list[str] = []
    name: str | None = None
    if missing := sorted(REQUIRED_FIELDS - set(record)):
        reasons.append(f"{INVALID_RECORD}: missing fields: {', '.join(missing)}")

    if "id" in record and not _valid_id(record["id"]):
        reasons.append(f"{INVALID_RECORD}: id must be four digits")
    if "name" in record:
        name, reason = _name(record)
        if reason:
            reasons.append(reason)
    for text_field in ("category", "muscle_group", "target", "media_id", "attribution"):
        if text_field in record and not _is_text(record[text_field]):
            reasons.append(f"{INVALID_RECORD}: {text_field} must be non-blank text")
    if "body_part" in record and record["body_part"] not in BODY_PARTS:
        reasons.append(f"{INVALID_RECORD}: unknown body_part {record['body_part']!r}")
    if "created_at" in record and not isinstance(record["created_at"], str):
        reasons.append(f"{INVALID_RECORD}: created_at must be text")
    for media, shape in (("image", IMAGE), ("gif_url", GIF)):
        if media in record and not (
            isinstance(record[media], str) and shape.fullmatch(record[media])
        ):
            reasons.append(f"{INVALID_RECORD}: {media} is not the path the schema allows")

    if "instructions" in record:
        text = record["instructions"]
        if not isinstance(text, dict) or not _is_text(text.get(LANGUAGE)):
            reasons.append(f"{INVALID_RECORD}: instructions.{LANGUAGE} must be non-blank text")
    if "instruction_steps" in record:
        by_language = record["instruction_steps"]
        steps = by_language.get(LANGUAGE) if isinstance(by_language, dict) else None
        if not _is_text_list(steps):
            reasons.append(f"{INVALID_RECORD}: instruction_steps.{LANGUAGE} must be a list of text")
        elif not steps:
            warnings.append("no instructions")
        elif any(not step.strip() for step in steps):
            warnings.append("a blank instruction step")

    if "secondary_muscles" in record and not _is_text_list(record["secondary_muscles"]):
        reasons.append(f"{INVALID_RECORD}: secondary_muscles must be a list of text")

    if "equipment" in record:
        reasons.extend(_equipment_reasons(record, unresolved))
    return reasons, warnings, name


def _name(record: dict[str, Any]) -> tuple[str | None, str | None]:
    """The name for display, or why there is none."""
    name = record["name"]
    if not _is_text(name):
        return None, f"{INVALID_NAME}: the name must be non-blank text"
    name = name.strip()
    known = MALFORMED_NAMES.get(record.get("id"))
    if known is not None and name == known[0]:
        name = known[1]
    if not NAME_CHARACTERS.fullmatch(name):
        odd = sorted({c for c in name if not NAME_CHARACTERS.fullmatch(c)})
        return None, f"{INVALID_NAME}: unexpected character {', '.join(map(repr, odd))} in {name!r}"
    if len(name) > MAX_NAME_LENGTH:
        return None, f"{INVALID_NAME}: longer than {MAX_NAME_LENGTH} characters"
    return display_name(name), None


def _equipment_reasons(record: dict[str, Any], unresolved: dict[str, set[str]]) -> list[str]:
    equipment = record["equipment"]
    if not _is_text(equipment):
        return [f"{INVALID_RECORD}: equipment must be non-blank text"]
    if equipment in UNUSABLE_EQUIPMENT:
        unresolved["equipment"].add(equipment)
        return [f"{UNUSABLE_EQUIPMENT_VALUE}: {equipment!r}: {UNUSABLE_EQUIPMENT[equipment]}"]
    if equipment not in EQUIPMENT:
        unresolved["equipment"].add(equipment)
        return [f"{UNKNOWN_EQUIPMENT}: no Formiq equipment for {equipment!r}"]
    steps = record.get("instruction_steps")
    english = steps.get(LANGUAGE) if isinstance(steps, dict) else None
    if not isinstance(record.get("name"), str) or not _is_text_list(english):
        return []
    if gear := unnamed_gear(record["name"], english, equipment):
        return [
            f"{AMBIGUOUS_EQUIPMENT}: the record says {equipment!r} but its text names "
            f"{', '.join(gear)}"
        ]
    return []


def _muscles(
    record: dict[str, Any],
    unresolved: dict[str, set[str]],
    reasons: list[str],
    warnings: list[str],
) -> dict[str, MuscleRole]:
    """Formiq's muscle groups and roles for the record, primary first. The primary
    muscle is the record's target; muscle_group is not read, since it is always the
    first of the secondary muscles. A group that is both is primary."""
    muscles: dict[str, MuscleRole] = {}
    target = record["target"]
    if target not in MUSCLES:
        unresolved["muscles"].add(target)
        reasons.append(f"{UNKNOWN_MUSCLE}: no Formiq muscle group for {target!r}")
    elif MUSCLES[target] is None:
        unresolved["primary muscles"].add(target)
        reasons.append(
            f"{UNMAPPED_PRIMARY_MUSCLE}: the target {target!r} has no Formiq muscle group"
        )
    else:
        muscles[MUSCLES[target]] = MuscleRole.PRIMARY
    for muscle in record["secondary_muscles"]:
        if muscle not in MUSCLES:
            unresolved["muscles"].add(muscle)
            reasons.append(f"{UNKNOWN_MUSCLE}: no Formiq muscle group for {muscle!r}")
        elif MUSCLES[muscle] is None:
            unresolved["secondary muscles"].add(muscle)
            warnings.append(
                f"secondary muscle {muscle!r} has no Formiq muscle group: not linked (the record "
                "keeps it)"
            )
        else:
            muscles.setdefault(MUSCLES[muscle], MuscleRole.SECONDARY)
    return muscles


def english_record(record: dict[str, Any]) -> dict[str, Any]:
    """The record as the file has it, with only the English instructions."""
    return {
        **record,
        "instructions": {LANGUAGE: record["instructions"][LANGUAGE]},
        "instruction_steps": {LANGUAGE: record["instruction_steps"][LANGUAGE]},
    }


def _mapped(
    record: dict[str, Any],
    name: str,
    muscles: dict[str, MuscleRole],
    warnings: list[str],
) -> SourceExercise:
    mapped = EQUIPMENT[record["equipment"]]
    return SourceExercise(
        source_id=record["id"],
        name=name,
        # the source gives no level, and none is guessed
        difficulty=Difficulty.UNRATED,
        movement_pattern=None,
        muscles=muscles,
        equipment=[mapped] if mapped else [],
        # Formiq has not classified it for any section: searchable and readable, not proposable
        uses=[],
        # the media are not Formiq's to register or serve
        image_paths=[],
        record=english_record(record),
        description=None,
        warnings=warnings,
    )
