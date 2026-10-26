"""Recovery after a workout: how long each trained muscle rests, what a reported
discomfort changes, when to stop coaching and send the user to care, and sleep.

The rules, in the order the safety layer applies them:

- a warning sign needs medical care, so every nutrition, hydration and recovery
  timing item is withheld (safety_status, urgent_care_notice);
- pain or a known injury is for a doctor or physiotherapist: its muscles get no rest
  timing and no return-to-training time, which Formiq never gives;
- soreness of 4 to 6 out of 10 gives that muscle 72 hours, 7 or more also lists the
  warning signs to watch for; soreness of 0 to 3 changes nothing;
- otherwise a muscle trained as a main muscle rests 48 hours, and one worked only as
  a secondary muscle is noted but gets no window.

Pure: the completion time is passed in, and a discomfort is only ever an enum and a
number, never text. The caller decides which exercises count (main-workout work only).
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from app.guidance.sources import GuidanceItem, SourceId
from app.schemas.exercise import MuscleRole
from app.schemas.recovery_summary import BodyArea, DiscomfortKind, WarningSign

# ACSM_POSITION_2011: "A rest of >=48 h between sessions for any single muscle group is
# recommended" (evidence category A); the same stand says 48 to 72 h between sessions is
# needed to promote the adaptations to training.
REST_HOURS = 48
# Product rule: the upper end of that 48 to 72 h range, for a muscle the user reports
# sore (CHEUNG_DOMS_2003 describes delayed onset muscle soreness and advises reducing
# training for 1-2 days after intense soreness-causing exercise). The number is Formiq's.
# UNVERIFIED: that soreness peaks 24-72 h after training could not be read in
# CHEUNG_DOMS_2003 (its abstract does not state it, the full text is paywalled), so no
# text says it.
SORE_REST_HOURS = 72
# Product guardrails on a 0 to 10 rating, with no source: 4 and above is more than mild.
MODERATE_SORENESS = 4
SEVERE_SORENESS = 7
# AASM_SLEEP_2015: "Adults should sleep 7 or more hours per night on a regular basis to
# promote optimal health."
MIN_SLEEP_HOURS = 7
# Product rule: a self-reported sleep of 0 or less, or of more than 16 hours, is a data
# error and is ignored.
MAX_PLAUSIBLE_SLEEP_HOURS = 16

# The muscle groups of the catalog (the names seeded in `muscle_groups`) that each
# reported body area stands for. This is Formiq's own mapping, by the muscles that
# cross or surround the area; a joint maps to the muscles that move it.
AREA_MUSCLES: dict[BodyArea, tuple[str, ...]] = {
    BodyArea.NECK: ("Neck",),
    BodyArea.SHOULDERS: ("Shoulders", "Front Deltoid", "Rear Deltoid"),
    BodyArea.CHEST: ("Chest",),
    BodyArea.UPPER_BACK: ("Upper Back", "Lats"),
    BodyArea.LOWER_BACK: ("Lower Back",),
    BodyArea.ARMS: ("Biceps", "Triceps"),
    BodyArea.ELBOWS: ("Biceps", "Triceps", "Forearms"),
    BodyArea.WRISTS_HANDS: ("Forearms",),
    BodyArea.CORE: ("Core", "Obliques"),
    BodyArea.HIPS: ("Glutes", "Abductors", "Adductors"),
    BodyArea.GLUTES: ("Glutes",),
    BodyArea.FRONT_THIGHS: ("Quadriceps",),
    BodyArea.BACK_THIGHS: ("Hamstrings",),
    BodyArea.KNEES: ("Quadriceps", "Hamstrings", "Calves"),
    BodyArea.CALVES: ("Calves",),
    BodyArea.ANKLES_FEET: ("Calves",),
}

# How each warning sign is named to the user. The list of signs is Formiq's own and
# conservative: CDC_RHABDO supports dark urine and unusually severe muscle pain or
# weakness; ACSM_POSITION_2011 supports telling exercisers the warning signs and how
# to respond. The cardiac and nerve signs are added caution, not taken from them.
WARNING_SIGN_NAMES: dict[WarningSign, str] = {
    WarningSign.CHEST_PAIN: "chest pain",
    WarningSign.SHORTNESS_OF_BREATH: "shortness of breath",
    WarningSign.FAINTING_OR_DIZZINESS: "fainting or dizziness",
    WarningSign.DARK_URINE: "dark urine",
    WarningSign.SEVERE_SWELLING: "severe swelling",
    WarningSign.NUMBNESS_OR_TINGLING: "numbness or tingling",
    WarningSign.SUDDEN_SEVERE_PAIN: "sudden severe pain",
}

PAIN_ADVICE = (
    "stop exercises that load this area and see a doctor or physiotherapist. "
    "Formiq gives no time to return to training."
)


class SafetyStatus(StrEnum):
    OK = "OK"
    CAUTION = "CAUTION"
    SEEK_MEDICAL_CARE = "SEEK_MEDICAL_CARE"


class MuscleStatus(StrEnum):
    REST = "REST"
    ALSO_WORKED = "ALSO_WORKED"
    SEE_PROFESSIONAL = "SEE_PROFESSIONAL"


@dataclass(frozen=True)
class Discomfort:
    area: BodyArea
    kind: DiscomfortKind
    severity: int


@dataclass(frozen=True)
class TrainedMuscle:
    """A muscle group worked in a counted main-workout exercise, and its role there."""

    muscle: str
    role: MuscleRole


@dataclass(frozen=True)
class MuscleRecovery:
    """What a muscle needs. rest_hours and rest_until are None unless it has a window;
    a muscle for a professional never has one. role is None for a muscle the user
    reported but did not train in this workout."""

    muscle: str
    role: MuscleRole | None
    status: MuscleStatus
    rest_hours: int | None
    rest_until: datetime | None
    reasons: tuple[str, ...]
    source_ids: tuple[SourceId, ...]


def _hurts(item: Discomfort) -> bool:
    return item.kind in {DiscomfortKind.PAIN, DiscomfortKind.KNOWN_INJURY}


def _sore(item: Discomfort) -> bool:
    return item.kind is DiscomfortKind.SORENESS and item.severity >= MODERATE_SORENESS


def safety_status(
    warning_signs: Iterable[WarningSign],
    discomfort: Iterable[Discomfort],
    *,
    other_cautions: bool = False,
) -> SafetyStatus:
    """SEEK_MEDICAL_CARE for any warning sign. CAUTION for pain, an injury, soreness of
    4 or more, or another caution the caller found (a flagged note, a fast weight-loss
    goal). OK otherwise."""
    if tuple(warning_signs):
        return SafetyStatus.SEEK_MEDICAL_CARE
    items = tuple(discomfort)
    if other_cautions or any(_hurts(item) or _sore(item) for item in items):
        return SafetyStatus.CAUTION
    return SafetyStatus.OK


def withholds_guidance(status: SafetyStatus) -> bool:
    """Whether the status removes every estimate, hydration, food and recovery-timing item."""
    return status is SafetyStatus.SEEK_MEDICAL_CARE


def urgent_care_notice(warning_signs: Iterable[WarningSign]) -> GuidanceItem:
    """The single notice shown in place of guidance when a warning sign is reported."""
    reported = set(warning_signs)
    names = ", ".join(name for sign, name in WARNING_SIGN_NAMES.items() if sign in reported)
    return GuidanceItem(
        "SEEK_MEDICAL_CARE",
        f"You reported: {names}. Stop training and seek medical care now. Formiq gives no "
        "nutrition, hydration or recovery timing when a warning sign is reported.",
        (SourceId.CDC_RHABDO, SourceId.ACSM_POSITION_2011),
    )


def discomfort_notices(discomfort: Iterable[Discomfort]) -> tuple[GuidanceItem, ...]:
    """The safety notices that reported pain, an injury or severe soreness add."""
    items = tuple(discomfort)
    notices = []
    if any(_hurts(item) for item in items):
        notices.append(
            GuidanceItem(
                "PAIN_OR_INJURY",
                f"You reported pain or a known injury: {PAIN_ADVICE}",
            )
        )
    if any(
        item.kind is DiscomfortKind.SORENESS and item.severity >= SEVERE_SORENESS
        for item in items
    ):
        signs = ", ".join(WARNING_SIGN_NAMES.values())
        notices.append(
            GuidanceItem(
                "SEVERE_SORENESS",
                "You reported severe soreness. Watch for these warning signs, and seek "
                f"medical care if any appears: {signs}.",
                (SourceId.CDC_RHABDO,),
            )
        )
    return tuple(notices)


def muscle_recovery(
    trained: Iterable[TrainedMuscle],
    discomfort: Iterable[Discomfort],
    completed_at: datetime,
) -> tuple[MuscleRecovery, ...]:
    """Each trained muscle's recovery, then each reported muscle that was not trained and
    still needs a status. A muscle is PRIMARY if it is primary in any counted exercise."""
    roles: dict[str, MuscleRole] = {}
    for item in trained:
        if item.role is MuscleRole.PRIMARY or item.muscle not in roles:
            roles[item.muscle] = item.role

    hurting: set[str] = set()
    soreness: dict[str, int] = {}
    reported: dict[str, None] = {}
    for item in discomfort:
        for muscle in AREA_MUSCLES[item.area]:
            reported.setdefault(muscle)
            if _hurts(item):
                hurting.add(muscle)
            elif item.kind is DiscomfortKind.SORENESS:
                soreness[muscle] = max(soreness.get(muscle, item.severity), item.severity)

    recoveries = []
    for muscle in (*roles, *(name for name in reported if name not in roles)):
        role = roles.get(muscle)
        reasons = [] if role is not None else ["Not trained in this workout."]
        severity = soreness.get(muscle, 0)
        if muscle in hurting:
            recoveries.append(
                MuscleRecovery(
                    muscle,
                    role,
                    MuscleStatus.SEE_PROFESSIONAL,
                    None,
                    None,
                    (*reasons, f"Pain or a known injury was reported here: {PAIN_ADVICE}"),
                    (),
                )
            )
        elif severity >= MODERATE_SORENESS:
            recoveries.append(
                _rest(
                    muscle,
                    role,
                    SORE_REST_HOURS,
                    completed_at,
                    (
                        *reasons,
                        f"You reported soreness of {severity} out of 10: allow "
                        f"{SORE_REST_HOURS} hours before training it hard again.",
                    ),
                    (SourceId.ACSM_POSITION_2011, SourceId.CHEUNG_DOMS_2003),
                )
            )
        elif role is MuscleRole.PRIMARY:
            recoveries.append(
                _rest(
                    muscle,
                    role,
                    REST_HOURS,
                    completed_at,
                    (
                        f"Trained as a main muscle in this workout: allow {REST_HOURS} "
                        "hours before training it hard again.",
                    ),
                    (SourceId.ACSM_POSITION_2011,),
                )
            )
        elif role is MuscleRole.SECONDARY:
            recoveries.append(
                MuscleRecovery(
                    muscle,
                    role,
                    MuscleStatus.ALSO_WORKED,
                    None,
                    None,
                    ("Worked as a supporting muscle only, so no rest window is set.",),
                    (),
                )
            )
    return tuple(recoveries)


def flag_for_professional(
    recoveries: Iterable[MuscleRecovery], muscles: Iterable[str], reason: str
) -> tuple[MuscleRecovery, ...]:
    """The recoveries, with the named muscles turned into SEE_PROFESSIONAL: no rest window
    and no return time, as for reported pain, with the reason added once. A muscle with no
    recovery here is not added, and the sources stay those of the entry."""
    flagged = set(muscles)
    result = []
    for recovery in recoveries:
        if recovery.muscle in flagged:
            reasons = recovery.reasons
            recovery = replace(
                recovery,
                status=MuscleStatus.SEE_PROFESSIONAL,
                rest_hours=None,
                rest_until=None,
                reasons=reasons if reason in reasons else (*reasons, reason),
            )
        result.append(recovery)
    return tuple(result)


def _rest(
    muscle: str,
    role: MuscleRole | None,
    hours: int,
    completed_at: datetime,
    reasons: tuple[str, ...],
    source_ids: tuple[SourceId, ...],
) -> MuscleRecovery:
    return MuscleRecovery(
        muscle,
        role,
        MuscleStatus.REST,
        hours,
        completed_at + timedelta(hours=hours),
        reasons,
        source_ids,
    )


def general_recovery_items() -> tuple[GuidanceItem, ...]:
    """Recovery guidance that does not depend on the session."""
    return (
        GuidanceItem(
            "GENTLE_MOVEMENT",
            "Gentle movement, such as an easy walk, can ease muscle soreness for a while.",
            # CHEUNG_DOMS_2003 (abstract): exercise relieves the pain of soreness, but the
            # effect is temporary
            (SourceId.CHEUNG_DOMS_2003,),
        ),
        GuidanceItem(
            "SPREAD_PROTEIN",
            "Spread your protein across your meals rather than eating most of it at once.",
            # ISSN_PROTEIN_2017: doses evenly distributed, every 3-4 h, across the day
            (SourceId.ISSN_PROTEIN_2017,),
        ),
    )


def sleep_item(sleep_hours: float | None) -> GuidanceItem | None:
    """A note when the user's self-reported typical sleep is under 7 hours. A value of 0 or
    less, or over 16, is ignored, and so is one that meets the recommendation."""
    if sleep_hours is None or not math.isfinite(sleep_hours):
        return None
    if sleep_hours <= 0 or sleep_hours > MAX_PLAUSIBLE_SLEEP_HOURS:
        return None
    if sleep_hours >= MIN_SLEEP_HOURS:
        return None
    return GuidanceItem(
        "SLEEP_BELOW_RECOMMENDED",
        f"You report sleeping about {sleep_hours:g} hours a night (self-reported, not "
        f"measured). Adults are recommended {MIN_SLEEP_HOURS} or more hours.",
        (SourceId.AASM_SLEEP_2015,),
    )

