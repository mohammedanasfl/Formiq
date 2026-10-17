"""The recovery summary of a completed workout session: what was done, the post-workout
nutrition, hydration and recovery guidance for it, and the cautions that apply.

The service only reads. It never commits, flushes or locks a row, so a summary can be
asked for as often as wanted and leaves every row as it was. The rules are pure
(app.guidance): this service gathers the recorded data, applies the rules in the safety
order below and maps what they return into the response (app.schemas.recovery_summary).

The safety order:

1. a reported warning sign needs medical care: only the calculated facts and one urgent
   notice are returned, and no estimate, hydration, food or recovery timing is worked out;
2. otherwise pain or an injury, severe soreness, a flagged note or a goal that loses weight
   too fast each add a caution; pain, an injury or a flagged note sends the muscles it
   covers to a professional, with no rest time;
3. otherwise the summary is complete.

The user's notes are the only free text. They are read once, by keywords, with the coach's
safety backstop (app.agent.safety), and never echoed: no field, notice or log carries a
note's text, only Formiq's own fixed wording.
"""

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.safety import MAX_WEEKLY_LOSS_KG, SafetyCategory, assess_safety
from app.guidance import foods, nutrition, recovery
from app.guidance.sources import GuidanceItem, cited_sources
from app.models import (
    Exercise,
    UserProfile,
    WorkoutPlanExercise,
    WorkoutSession,
    WorkoutSessionExercise,
    WorkoutSet,
)
from app.repositories import (
    ExerciseRepository,
    UserProfileRepository,
    WorkoutPlanExerciseRepository,
    WorkoutSessionRepository,
)
from app.schemas import (
    Allergen,
    CalculatedFacts,
    EstimateRange,
    Estimates,
    ExerciseStatus,
    ExerciseSummary,
    FoodItemOut,
    FoodSuggestions,
    Guidance,
    GuidanceNote,
    MissingData,
    MuscleRecoveryPlan,
    MuscleRole,
    MuscleTrained,
    ProfileValuesUsed,
    RecoveryGuidance,
    RecoverySummaryRequest,
    RecoverySummaryResponse,
    SafetyNotice,
    SafetySummary,
    SourceReference,
    WorkoutSection,
)
from app.services.exceptions import WorkoutSessionNotCompletedError
from app.services.workout_session_rules import COMPLETED, get_owned_session

# The longest note that is read: as long as a coach message (CoachMessageRequest.message).
# A longer note is not scanned, and the summary says so.
MAX_NOTE_LENGTH = 4000

# Formiq's own wording. A note's text is never part of any of it.
NOTES_FLAGGED_MESSAGE = (
    "A note on this workout mentions pain, an injury or a health concern. Formiq reads "
    "notes only by keywords and cannot judge them: if something hurts, stop exercises "
    "that load it and see a doctor or physiotherapist."
)
NOTES_DIET_FLAGGED_MESSAGE = (
    "A note on this workout mentions extreme dieting or weight loss. Formiq's targets here "
    "fuel training and are not a diet: please talk to a doctor or dietitian."
)
NOTE_TOO_LONG_MESSAGE = "A note on this workout was too long for Formiq to check."
GOAL_RATE_MESSAGE = (
    f"Your recorded goal needs losing more than {MAX_WEEKLY_LOSS_KG:g} kg a week, which "
    "Formiq treats as too fast: please talk to a doctor or dietitian. The ranges below "
    "only fuel training."
)
NOTE_MUSCLE_REASON = (
    "A note on this workout mentions pain, an injury or a health concern: "
    f"{recovery.PAIN_ADVICE}"
)
UNSIZED_REASON = (
    "Based on exercises logged without sets (for example timed ones), so how much work "
    "was done is unknown."
)
NO_COMPLETION_TIME_EFFECT = (
    "no completion time is recorded, so the time of the last update is used for rest "
    "windows and the session length is not given"
)
NO_PROFILE_EFFECT = (
    "no profile is recorded, so no per-kg or energy estimate is given and food examples "
    "are not filtered by diet"
)

