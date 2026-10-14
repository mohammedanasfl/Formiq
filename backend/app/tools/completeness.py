"""Whether a proposed workout's main exercises fulfil its focus: Formiq's own
rules, so a proposal is judged the same way whatever the model wrote.

A main exercise belongs to the body regions of its primary muscles, never of
its secondary ones. Few imported exercises have a movement pattern, so the
regions come from the muscles every one lists. A region's main movers
(REGION_MUSCLES) cover it; its accessory muscles (REGION_ACCESSORIES) only
belong to it: a curl or a farmer's carry is an upper-body pull exercise, but
never covers the pull a workout needs, nor a calf raise its lower body.

Each focus (FOCUS_RULES) names the regions its exercises count for, and the
regions it must cover: a full-body workout covers the lower body, an
upper-body push and an upper-body pull. A core exercise may go with any focus, but counts
only for a full-body or a core workout; an exercise for none of the focus's
regions does not belong in it. Only an exercise of at least MIN_COUNTED_SETS
sets counts, and two exercises with the same name (name_key) are one.

The minimums are coaching defaults, not medical rules: a short session (under
SHORT_SESSION_MINUTES) needs fewer exercises, never less coverage.
"""

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.schemas.coach import BodyRegion, SessionFocus
from app.schemas.exercise import MuscleRole
from app.tools.limits import (
    MAX_REQUIRED_MINUTES,
    MIN_COUNTED_SETS,
    MIN_FOCUSED_EXERCISES,
    MIN_FULL_BODY_EXERCISES,
    MIN_SHORT_SESSION_EXERCISES,
    MIN_WARM_UP_MINUTES,
    SHORT_SESSION_MINUTES,
)

LOWER_BODY = BodyRegion.LOWER_BODY
UPPER_PUSH = BodyRegion.UPPER_PUSH
UPPER_PULL = BodyRegion.UPPER_PULL
CORE = BodyRegion.CORE

# The catalog's muscle groups in each region; the neck is in none. A region's
# main movers cover it; its accessory muscles only belong to it. The catalog's
# "Shoulders" stands for the deltoids as a whole, and is counted as pushing.
REGION_MUSCLES = {
    LOWER_BODY: ("Quadriceps", "Glutes", "Hamstrings"),
    UPPER_PUSH: ("Chest", "Shoulders", "Front Deltoid"),
    UPPER_PULL: ("Upper Back", "Lats", "Rear Deltoid"),
    CORE: ("Core", "Obliques", "Lower Back"),
}
REGION_ACCESSORIES = {
    LOWER_BODY: ("Calves", "Adductors", "Abductors"),
    UPPER_PUSH: ("Triceps",),
    UPPER_PULL: ("Biceps", "Forearms"),
    CORE: (),
}
MOVER_REGIONS = {
    muscle.casefold(): region for region, muscles in REGION_MUSCLES.items() for muscle in muscles
}
MUSCLE_REGIONS = MOVER_REGIONS | {
    muscle.casefold(): region
    for region, muscles in REGION_ACCESSORIES.items()
    for muscle in muscles
}
REGION_NAMES = {
    LOWER_BODY: "lower body",
    UPPER_PUSH: "upper-body push",
    UPPER_PULL: "upper-body pull",
    CORE: "core",
}


@dataclass(frozen=True)
class FocusRule:
    # the regions whose exercises count towards the minimum
    counted: frozenset[BodyRegion]
    # the regions the main workout must train
    required: frozenset[BodyRegion]
    # main exercises that count, in a session that is not short
    minimum: int

    @property
    def allowed(self) -> frozenset[BodyRegion]:
        """The regions an exercise of this focus may train: its own, and the core."""
        return self.counted | {CORE}


FOCUS_RULES = {
    SessionFocus.FULL_BODY: FocusRule(
        frozenset(BodyRegion),
        frozenset({LOWER_BODY, UPPER_PUSH, UPPER_PULL}),
        MIN_FULL_BODY_EXERCISES,
    ),
    SessionFocus.UPPER_BODY: FocusRule(
        frozenset({UPPER_PUSH, UPPER_PULL}),
        frozenset({UPPER_PUSH, UPPER_PULL}),
        MIN_FOCUSED_EXERCISES,
    ),
    SessionFocus.LOWER_BODY: FocusRule(
        frozenset({LOWER_BODY}), frozenset({LOWER_BODY}), MIN_FOCUSED_EXERCISES
    ),
    SessionFocus.PUSH: FocusRule(
        frozenset({UPPER_PUSH}), frozenset({UPPER_PUSH}), MIN_FOCUSED_EXERCISES
    ),
    SessionFocus.PULL: FocusRule(
        frozenset({UPPER_PULL}), frozenset({UPPER_PULL}), MIN_FOCUSED_EXERCISES
    ),
    SessionFocus.CORE: FocusRule(frozenset({CORE}), frozenset({CORE}), MIN_FOCUSED_EXERCISES),
}


