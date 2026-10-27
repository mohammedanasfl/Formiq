"""How a workout compares with a saved plan, and how long it takes: Formiq's own
rules, in one place.

The coach's tools describe a proposal's changes with them (get_pending_proposal,
get_workout_plan with a plan to compare with) and the API answers with the same
comparison (the proposal's `changes`), so what the coach is held to and what the
app shows are one implementation. Pure: it reads the plans and exercises it is
given and nothing else.
"""

import math
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any, NamedTuple

from app.schemas.coach import ExerciseChange, Prescription, ProposalChanges
from app.schemas.workout_plan import PlanSection
from app.tools import completeness
from app.tools.limits import DEFAULT_REST_SECONDS, SECONDS_PER_REP, SET_SECONDS
from app.tools.schemas import ExerciseChangeOutput, ProposedExerciseOutput, WorkoutChangesOutput

MAIN = PlanSection.MAIN_WORKOUT


class Row(NamedTuple):
    """What a workout prescribes for one of its exercises."""

    section: PlanSection
    name: str
    sets: int
    reps: int | None
    duration_seconds: int | None
    rest_seconds: int | None
    weight_kg: float | None


def plan_rows(plan: Any) -> list[Row]:
    """A saved plan's exercises as prescribed, in order."""
    return [
        Row(
            PlanSection(item.section),
            item.exercise.name if item.exercise is not None else f"exercise {item.exercise_id}",
            item.sets,
            item.reps,
            item.duration_seconds,
            item.rest_seconds,
            item.weight_kg,
        )
        for item in sorted(plan.exercises, key=lambda item: (item.exercise_order, item.id))
    ]


def proposed_rows(exercises: Iterable[ProposedExerciseOutput]) -> list[Row]:
    """A proposal's exercises as prescribed, in order, each with the weight the
    proposal gives it (a revision carries its plan's weights on, so none is lost
    unless the user asked)."""
    return [
        Row(
            item.section,
            item.exercise_name,
            item.sets,
            item.reps,
            item.duration_seconds,
            item.rest_seconds,
            item.weight_kg,
        )
        for item in exercises
    ]


def prescription(row: Row) -> str:
    """What a row prescribes, as "3 sets of 10 reps, 60 s rest"."""
    target = f"{row.reps} reps" if row.reps is not None else f"{row.duration_seconds} s"
    text = f"{row.sets} {'set' if row.sets == 1 else 'sets'} of {target}"
    if row.weight_kg is not None:
        text += f" at {row.weight_kg:g} kg"
    if row.rest_seconds:
        text += f", {row.rest_seconds} s rest"
    return text


def prescription_of(row: Row) -> Prescription:
    """What a row prescribes, as its numbers and as one line."""
    return Prescription(
        sets=row.sets,
        reps=row.reps,
        duration_seconds=row.duration_seconds,
        rest_seconds=row.rest_seconds,
        weight_kg=None if row.weight_kg is None else float(row.weight_kg),
        summary=prescription(row),
    )


def compare_workouts(
    rows: Sequence[Row], name: str, scheduled_date: date | None, plan: Any
) -> ProposalChanges:
    """How a workout (its rows, name and date) differs from a saved plan: each
    exercise matched by section and name, so nothing is said to differ that
    does not."""
    unmatched = plan_rows(plan)
    added, changed, unchanged = [], [], []
    for row in rows:
        same = next(
            (
                item
                for item in unmatched
                if item.section == row.section
                and completeness.name_key(item.name) == completeness.name_key(row.name)
            ),
            None,
        )
        if same is None:
            added.append(ExerciseChange(
                section=row.section, exercise_name=row.name, before=None, after=prescription_of(row)
            ))  # fmt: skip
            continue
        unmatched.remove(same)
        if prescription(same) == prescription(row):
            unchanged.append(row.name)
        else:
            changed.append(ExerciseChange(
                section=row.section, exercise_name=row.name, before=prescription_of(same),
                after=prescription_of(row),
            ))  # fmt: skip
    removed = [
        ExerciseChange(
            section=item.section, exercise_name=item.name, before=prescription_of(item), after=None
        )
        for item in unmatched
    ]
    return ProposalChanges(
        compared_with_plan_id=plan.id,
        compared_with_plan_name=plan.name,
        compared_with_scheduled_date=plan.scheduled_date,
        added=added,
        removed=removed,
        changed=changed,
        unchanged=unchanged,
        name_changed=name != plan.name,
        scheduled_date_changed=scheduled_date != plan.scheduled_date,
        identical=not (added or removed or changed),
    )


def tool_changes(changes: ProposalChanges) -> WorkoutChangesOutput:
    """The comparison as the coach's tools tell it: each prescription as one line."""

    def line(item: ExerciseChange) -> ExerciseChangeOutput:
        return ExerciseChangeOutput(
            section=item.section,
            exercise_name=item.exercise_name,
            before=None if item.before is None else item.before.summary,
            after=None if item.after is None else item.after.summary,
        )

    return WorkoutChangesOutput(
        compared_with_plan_id=changes.compared_with_plan_id,
        compared_with_plan_name=changes.compared_with_plan_name,
        added=[line(item) for item in changes.added],
        removed=[line(item) for item in changes.removed],
        changed=[line(item) for item in changes.changed],
        unchanged=changes.unchanged,
        name_changed=changes.name_changed,
        scheduled_date_changed=changes.scheduled_date_changed,
        identical=changes.identical,
    )


def workout_changes(
    rows: Sequence[Row], name: str, scheduled_date: date | None, plan: Any
) -> WorkoutChangesOutput:
    """compare_workouts() as the coach's tools tell it."""
    return tool_changes(compare_workouts(rows, name, scheduled_date, plan))


def section_minutes(exercises: Iterable[Any]) -> int:
    """How long a section's exercises take, roughly: each set and the rest
    after it. A timed set lasts its duration; a set of reps SET_SECONDS, or
    SECONDS_PER_REP a rep when its reps take longer. A main exercise without a
    rest gets the default; a warm-up or cool-down activity has none."""
    seconds = 0
    for item in exercises:
        rest = item.rest_seconds
        if rest is None:
            rest = DEFAULT_REST_SECONDS if item.section is MAIN else 0
        work = item.duration_seconds or max(SET_SECONDS, (item.reps or 0) * SECONDS_PER_REP)
        seconds += item.sets * (work + rest)
    return math.ceil(seconds / 60)


def workout_minutes(exercises: Iterable[Any]) -> dict[PlanSection, int]:
    """How long each section of a workout takes (section_minutes); their sum
    is the workout's estimate."""
    items = list(exercises)
    return {
        section: section_minutes(item for item in items if item.section is section)
        for section in PlanSection
    }


def plan_minutes(plan: Any) -> int:
    """How long a saved plan takes, by the formula that gives a proposal's
    estimated_minutes: the plan stores no length."""
    return sum(workout_minutes(plan_rows(plan)).values())