# What a note found by the safety backstop is about: eating, or the body.
DIET_CATEGORIES = frozenset({SafetyCategory.EXTREME_DIETING, SafetyCategory.EXTREME_WEIGHT_LOSS})
# Exercises that were done: they are what rest windows, muscles and protein count.
COUNTED_STATUSES = frozenset({ExerciseStatus.TRAINED, ExerciseStatus.LOGGED_WITHOUT_SETS})
MAIN_WORKOUT = WorkoutSection.MAIN_WORKOUT
WARM_UP = WorkoutSection.WARM_UP
COOL_DOWN = WorkoutSection.COOL_DOWN

_TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class _Done:
    """A session exercise with its catalog exercise, and what was recorded for it."""

    summary: ExerciseSummary
    exercise: Exercise
    session_exercise: WorkoutSessionExercise
    # unrounded, so that a total is rounded once
    volume: Decimal | None

    @property
    def counted(self) -> bool:
        return self.summary.section is MAIN_WORKOUT and self.summary.status in COUNTED_STATUSES


@dataclass
class _Worked:
    """A muscle group worked in the counted exercises."""

    muscle: str
    role: MuscleRole
    completed_sets: int = 0
    exercises: list[str] = field(default_factory=list)
    # every counted exercise that works it was logged without sets
    only_unsized: bool = True


@dataclass
class _NoteFindings:
    """What the notes showed, without the notes themselves."""

    flagged: bool = False
    diet: bool = False
    too_long: bool = False
    muscles: set[str] = field(default_factory=set)

    def read(self, note: str | None, muscles: Iterable[str]) -> None:
        """Scans one note. muscles are the ones the note covers if it is flagged."""
        text = (note or "").strip()
        if not text:
            return
        if len(text) > MAX_NOTE_LENGTH:
            self.too_long = True
            return
        assessment = assess_safety(text)
        if not assessment.enforced:
            return
        if assessment.category in DIET_CATEGORIES:
            self.diet = True
        else:
            # any other category, including one added later, is treated as a health concern
            self.flagged = True
            self.muscles.update(muscles)