def _primary_regions(exercise: Any, regions: dict[str, BodyRegion]) -> frozenset[BodyRegion]:
    return frozenset(
        region
        for item in exercise.muscles
        if item.role == MuscleRole.PRIMARY
        and (region := regions.get(item.muscle_group.name.casefold())) is not None
    )


def regions_of(exercise: Any) -> frozenset[BodyRegion]:
    """The regions the exercise belongs to: those of its primary muscles."""
    return _primary_regions(exercise, MUSCLE_REGIONS)


def covered_by(exercise: Any) -> frozenset[BodyRegion]:
    """The regions the exercise covers: those a primary muscle of it is a main
    mover of."""
    return _primary_regions(exercise, MOVER_REGIONS)


def in_order(regions: Iterable[BodyRegion]) -> list[BodyRegion]:
    regions = set(regions)
    return [region for region in BodyRegion if region in regions]


def name_key(name: str) -> str:
    """An exercise's name as two exercises are told apart: without case,
    punctuation, spacing or a plural "s" ("Push-Up" and "Pushups" are one)."""
    words = re.findall(r"[a-z0-9]+", name.casefold())
    return "".join(word[:-1] if len(word) > 2 and word.endswith("s") else word for word in words)


def is_short(max_minutes: int | None) -> bool:
    """Whether the user has so little time that fewer exercises will do."""
    return max_minutes is not None and max_minutes < SHORT_SESSION_MINUTES


def required_exercises(focus: SessionFocus, max_minutes: int | None) -> int:
    """How many main exercises must count towards the focus."""
    return MIN_SHORT_SESSION_EXERCISES if is_short(max_minutes) else FOCUS_RULES[focus].minimum


def minimum_warm_up_minutes(max_minutes: int | None) -> int:
    """The shortest warm-up, by the duration estimate: any, in a short session."""
    return 0 if is_short(max_minutes) else MIN_WARM_UP_MINUTES


def minimum_minutes(max_minutes: int | None) -> int:
    """The shortest proposal, by the duration estimate, when the user said how
    long they have: half of it, at most MAX_REQUIRED_MINUTES. None said: any."""
    if max_minutes is None:
        return 0
    return min(math.ceil(max_minutes / 2), MAX_REQUIRED_MINUTES)


def is_beginner(fitness_experience: str | None) -> bool:
    """Whether the profile's experience, free text, says beginner."""
    return fitness_experience is not None and "beginner" in fitness_experience.casefold()


@dataclass(frozen=True)
class Assessment:
    # the regions the main exercises cover
    trained: frozenset[BodyRegion]
    # the regions the focus needs that no main exercise covers
    missing: frozenset[BodyRegion]
    # the main exercises that count, and how many must
    counted: int
    required: int
    # the main exercises that train none of the focus's regions
    off_focus: list[Any]


def assess(
    focus: SessionFocus, main: Sequence[tuple[Any, int]], max_minutes: int | None
) -> Assessment:
    """The main workout, as (catalog exercise, sets) in order, against its focus."""
    rule = FOCUS_RULES[focus]
    trained: set[BodyRegion] = set()
    counted: set[str] = set()
    off_focus = []
    for exercise, sets in main:
        regions = regions_of(exercise) & rule.allowed
        if not regions:
            off_focus.append(exercise)
            continue
        trained |= covered_by(exercise) & rule.allowed
        if sets >= MIN_COUNTED_SETS and regions & rule.counted:
            counted.add(name_key(exercise.name))
    return Assessment(
        trained=frozenset(trained),
        missing=rule.required - trained,
        counted=len(counted),
        required=required_exercises(focus, max_minutes),
        off_focus=off_focus,
    )


def trainable(pool: Iterable[Any], region: BodyRegion) -> bool:
    """Whether an exercise of the pool covers the region."""
    return any(region in covered_by(exercise) for exercise in pool)


def countable(pool: Iterable[Any], focus: SessionFocus) -> int:
    """How many different exercises of the pool would count towards the focus."""
    counted = FOCUS_RULES[focus].counted
    return len({name_key(exercise.name) for exercise in pool if regions_of(exercise) & counted})
