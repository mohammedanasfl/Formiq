"""A stored workout proposal read back as the user was shown it.

The coach reads the proposal awaiting approval (get_pending_proposal) and the
API lists it (GET /coach/proposals/pending) from the same stored values, so
both are built here: its exercises with the catalog's names and equipment, its
minutes, its coverage as judged again, and, for a revision, the saved plan it
replaces, how the proposal differs from that plan (app.tools.comparison) and
how long that plan takes. Reads only, through the services it is given.
"""

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from app.schemas.coach import (
    CoverageLimitation,
    ProposalChanges,
    ProposalCoverage,
    ProposalRevision,
    SessionFocus,
)
from app.schemas.workout_plan import PlanSection, WorkoutPlanStatus
from app.tools import completeness
from app.tools.comparison import (
    compare_workouts,
    plan_minutes,
    plan_rows,
    proposed_rows,
    workout_minutes,
)
from app.tools.completeness import REGION_NAMES, movers
from app.tools.limits import clip
from app.tools.schemas import ProposedExerciseOutput

if TYPE_CHECKING:
    # Only for type hints: the caller gives the services, so this package
    # imports no services (or anything below them) when it runs.
    from app.services import ExerciseCatalogService, WorkoutPlanService

MAIN = PlanSection.MAIN_WORKOUT


@dataclass(frozen=True)
class ReplacedPlan:
    """The saved plan a proposal replaces, as it is now, and the proposal against it."""

    plan: Any
    # still PLANNED and as it was when proposed: if not, approving the proposal fails
    unchanged: bool
    # null for a proposal stored before Formiq recorded how it revises a plan
    revision: ProposalRevision | None
    # the proposal against that plan
    changes: ProposalChanges
    # how long that plan takes, by the formula of a proposal's estimate
    minutes: int


@dataclass(frozen=True)
class StoredProposalView:
    name: str
    scheduled_date: date
    exercises: list[ProposedExerciseOutput]
    # whether every exercise is still an active catalog exercise: if not, approving fails
    exercises_available: bool
    minutes: dict[PlanSection, int]
    # null for a proposal made before Formiq recorded what it is for
    coverage: ProposalCoverage | None
    # the plan it replaces, when it revises one the user still has
    replaces_plan_id: int | None
    replaced: ReplacedPlan | None


class ProposalViewBuilder:
    """Builds the views from the catalog and plan services it is given."""

    def __init__(self, catalog: "ExerciseCatalogService", plans: "WorkoutPlanService") -> None:
        self.catalog = catalog
        self.plans = plans

    def stored(self, user_id: int, values: dict[str, Any]) -> StoredProposalView:
        """The proposal that was stored with these values, for its user."""
        exercises, available = self.exercises(values)
        name = values["name"]
        scheduled = date.fromisoformat(values["scheduled_date"])
        coverage = None
        if (focus := values.get("focus")) is not None:
            coverage = self.coverage(
                SessionFocus(focus),
                [item for item in exercises if item.section is MAIN],
                values.get("max_minutes"),
            )
        return StoredProposalView(
            name=name,
            scheduled_date=scheduled,
            exercises=exercises,
            exercises_available=available,
            minutes=workout_minutes(exercises),
            coverage=coverage,
            replaces_plan_id=values.get("replaces_plan_id"),
            replaced=self.replaced(
                user_id, values, name=name, scheduled_date=scheduled, exercises=exercises
            ),
        )

    def exercises(self, values: dict[str, Any]) -> tuple[list[ProposedExerciseOutput], bool]:
        """The proposal's exercises as stored, in order, with the catalog's
        names and equipment, and whether each is still an active exercise."""
        shown = []
        available = True
        for kept in sorted(values["exercises"], key=lambda item: item["exercise_order"]):
            exercise = self.catalog.get_exercise_by_id(kept["exercise_id"])
            available &= exercise is not None and exercise.is_active
            shown.append(
                ProposedExerciseOutput(
                    exercise_order=kept["exercise_order"],
                    section=kept["section"],
                    exercise_id=kept["exercise_id"],
                    exercise_name=exercise.name
                    if exercise is not None
                    else f"exercise {kept['exercise_id']}",
                    equipment=[]
                    if exercise is None
                    else [item.name for item in exercise.equipment],
                    sets=kept["sets"],
                    reps=kept.get("reps"),
                    duration_seconds=kept.get("duration_seconds"),
                    rest_seconds=kept.get("rest_seconds"),
                    weight_kg=kept.get("weight_kg"),
                    notes=clip(kept.get("notes")),
                )
            )
        return shown, available

    def replaced(
        self,
        user_id: int,
        values: dict[str, Any],
        *,
        name: str,
        scheduled_date: date,
        exercises: list[ProposedExerciseOutput],
    ) -> ReplacedPlan | None:
        """The plan the proposal replaces, when it revises one the user still
        has; None when it revises none, or the plan cannot be found for them."""
        replaced_id = values.get("replaces_plan_id")
        if replaced_id is None:
            return None
        plan = self.plans.get_plan(user_id, replaced_id)
        if plan is None:
            return None
        unchanged = plan.status == WorkoutPlanStatus.PLANNED and self.plans.version_of(
            plan
        ) == values.get("replaces_plan_digest")
        revision = None
        if values.get("revision") is not None:
            before = {
                completeness.name_key(row.name) for row in plan_rows(plan) if row.section is MAIN
            }
            revision = ProposalRevision(
                replaces_plan_id=plan.id,
                replaces_plan_name=plan.name,
                kind=values["revision"],
                kept_exercises=[
                    item.exercise_name
                    for item in exercises
                    if item.section is MAIN and completeness.name_key(item.exercise_name) in before
                ],
            )
        return ReplacedPlan(
            plan=plan,
            unchanged=unchanged,
            revision=revision,
            changes=compare_workouts(proposed_rows(exercises), name, scheduled_date, plan),
            minutes=plan_minutes(plan),
        )

    def coverage(
        self, focus: SessionFocus, main: list[ProposedExerciseOutput], max_minutes: int | None
    ) -> ProposalCoverage:
        """A stored proposal's coverage, judged again from what it prescribes.
        Formiq accepted it, so whatever it misses, the catalog had nothing the
        user could do for when it was proposed."""
        catalog = [self.catalog.get_exercise_by_id(item.exercise_id) for item in main]
        assessment = completeness.assess(
            focus,
            [
                (exercise, item.sets)
                for exercise, item in zip(catalog, main, strict=True)
                if exercise is not None
            ],
            max_minutes,
        )
        limitations = [
            CoverageLimitation(
                code="NO_SUITABLE_EXERCISE",
                region=region,
                message=(
                    f"Formiq's catalog had no {REGION_NAMES[region]} exercise (with "
                    f"{movers(region)} as a primary muscle) that suited the user's equipment and "
                    "experience when this was proposed, so this workout does not train it."
                ),
            )
            for region in completeness.in_order(assessment.missing)
        ]
        if assessment.counted < assessment.required:
            limitations.append(
                CoverageLimitation(
                    code="TOO_FEW_SUITABLE_EXERCISES",
                    region=None,
                    message=(
                        f"It has {assessment.counted} exercises that count for a {focus} "
                        f"workout, fewer than the {assessment.required} it needs: the catalog "
                        "had no more that suited the user when this was proposed."
                    ),
                )
            )
        return ProposalCoverage(
            complete=not limitations,
            focus=focus,
            trained_regions=completeness.in_order(assessment.trained),
            missing_regions=completeness.in_order(assessment.missing),
            main_exercises_counted=assessment.counted,
            main_exercises_required=assessment.required,
            limitations=limitations,
        )