class RecoverySummaryService:
    """The recovery summary of one of a user's COMPLETED workout sessions.

    Read only: nothing is committed, flushed, locked or written. The clock is given, so
    the time since the workout, and with it a summary, is the same for the same clock; it
    must return a timezone-aware time, like the times the database gives."""

    def __init__(
        self,
        session: Session,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.session = session
        self.clock = clock
        self.sessions = WorkoutSessionRepository(session)
        self.profiles = UserProfileRepository(session)
        self.exercises = ExerciseRepository(session)
        self.plan_exercises = WorkoutPlanExerciseRepository(session)

    def build_summary(
        self, user_id: int, session_id: int, request: RecoverySummaryRequest
    ) -> RecoverySummaryResponse:
        """The summary for the user's session. A session that is another user's, or does
        not exist, is not found, and that is decided before its status is looked at."""
        workout_session = get_owned_session(self.sessions, user_id, session_id)
        if workout_session.status != COMPLETED:
            raise WorkoutSessionNotCompletedError(
                f"workout session {workout_session.id} is {workout_session.status}; "
                "only COMPLETED workout sessions have a recovery summary"
            )

        missing: list[MissingData] = []
        completed_at = workout_session.completed_at
        duration_minutes = None
        if completed_at is None:
            # data written outside the API: the last update is the best time there is
            completed_at = workout_session.updated_at
            missing.append(MissingData(field="completed_at", effect=NO_COMPLETION_TIME_EFFECT))
        else:
            duration_minutes = _duration_minutes(workout_session.started_at, completed_at)
        hours_since_completed = max(0.0, (self.clock() - completed_at).total_seconds() / 3600)

        profile = self.profiles.get_by_user_id(user_id)
        done = self._exercises_done(workout_session)
        counted = [item for item in done if item.counted]
        worked = _worked_muscles(counted)
        discomfort = [
            recovery.Discomfort(report.area, report.kind, report.severity)
            for report in request.discomfort
        ]
        calculated = _calculated_facts(profile, done, worked, duration_minutes)

        status = recovery.safety_status(request.warning_signs, discomfort)
        if recovery.withholds_guidance(status):
            # Nothing about food, fluid or rest timing is worked out: with a warning sign
            # that advice is medical.
            safety = SafetySummary(
                status=status.value,
                notices=[_notice(recovery.urgent_care_notice(request.warning_signs))],
            )
            return RecoverySummaryResponse(
                session_id=workout_session.id,
                completed_at=completed_at,
                hours_since_completed=hours_since_completed,
                safety=safety,
                calculated=calculated,
                estimates=Estimates(),
                guidance=Guidance(),
                missing_data=[],
                sources=_sources(safety),
            )

        cautions, flagged_muscles = _cautions(workout_session, done, worked, profile)
        status = recovery.safety_status(
            request.warning_signs, discomfort, other_cautions=bool(cautions)
        )
        plans = _recovery_plans(worked, discomfort, completed_at, flagged_muscles)
        safety = SafetySummary(
            status=status.value,
            notices=[
                *(_notice(item) for item in recovery.discomfort_notices(discomfort)),
                *cautions,
            ],
        )

        if profile is None:
            estimates = Estimates()
            missing.append(MissingData(field="profile", effect=NO_PROFILE_EFFECT))
        else:
            estimates, withheld = _estimates(
                profile,
                counted=len(counted),
                duration_minutes=duration_minutes,
                hours_since_completed=hours_since_completed,
            )
            missing.extend(entry for entry in withheld if entry not in missing)
        suggestions = foods.suggest_foods(
            profile.dietary_preference if profile else None, request.avoid_allergens
        )
        sleep = recovery.sleep_item(profile.sleep_hours) if profile else None
        guidance = Guidance(
            post_workout_carbohydrate=[
                _note(item) for item in nutrition.post_workout_carbohydrate_items()
            ],
            hydration=[_note(item) for item in nutrition.hydration_items()],
            sleep=_note(sleep) if sleep is not None else None,
            recovery=RecoveryGuidance(
                muscles=[_muscle_plan(plan) for plan in plans],
                general=[_note(item) for item in recovery.general_recovery_items()],
            ),
            food_suggestions=_food_suggestions(suggestions),
        )
        return RecoverySummaryResponse(
            session_id=workout_session.id,
            completed_at=completed_at,
            hours_since_completed=hours_since_completed,
            safety=safety,
            calculated=calculated,
            estimates=estimates,
            guidance=guidance,
            missing_data=missing,
            # the food examples' own sources are not in the schema's food suggestions
            sources=_sources(safety, estimates, guidance, extra=suggestions.source_ids),
        )

    def _exercises_done(self, workout_session: WorkoutSession) -> list[_Done]:
        """The session's exercises in order, with their catalog exercises and sections,
        loaded in batches."""
        session_exercises = sorted(workout_session.exercises, key=lambda item: item.exercise_order)
        catalog = {
            exercise.id: exercise
            for exercise in self.exercises.find_by_ids(
                {item.exercise_id for item in session_exercises}
            )
        }
        planned = {
            plan_exercise.id: plan_exercise
            for plan_exercise in self.plan_exercises.find_by_ids(
                {
                    item.plan_exercise_id
                    for item in session_exercises
                    if item.plan_exercise_id is not None
                }
            )
        }
        return [
            _done(item, catalog[item.exercise_id], planned.get(item.plan_exercise_id))
            for item in session_exercises
        ]


def _duration_minutes(started_at: datetime, completed_at: datetime) -> float | None:
    """The minutes from start to completion, to two decimals; None if they are out of order."""
    seconds = (completed_at - started_at).total_seconds()
    if seconds < 0:
        return None
    return _two_places(Decimal(str(seconds)) / 60)


def _two_places(value: Decimal | None) -> float | None:
    """A float to two decimals, with .005 rounded up; None stays None."""
    if value is None:
        return None
    return float(value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))


def _section(exercise: Exercise, plan_exercise: WorkoutPlanExercise | None) -> WorkoutSection:
    """The section the exercise was done in: its plan exercise's, else the one its uses
    allow. An exercise Formiq has not classified, or that suits the main workout, is main work."""
    if plan_exercise is not None:
        return WorkoutSection(plan_exercise.section)
    if not exercise.uses or MAIN_WORKOUT in exercise.uses:
        return MAIN_WORKOUT
    return WARM_UP if WARM_UP in exercise.uses else COOL_DOWN


def _volume(sets: Iterable[WorkoutSet]) -> Decimal | None:
    """reps x weight over the sets with a weight; None, never 0, when none has one."""
    weighted = [item for item in sets if item.weight_kg is not None]
    if not weighted:
        return None
    products = (Decimal(item.reps) * Decimal(str(item.weight_kg)) for item in weighted)
    return sum(products, Decimal(0))


def _average_rpe(sets: Iterable[WorkoutSet]) -> Decimal | None:
    rated = [Decimal(str(item.rpe)) for item in sets if item.rpe is not None]
    if not rated:
        return None
    return sum(rated, Decimal(0)) / len(rated)


def _done(
    session_exercise: WorkoutSessionExercise,
    exercise: Exercise,
    plan_exercise: WorkoutPlanExercise | None,
) -> _Done:
    sets = list(session_exercise.sets)
    completed = [item for item in sets if item.completed]
    if completed:
        status = ExerciseStatus.TRAINED
    elif sets:
        status = ExerciseStatus.SKIPPED
    else:
        # a timed exercise has no sets
        status = ExerciseStatus.LOGGED_WITHOUT_SETS
    volume = _volume(completed)
    summary = ExerciseSummary(
        session_exercise_id=session_exercise.id,
        exercise_id=exercise.id,
        name=exercise.name,
        section=_section(exercise, plan_exercise),
        status=status,
        sets_logged=len(sets),
        completed_sets=len(completed),
        total_reps=sum(item.reps for item in completed),
        volume_kg=_two_places(volume),
        average_rpe=_two_places(_average_rpe(completed)),
    )
    return _Done(summary, exercise, session_exercise, volume)


def _worked_muscles(counted: Iterable[_Done]) -> list[_Worked]:
    """The muscle groups of the counted exercises: a muscle is PRIMARY if it is primary in
    any of them. Primary muscles come first, each group in the order first seen."""
    worked: dict[str, _Worked] = {}
    for item in counted:
        for link in item.exercise.muscles:
            name = link.muscle_group.name
            role = MuscleRole(link.role)
            entry = worked.setdefault(name, _Worked(name, role))
            if role is MuscleRole.PRIMARY:
                entry.role = role
            entry.completed_sets += item.summary.completed_sets
            if item.summary.name not in entry.exercises:
                entry.exercises.append(item.summary.name)
            if item.summary.status is not ExerciseStatus.LOGGED_WITHOUT_SETS:
                entry.only_unsized = False
    # sorted is stable, so the order first seen is kept within each role
    return sorted(worked.values(), key=lambda entry: entry.role is not MuscleRole.PRIMARY)


def _calculated_facts(
    profile: UserProfile | None,
    done: Sequence[_Done],
    worked: Sequence[_Worked],
    duration_minutes: float | None,
) -> CalculatedFacts:
    volumes = [item.volume for item in done if item.volume is not None]
    return CalculatedFacts(
        duration_minutes=duration_minutes,
        duration_plausible=nutrition.duration_is_plausible(duration_minutes),
        exercises=[item.summary for item in done],
        completed_sets=sum(item.summary.completed_sets for item in done),
        total_reps=sum(item.summary.total_reps for item in done),
        volume_kg=_two_places(sum(volumes, Decimal(0))) if volumes else None,
        muscles_trained=[
            MuscleTrained(
                muscle=entry.muscle,
                role=entry.role,
                completed_sets=entry.completed_sets,
                exercises=entry.exercises,
            )
            for entry in worked
        ],
        profile_values_used=_values_used(profile) if profile else None,
    )


def _values_used(profile: UserProfile) -> ProfileValuesUsed:
    """The recorded values the rules saw; the estimates' own gates say which they accepted."""
    return ProfileValuesUsed(
        weight_kg=profile.weight_kg,
        age=profile.age,
        bmi=nutrition.bmi(profile.weight_kg, profile.height_cm),
        goal=profile.goal,
        goal_category=nutrition.normalise_goal(profile.goal).value,
        dietary_preference=profile.dietary_preference,
        sleep_hours=profile.sleep_hours,
    )


def _primary_muscles(exercise: Exercise) -> list[str]:
    return [link.muscle_group.name for link in exercise.muscles if link.role == MuscleRole.PRIMARY]


def _goal_too_fast(profile: UserProfile) -> bool:
    """Whether the recorded goal loses more than MAX_WEEKLY_LOSS_KG a week. A period under
    one week counts as one week, as in the coach's safety backstop."""
    if profile.target_weight_kg is None or profile.goal_period_weeks is None:
        return False
    weight = Decimal(str(profile.weight_kg))
    target = Decimal(str(profile.target_weight_kg))
    if target >= weight:
        return False
    return (weight - target) / max(profile.goal_period_weeks, 1) > Decimal(str(MAX_WEEKLY_LOSS_KG))


def _cautions(
    workout_session: WorkoutSession,
    done: Sequence[_Done],
    worked: Sequence[_Worked],
    profile: UserProfile | None,
) -> tuple[list[SafetyNotice], set[str]]:
    """The notices that the notes and the goal add, and the muscles a flagged note covers.
    A note on the session covers every counted muscle, since it cannot say where: that is
    over-cautious on purpose. A note on an exercise or a set covers that exercise's primary
    muscles."""
    findings = _NoteFindings()
    findings.read(workout_session.notes, (entry.muscle for entry in worked))
    for item in done:
        primary = _primary_muscles(item.exercise)
        findings.read(item.session_exercise.notes, primary)
        for workout_set in item.session_exercise.sets:
            findings.read(workout_set.notes, primary)

    notices = []
    if findings.flagged:
        notices.append(_fixed_notice("NOTES_FLAGGED", NOTES_FLAGGED_MESSAGE))
    if findings.diet:
        notices.append(_fixed_notice("NOTES_DIET_FLAGGED", NOTES_DIET_FLAGGED_MESSAGE))
    if findings.too_long:
        notices.append(_fixed_notice("NOTE_TOO_LONG_TO_CHECK", NOTE_TOO_LONG_MESSAGE))
    if profile is not None and _goal_too_fast(profile):
        notices.append(_fixed_notice("GOAL_RATE_TOO_FAST", GOAL_RATE_MESSAGE))
    return notices, findings.muscles


def _recovery_plans(
    worked: Sequence[_Worked],
    discomfort: Sequence[recovery.Discomfort],
    completed_at: datetime,
    flagged_muscles: set[str],
) -> tuple[recovery.MuscleRecovery, ...]:
    plans = recovery.muscle_recovery(
        [recovery.TrainedMuscle(entry.muscle, entry.role) for entry in worked],
        discomfort,
        completed_at,
    )
    unsized = {entry.muscle for entry in worked if entry.only_unsized}
    plans = tuple(
        replace(plan, reasons=(*plan.reasons, UNSIZED_REASON)) if plan.muscle in unsized else plan
        for plan in plans
    )
    if flagged_muscles:
        plans = recovery.flag_for_professional(plans, flagged_muscles, NOTE_MUSCLE_REASON)
    return plans


def _estimates(
    profile: UserProfile,
    *,
    counted: int,
    duration_minutes: float | None,
    hours_since_completed: float,
) -> tuple[Estimates, list[MissingData]]:
    """Each estimate the rules give, and for each they withhold what is missing."""
    values = nutrition.Profile(profile.weight_kg, profile.age, profile.height_cm, profile.goal)
    results = {
        "post_workout_protein_g": nutrition.post_workout_protein(
            values, counted_exercises=counted, hours_since_completed=hours_since_completed
        ),
        "daily_protein_g": nutrition.daily_protein(values),
        "daily_carbohydrate_g": nutrition.daily_carbohydrate(
            values, duration_minutes=duration_minutes
        ),
        "rapid_refuel_carbohydrate_g_per_hour": nutrition.rapid_refuel(
            values,
            duration_minutes=duration_minutes,
            hours_since_completed=hours_since_completed,
        ),
        "active_energy_kcal": nutrition.active_energy(values, duration_minutes=duration_minutes),
    }
    ranges: dict[str, EstimateRange] = {}
    missing: list[MissingData] = []
    for name, result in results.items():
        if isinstance(result, nutrition.Withheld):
            entry = MissingData(field=result.field, effect=result.effect)
            if entry not in missing:
                missing.append(entry)
        else:
            ranges[name] = EstimateRange(
                low=result.low,
                high=result.high,
                unit=result.unit,
                basis=result.basis,
                applies_if=result.applies_if,
                assumptions=list(result.assumptions),
                source_ids=[str(source_id) for source_id in result.source_ids],
            )
    return Estimates(**ranges), missing


def _fixed_notice(code: str, message: str) -> SafetyNotice:
    """A caution with Formiq's own wording and no published source: its limits are product
    guardrails."""
    return SafetyNotice(code=code, message=message, source_ids=[])


def _notice(item: GuidanceItem) -> SafetyNotice:
    return SafetyNotice(
        code=item.code,
        message=item.text,
        source_ids=[str(source_id) for source_id in item.source_ids],
    )


def _note(item: GuidanceItem) -> GuidanceNote:
    return GuidanceNote(
        code=item.code,
        text=item.text,
        source_ids=[str(source_id) for source_id in item.source_ids],
    )


def _muscle_plan(plan: recovery.MuscleRecovery) -> MuscleRecoveryPlan:
    return MuscleRecoveryPlan(
        muscle=plan.muscle,
        role=plan.role,
        status=plan.status.value,
        rest_hours=plan.rest_hours,
        rest_until=plan.rest_until,
        reasons=list(plan.reasons),
        source_ids=[str(source_id) for source_id in plan.source_ids],
    )


def _food_suggestions(suggestions: foods.FoodSuggestions) -> FoodSuggestions:
    diet = suggestions.dietary_pattern
    return FoodSuggestions(
        preference_status=suggestions.preference_status.value,
        dietary_pattern=diet.value if diet is not None else None,
        allergens_excluded=list(suggestions.allergens_excluded),
        items=[
            FoodItemOut(
                name=food.name,
                serving=food.serving,
                protein_g=food.protein_g,
                carbohydrate_g=food.carbohydrate_g,
                suits=[pattern.value for pattern in foods.suits(food)],
                contains=[
                    source.value for source in foods.AnimalSource if source in food.contains
                ],
                allergens=[allergen for allergen in Allergen if allergen in food.allergens],
                source_id=str(food.source_id),
            )
            for food in suggestions.items
        ],
        caveats=list(suggestions.caveats),
    )


def _cited_ids(value: Any) -> Iterator[str]:
    """Every source id a dumped response cites, in any source_ids or source_id field, so a
    field added later cannot be left out of the sources."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "source_ids":
                yield from item
            elif key == "source_id":
                yield item
            else:
                yield from _cited_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _cited_ids(item)


def _sources(*parts: BaseModel, extra: Iterable[str] = ()) -> list[SourceReference]:
    """The sources cited by the given parts of the response and by extra, once each."""
    ids = [source_id for part in parts for source_id in _cited_ids(part.model_dump(mode="json"))]
    return [
        SourceReference(id=str(source.id), citation=source.citation, url=source.url)
        for source in cited_sources([*ids, *extra])
    ]
