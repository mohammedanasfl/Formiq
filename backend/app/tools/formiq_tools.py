"""The coach's tools.

Each tool is an adapter around the existing services: it reads through them,
never through repositories or the database, and turns what they return into a
compact output for the model. No tool writes: propose_workout_plan only
builds a proposal. The coach service keeps the one it shows the user, and only
the user's own approval of it may later save the plan
(app.services.plan_proposal_service).
"""

import logging
import math
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from app.agent.safety import SAFE
from app.ai import ToolCall
from app.approvals import (
    PROPOSAL_ACTIONS,
    ProposalDraft,
    ProposalTerms,
    SafetyBlocked,
    WriteProposal,
    propose,
)
from app.schemas.coach import CoverageLimitation, ProposalCoverage
from app.schemas.exercise import (
    Difficulty,
    ExerciseFilters,
    MovementPattern,
    MuscleRole,
    WorkoutSection,
)
from app.schemas.workout_plan import PlanSection
from app.tools import completeness
from app.tools.completeness import FOCUS_RULES, REGION_MUSCLES, REGION_NAMES
from app.tools.declarations import TOOL_DECLARATIONS
from app.tools.errors import ToolError, ToolErrorCode
from app.tools.limits import (
    DEFAULT_REST_SECONDS,
    MAX_EXECUTED_TOOL_CALLS_PER_TURN,
    MAX_EXERCISES,
    MAX_INSTRUCTION_STEPS,
    MAX_PROPOSAL_DAYS_AHEAD,
    MAX_SEARCH_RESULTS,
    MAX_SECTION_MINUTES,
    MAX_SETS,
    MAX_TEXT_LENGTH,
    MIN_COUNTED_SETS,
    SECONDS_PER_REP,
    SET_SECONDS,
)
from app.tools.schemas import (
    CurrentWorkoutPlanOutput,
    ExerciseOutput,
    ExerciseSummaryOutput,
    GetCurrentWorkoutPlanInput,
    GetExerciseInput,
    GetLatestWorkoutSessionInput,
    GetUserProfileInput,
    GetWorkoutPlanInput,
    GetWorkoutSessionInput,
    LatestWorkoutSessionOutput,
    MuscleOutput,
    PlanExerciseOutput,
    ProfileOutput,
    ProposedActivityInput,
    ProposedExerciseInput,
    ProposedExerciseOutput,
    ProposedWorkoutPlanOutput,
    ProposeWorkoutPlanInput,
    SearchExercisesInput,
    SearchExercisesOutput,
    SessionExerciseOutput,
    UserProfileOutput,
    UserScopedInput,
    WorkoutPlanOutput,
    WorkoutSessionOutput,
    WorkoutSetOutput,
)

if TYPE_CHECKING:
    # Only for type hints: the tools get service instances from CoachService, so
    # this package imports no services (or anything below them) when it runs.
    from app.services import (
        ExerciseCatalogService,
        UserProfileService,
        UserService,
        WorkoutPlanService,
        WorkoutSessionService,
    )

logger = logging.getLogger(__name__)


def clip(text: str | None) -> str | None:
    """The text, cut to MAX_TEXT_LENGTH characters."""
    if text is None or len(text) <= MAX_TEXT_LENGTH:
        return text
    return text[: MAX_TEXT_LENGTH - 1] + "…"


def error_result(code: ToolErrorCode, message: str) -> dict[str, Any]:
    return {"error": {"code": code.value, "message": message}}


def utc_today() -> date:
    """Formiq's date: today in UTC. The user's own time zone is not known."""
    return datetime.now(UTC).date()


WARM_UP = PlanSection.WARM_UP
MAIN = PlanSection.MAIN_WORKOUT
COOL_DOWN = PlanSection.COOL_DOWN

# Each section of a proposed plan holds catalog exercises whose uses (Formiq's
# classification) include it: the main workout trains, the warm-up prepares and
# the cool-down recovers. Warm-up and cool-down activities are light (BEGINNER),
# and work a muscle the main exercises train, unless they are easy CARDIO,
# which suits any workout.
GENERAL_ACTIVITIES = frozenset({MovementPattern.CARDIO})
SECTION_NAMES = {WARM_UP: "warm-up", MAIN: "main workout", COOL_DOWN: "cool-down"}

# What the model may write for training with no equipment at all, as
# equipment_key() has it ("body only" is free-exercise-db's own name for it).
# None of them is a piece of the catalog's equipment: an exercise that needs
# none is what a search with available_equipment [] finds.
NO_EQUIPMENT = frozenset({"body weight", "bodyweight", "body only", "no equipment", "none"})


class FormiqTools:
    """Runs the model's tool calls for one coach request.

    User-scoped tools read only the data of the user given to run(), which
    comes from the coach request: the model cannot name another user. The
    current plan and the last workout are found relative to today, the
    request's date unless one is given.

    Proposed plans are kept in proposals for the coach's reply, made on
    proposal_terms (Formiq's clock and how long a proposal waits); without
    them, no plan can be proposed. Nothing is stored here: the coach service
    keeps the proposal it shows the user.
    """

    declarations = TOOL_DECLARATIONS

    def __init__(
        self,
        *,
        users: "UserService",
        profiles: "UserProfileService",
        plans: "WorkoutPlanService",
        sessions: "WorkoutSessionService",
        catalog: "ExerciseCatalogService",
        end_read: Callable[[], None],
        today: date | None = None,
        proposal_terms: ProposalTerms | None = None,
    ) -> None:
        self.users = users
        self.profiles = profiles
        self.plans = plans
        self.sessions = sessions
        self.catalog = catalog
        self.today = today if today is not None else utc_today()
        self.proposal_terms = proposal_terms
        # the main exercises this request's searches returned, by id, with the
        # muscles they train: what a warm-up or cool-down search says each
        # activity suits (suited_main)
        self.main_candidates: dict[int, frozenset[str]] = {}
        # the plans proposed in this request, in order, with what the model was told
        self.proposals: list[tuple[WriteProposal, ProposedWorkoutPlanOutput]] = []
        # Called after each batch of calls to end the read transaction, so no
        # database connection is held while the model answers.
        self.end_read = end_read
        self._tools: dict[str, tuple[type[BaseModel], Callable[[Any], BaseModel]]] = {
            "get_user_profile": (GetUserProfileInput, self.get_user_profile),
            "get_workout_plan": (GetWorkoutPlanInput, self.get_workout_plan),
            "get_workout_session": (GetWorkoutSessionInput, self.get_workout_session),
            "get_current_workout_plan": (GetCurrentWorkoutPlanInput, self.get_current_workout_plan),
            "get_latest_workout_session": (
                GetLatestWorkoutSessionInput,
                self.get_latest_workout_session,
            ),
            "propose_workout_plan": (ProposeWorkoutPlanInput, self.propose_workout_plan),
            "get_exercise": (GetExerciseInput, self.get_exercise),
            "search_exercises": (SearchExercisesInput, self.search_exercises),
        }

    def run(self, calls: Sequence[ToolCall], *, user_id: int) -> list[dict[str, Any]]:
        """One result per call, in order: {"output": ...} or {"error": {"code",
        "message"}}. Only the first MAX_EXECUTED_TOOL_CALLS_PER_TURN calls are run:
        the searches for main exercises among them first, so that the turn's
        warm-up and cool-down searches can say which of those each activity
        suits."""
        runnable = calls[:MAX_EXECUTED_TOOL_CALLS_PER_TURN]
        order = sorted(range(len(runnable)), key=lambda index: not searches_main(runnable[index]))
        try:
            results = {index: self._run_call(runnable[index], user_id) for index in order}
            return [
                results[index]
                if index < MAX_EXECUTED_TOOL_CALLS_PER_TURN
                else error_result(
                    ToolErrorCode.TOOL_LIMIT_REACHED,
                    f"only {MAX_EXECUTED_TOOL_CALLS_PER_TURN} tool calls are run per turn; "
                    "this one was not",
                )
                for index in range(len(calls))
            ]
        finally:
            self.end_read()

    def _run_call(self, call: ToolCall, user_id: int) -> dict[str, Any]:
        tool = self._tools.get(call.name)
        if tool is None:
            return error_result(ToolErrorCode.UNKNOWN_TOOL, "there is no tool with this name")
        input_model, function = tool
        if "user_id" in call.arguments:
            return error_result(
                ToolErrorCode.INVALID_INPUT,
                "user_id is not an argument: Formiq always uses the current user",
            )
        arguments = dict(call.arguments)
        if issubclass(input_model, UserScopedInput):
            arguments["user_id"] = user_id

        try:
            request = input_model.model_validate(arguments)
        except ValidationError as error:
            return error_result(ToolErrorCode.INVALID_INPUT, describe(error))
        try:
            output = function(request)
        except ToolError as error:
            return error_result(error.code, error.message)
        except Exception:
            # The cause, such as a database error, goes to the server log only.
            logger.exception("Coach tool %s failed", call.name)
            # A database error aborts the read transaction, and every later
            # query in it would fail too: end it, so the turn's other calls read
            # as if this one had not run.
            self.end_read()
            return error_result(ToolErrorCode.TOOL_ERROR, "the data could not be read")
        return {"output": output.model_dump(mode="json")}

    def get_user_profile(self, request: GetUserProfileInput) -> UserProfileOutput:
        if self.users.get_user_by_id(request.user_id) is None:
            raise ToolError(ToolErrorCode.USER_NOT_FOUND, "the user does not exist")
        profile = self.profiles.get_profile_by_user_id(request.user_id)
        if profile is None:
            raise ToolError(
                ToolErrorCode.PROFILE_NOT_FOUND, "the user has not created a fitness profile"
            )
        return UserProfileOutput(
            user_id=request.user_id, profile=ProfileOutput.model_validate(profile)
        )

    def get_workout_plan(self, request: GetWorkoutPlanInput) -> WorkoutPlanOutput:
        # None also for another user's plan, which is not told apart from a missing one
        plan = self.plans.get_plan(request.user_id, request.plan_id)
        if plan is None:
            raise ToolError(
                ToolErrorCode.RESOURCE_NOT_FOUND,
                f"the user has no workout plan {request.plan_id}",
            )
        return self._plan_output(plan)

    def get_current_workout_plan(
        self, request: GetCurrentWorkoutPlanInput
    ) -> CurrentWorkoutPlanOutput:
        plan = self.plans.get_current_plan(request.user_id, self.today)
        if plan is None:
            raise ToolError(
                ToolErrorCode.RESOURCE_NOT_FOUND,
                "the user has no current workout plan (no PLANNED plan); there is no id to ask for",
            )
        return self._plan_output(
            plan,
            CurrentWorkoutPlanOutput,
            today=self.today,
            days_from_today=(plan.scheduled_date - self.today).days
            if plan.scheduled_date is not None
            else None,
        )

    def _plan_output(
        self, plan: Any, output: type[WorkoutPlanOutput] = WorkoutPlanOutput, **fields: Any
    ) -> WorkoutPlanOutput:
        items = plan.exercises[:MAX_EXERCISES]
        names = self._exercise_names(item.exercise_id for item in items)
        return output(
            **fields,
            plan_id=plan.id,
            name=plan.name,
            status=plan.status,
            scheduled_date=plan.scheduled_date,
            exercises=[
                PlanExerciseOutput(
                    exercise_id=item.exercise_id,
                    exercise_name=names.get(item.exercise_id),
                    exercise_order=item.exercise_order,
                    section=item.section,
                    sets=item.sets,
                    reps=item.reps,
                    duration_seconds=item.duration_seconds,
                    weight_kg=item.weight_kg,
                    rest_seconds=item.rest_seconds,
                    notes=clip(item.notes),
                )
                for item in items
            ],
            truncated=len(plan.exercises) > MAX_EXERCISES,
        )

    def get_workout_session(self, request: GetWorkoutSessionInput) -> WorkoutSessionOutput:
        # None also for another user's session, which is not told apart from a missing one
        workout_session = self.sessions.get_session(request.user_id, request.session_id)
        if workout_session is None:
            raise ToolError(
                ToolErrorCode.RESOURCE_NOT_FOUND,
                f"the user has no workout session {request.session_id}",
            )
        return self._session_output(workout_session)

    def get_latest_workout_session(
        self, request: GetLatestWorkoutSessionInput
    ) -> LatestWorkoutSessionOutput:
        workout_session = self.sessions.get_latest_completed_session(request.user_id)
        if workout_session is None:
            raise ToolError(
                ToolErrorCode.RESOURCE_NOT_FOUND,
                "the user has no completed workout session yet; there is no id to ask for",
            )
        done = workout_session.completed_at or workout_session.started_at
        return self._session_output(
            workout_session,
            LatestWorkoutSessionOutput,
            today=self.today,
            days_ago=(self.today - done.astimezone(UTC).date()).days,
        )

    def _session_output(
        self,
        workout_session: Any,
        output: type[WorkoutSessionOutput] = WorkoutSessionOutput,
        **fields: Any,
    ) -> WorkoutSessionOutput:
        items = workout_session.exercises[:MAX_EXERCISES]
        names = self._exercise_names(item.exercise_id for item in items)
        return output(
            **fields,
            session_id=workout_session.id,
            workout_plan_id=workout_session.workout_plan_id,
            status=workout_session.status,
            started_at=workout_session.started_at,
            completed_at=workout_session.completed_at,
            notes=clip(workout_session.notes),
            exercises=[
                SessionExerciseOutput(
                    exercise_id=item.exercise_id,
                    exercise_name=names.get(item.exercise_id),
                    exercise_order=item.exercise_order,
                    sets=[
                        WorkoutSetOutput(
                            set_number=workout_set.set_number,
                            reps=workout_set.reps,
                            weight_kg=workout_set.weight_kg,
                            rpe=workout_set.rpe,
                            completed=workout_set.completed,
                        )
                        for workout_set in item.sets[:MAX_SETS]
                    ],
                )
                for item in items
            ],
            truncated=len(workout_session.exercises) > MAX_EXERCISES
            or any(len(item.sets) > MAX_SETS for item in items),
        )

    def propose_workout_plan(self, request: ProposeWorkoutPlanInput) -> ProposedWorkoutPlanOutput:
        """Makes the workout a proposal for the user to approve, once each of its
        sections is made of active catalog exercises that suit the section and
        the main workout, the main workout fulfils its focus (or the catalog
        leaves no choice, which the proposal then says), and the whole fits the
        date, the user's experience and their stated time and equipment. It
        saves nothing."""
        if self.proposal_terms is None:
            raise ToolError(ToolErrorCode.TOOL_ERROR, "a plan cannot be proposed here")
        scheduled = request.scheduled_date or self.today
        days = (scheduled - self.today).days
        if not 0 <= days <= MAX_PROPOSAL_DAYS_AHEAD:
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"scheduled_date must be today or up to {MAX_PROPOSAL_DAYS_AHEAD} days later",
            )
        unavailable = self._unavailable_equipment(
            request.unavailable_equipment
        ) | self._equipment_lacking(request.available_equipment)
        beginner = self._beginner(request.user_id)
        sections = (
            (WARM_UP, request.warm_up),
            (MAIN, request.exercises),
            (COOL_DOWN, request.cool_down),
        )
        found = {
            section: [
                self._proposed_exercise(item, section, unavailable, beginner) for item in items
            ]
            for section, items in sections
        }
        if repeats := repeated(found[MAIN]):
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"{'; '.join(repeats)}: list each main exercise once, and give it more sets "
                "for more work",
            )
        main = {exercise.id: muscles_of(exercise) for exercise in found[MAIN]}
        trained = set().union(*main.values())
        # every activity that does not fit, so one correction can fix them all
        misfits = [
            f"exercise {exercise.id} ({exercise.name}) works none of the muscles the main "
            f"exercises train, so it does not belong in this {SECTION_NAMES[section]}"
            for section in (WARM_UP, COOL_DOWN)
            for exercise in found[section]
            if not suited_main(exercise, main)
        ]
        if misfits:
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"{'; '.join(misfits)}: the main exercises train "
                f"{', '.join(sorted(trained)) or 'no listed muscle'}; choose activities that "
                "work one of them, or easy CARDIO",
            )

        # one order across the sections: the warm-up, then the main workout, then the cool-down
        chosen = [
            (section, item, exercise)
            for section, items in sections
            for item, exercise in zip(items, found[section], strict=True)
        ]
        exercises = [
            ProposedExerciseOutput(
                exercise_order=order,
                section=section,
                exercise_id=exercise.id,
                exercise_name=exercise.name,
                equipment=[equipment.name for equipment in exercise.equipment],
                sets=item.sets,
                reps=item.reps,
                duration_seconds=getattr(item, "duration_seconds", None),
                rest_seconds=getattr(item, "rest_seconds", None),
                notes=item.notes,
            )
            for order, (section, item, exercise) in enumerate(chosen, start=1)
        ]
        minutes = {
            section: section_minutes(item for item in exercises if item.section is section)
            for section in PlanSection
        }
        for section in (WARM_UP, COOL_DOWN):
            if minutes[section] > MAX_SECTION_MINUTES:
                raise ToolError(
                    ToolErrorCode.INVALID_INPUT,
                    f"the {SECTION_NAMES[section]} takes about {minutes[section]} minutes, more "
                    f"than {MAX_SECTION_MINUTES}: keep it light and short",
                )
        total = sum(minutes.values())
        if request.max_minutes is not None and total > request.max_minutes:
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"this plan takes about {total} minutes (warm-up {minutes[WARM_UP]}, main "
                f"{minutes[MAIN]}, cool-down {minutes[COOL_DOWN]}), more than the "
                f"{request.max_minutes} the user has: use fewer sets or exercises, shorter "
                "rests, or a shorter warm-up or cool-down",
            )
        # every way the workout falls short, so one correction can fix them all
        problems, coverage = self._coverage(request, found[MAIN], unavailable, beginner)
        if minutes[WARM_UP] < (least := completeness.minimum_warm_up_minutes(request.max_minutes)):
            problems.append(
                f"the warm-up takes about {minutes[WARM_UP]} minutes, less than {least}: make "
                "it longer, such as a longer bout of easy cardio, rather than add activities"
            )
        if total < (least := completeness.minimum_minutes(request.max_minutes)):
            problems.append(
                f"this plan takes about {total} minutes, less than half of the "
                f"{request.max_minutes} the user has: make it at least {least} minutes, with "
                "more sets or main exercises"
            )
        if problems:
            raise ToolError(ToolErrorCode.INVALID_INPUT, "; ".join(problems))

        draft = ProposalDraft(
            action=PROPOSAL_ACTIONS["propose_workout_plan"],
            parameters={
                "name": request.name,
                "scheduled_date": scheduled.isoformat(),
                # every section's exercises, so the binding covers the whole workout
                "exercises": [
                    item.model_dump(
                        mode="json", exclude={"exercise_name", "equipment"}, exclude_none=True
                    )
                    for item in exercises
                ],
            },
        )
        try:
            # tools run only for requests the safety backstop did not flag
            # (app.agent.graph); the proposal's own text is checked here
            proposal = propose(
                draft,
                trusted_user_id=request.user_id,
                request=SAFE,
                resource_version=None,
                now=self.proposal_terms.clock(),
                ttl=self.proposal_terms.ttl,
            )
        except SafetyBlocked:
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                "the proposal's name or notes raise a safety concern: leave that out",
            ) from None
        output = ProposedWorkoutPlanOutput(
            name=request.name,
            scheduled_date=scheduled,
            days_from_today=days,
            exercises=exercises,
            warm_up_minutes=minutes[WARM_UP],
            main_minutes=minutes[MAIN],
            cool_down_minutes=minutes[COOL_DOWN],
            estimated_minutes=total,
            coverage=coverage,
            expires_at=proposal.expires_at,
        )
        self.proposals.append((proposal, output))
        return output

    def _proposed_exercise(
        self,
        item: ProposedExerciseInput | ProposedActivityInput,
        section: PlanSection,
        unavailable: set[str],
        beginner: bool,
    ) -> Any:
        """The catalog exercise of a proposed plan's item, once it is active,
        needs nothing the user cannot use, Formiq uses it for the item's
        section, and it is not too hard for the user."""
        exercise = self.catalog.get_exercise_by_id(item.exercise_id)
        if exercise is None or not exercise.is_active:
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"exercise {item.exercise_id} is not an active Formiq catalog exercise",
            )
        equipment = [equipment.name for equipment in exercise.equipment]
        if needed := [name for name in equipment if equipment_key(name) in unavailable]:
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"exercise {item.exercise_id} needs {', '.join(needed)}, which the user "
                "cannot use: choose another exercise",
            )
        if section not in exercise.uses:
            uses = ", ".join(exercise.uses) or "none"
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"exercise {item.exercise_id} ({exercise.name}) is not a "
                f"{SECTION_NAMES[section]} exercise in Formiq's catalog (its uses: {uses}): "
                f"choose one whose uses include {section}",
            )
        if section is not MAIN and exercise.difficulty != Difficulty.BEGINNER:
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"exercise {item.exercise_id} ({exercise.name}) is not a light "
                f"{SECTION_NAMES[section]} activity: choose a BEGINNER one",
            )
        if beginner and exercise.difficulty == Difficulty.ADVANCED:
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"exercise {item.exercise_id} ({exercise.name}) is ADVANCED, too hard for a "
                "beginner: choose a BEGINNER or INTERMEDIATE one (search_exercises with "
                "difficulty BEGINNER finds them)",
            )
        return exercise

    def _beginner(self, user_id: int) -> bool:
        """Whether the user's profile says they are a beginner."""
        profile = self.profiles.get_profile_by_user_id(user_id)
        return profile is not None and completeness.is_beginner(profile.fitness_experience)

    def _coverage(
        self,
        request: ProposeWorkoutPlanInput,
        main: Sequence[Any],
        unavailable: set[str],
        beginner: bool,
    ) -> tuple[list[str], ProposalCoverage]:
        """How the main workout falls short of its focus where the catalog has
        what it needs (each a problem for the model to correct), and its
        coverage: where the catalog has nothing the user can do for it, the
        workout is incomplete, and each limitation says what is missing."""
        focus = request.focus
        assessment = completeness.assess(
            focus,
            [(exercise, item.sets) for exercise, item in zip(main, request.exercises, strict=True)],
            request.max_minutes,
        )
        problems = [
            f"exercise {exercise.id} ({exercise.name}) trains none of what a {focus} workout "
            f"trains ({regions_named(FOCUS_RULES[focus].allowed)}): choose another exercise, or "
            "another focus"
            for exercise in assessment.off_focus
        ]
        limitations = []
        # with no equipment said, every piece counts as usable
        unsaid = request.available_equipment is None and not request.unavailable_equipment
        lacking = (
            ", or, if the user does not have the equipment it needs, give available_equipment "
            "(what they have; [] for none) and Formiq proposes the workout without it, saying "
            "what it leaves out"
            if unsaid
            else ""
        )
        short = assessment.counted < assessment.required
        session = " in a short session" if completeness.is_short(request.max_minutes) else ""
        if assessment.missing or short:
            # what the user could do, to tell a gap the model can fill from one it cannot
            pool = self._main_pool(unavailable, beginner)
            for region in completeness.in_order(assessment.missing):
                if completeness.trainable(pool, region):
                    problems.append(
                        f"the main workout trains no {REGION_NAMES[region]} (no main exercise "
                        f"with {movers(region)} as a primary muscle), which a {focus} workout "
                        "needs: "
                        "add a main exercise for it, such as one search_exercises finds with "
                        f"use MAIN_WORKOUT and muscle {REGION_MUSCLES[region][0]}{lacking}"
                    )
                else:
                    limitations.append(
                        CoverageLimitation(
                            code="NO_SUITABLE_EXERCISE",
                            region=region,
                            message=(
                                f"Formiq's catalog has no {REGION_NAMES[region]} exercise (with "
                                f"{movers(region)} as a primary muscle) that suits the user's "
                                "equipment and experience, so this workout does not train it."
                            ),
                        )
                    )
            if short:
                available = completeness.countable(pool, focus)
                if available == 0:
                    problems.append(
                        f"Formiq's catalog has no exercise for a {focus} workout that suits the "
                        "user's equipment and experience: choose another focus, or tell the user"
                    )
                elif assessment.counted < min(assessment.required, available):
                    problems.append(
                        f"the main workout has {assessment.counted} exercises that count for a "
                        f"{focus} workout (each different, for "
                        f"{regions_named(FOCUS_RULES[focus].counted)}, of at least "
                        f"{MIN_COUNTED_SETS} sets), fewer than the {assessment.required} it "
                        f"needs{session}: "
                        "add main exercises from the catalog"
                    )
                if 0 < available < assessment.required:
                    limitations.append(
                        CoverageLimitation(
                            code="TOO_FEW_SUITABLE_EXERCISES",
                            region=None,
                            message=(
                                f"Formiq's catalog has only {available} different exercises "
                                f"for a {focus} workout that suit the user's equipment and "
                                f"experience, fewer than the {assessment.required} it needs."
                            ),
                        )
                    )
        return problems, ProposalCoverage(
            complete=not limitations,
            focus=focus,
            trained_regions=completeness.in_order(assessment.trained),
            missing_regions=completeness.in_order(assessment.missing),
            main_exercises_counted=assessment.counted,
            main_exercises_required=assessment.required,
            limitations=limitations,
        )

    def _main_pool(self, unavailable: set[str], beginner: bool) -> list[Any]:
        """The active main exercises the user could do: needing nothing they
        cannot use, and not too hard for them."""
        available = None
        if unavailable:
            available = [
                item.id
                for item in self.catalog.list_equipment(is_active=True)
                if equipment_key(item.name) not in unavailable
            ]
        return [
            exercise
            for exercise in self.catalog.list_exercises(
                ExerciseFilters(use=MAIN), available_equipment_ids=available
            )
            if not (beginner and exercise.difficulty == Difficulty.ADVANCED)
        ]

    def get_exercise(self, request: GetExerciseInput) -> ExerciseOutput:
        # inactive exercises stay readable by id, as in the catalog API
        exercise = self.catalog.get_exercise_by_id(request.exercise_id)
        if exercise is None:
            raise ToolError(
                ToolErrorCode.RESOURCE_NOT_FOUND,
                f"the catalog has no exercise {request.exercise_id}",
            )
        steps = [step for step in exercise.instructions if step.strip()]
        return ExerciseOutput(
            exercise_id=exercise.id,
            name=exercise.name,
            description=clip(exercise.description),
            instructions=[clip(step) for step in steps[:MAX_INSTRUCTION_STEPS]],
            difficulty=exercise.difficulty,
            movement_pattern=exercise.movement_pattern,
            category=exercise.category,
            uses=exercise.uses,
            muscles=[
                MuscleOutput(name=muscle.muscle_group.name, role=muscle.role)
                for muscle in exercise.muscles
            ],
            equipment=[item.name for item in exercise.equipment],
            is_active=exercise.is_active,
            truncated=len(steps) > MAX_INSTRUCTION_STEPS,
        )

    def search_exercises(self, request: SearchExercisesInput) -> SearchExercisesOutput:
        muscle_group_id = None
        if request.muscle is not None:
            groups = self.catalog.list_muscle_groups(is_active=True)
            (muscle_group_id,) = _ids_by_name(groups, [request.muscle], "muscle group")
        available = None
        if request.available_equipment is not None:
            # a name for no equipment adds nothing: what needs none is always found
            equipment, _ = _equipment_named(
                self.catalog.list_equipment(is_active=True),
                request.available_equipment,
                hint="; for no equipment at all, give an empty list",
            )
            available = [item.id for item in equipment]
        # active exercises only, the catalog API's default
        matches = self.catalog.list_exercises(
            ExerciseFilters(
                use=request.use,
                muscle_group_id=muscle_group_id,
                equipment_id=request.equipment_id,
                movement_pattern=request.movement_pattern,
                difficulty=request.difficulty,
            ),
            available_equipment_ids=available,
        )
        exercises = most_relevant(matches, use=request.use, muscle=request.muscle)[
            :MAX_SEARCH_RESULTS
        ]
        if request.use == MAIN:
            self.main_candidates.update(
                (exercise.id, muscles_of(exercise)) for exercise in exercises
            )
        # what each activity may go with, once there are main exercises to go with
        annotate = request.use in (WARM_UP, COOL_DOWN) and self.main_candidates
        return SearchExercisesOutput(
            exercises=[
                ExerciseSummaryOutput(
                    exercise_id=exercise.id,
                    name=exercise.name,
                    difficulty=exercise.difficulty,
                    movement_pattern=exercise.movement_pattern,
                    uses=exercise.uses,
                    muscles=[muscle.muscle_group.name for muscle in exercise.muscles],
                    equipment=[item.name for item in exercise.equipment],
                    suits_main=suited_main(exercise, self.main_candidates) if annotate else None,
                )
                for exercise in exercises
            ],
            count=len(exercises),
            total_matches=len(matches),
        )

    def _unavailable_equipment(self, names: Sequence[str]) -> set[str]:
        """The equipment_key() of each piece the user cannot use. Saying the
        user has no equipment does not name what they cannot use, and read as
        nothing it would leave every piece usable: it is an error, as an
        unknown name is."""
        if not names:
            return set()
        catalog = self.catalog.list_equipment(is_active=True)
        hint = "; for a user with no equipment at all, name every piece"
        equipment, no_equipment = _equipment_named(catalog, names, hint=hint)
        if no_equipment:
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                "unavailable_equipment names the equipment the user cannot use, and having "
                f"no equipment is not one; the catalog has {_names(catalog)}{hint}",
            )
        return {equipment_key(item.name) for item in equipment}

    def _equipment_lacking(self, names: Sequence[str] | None) -> set[str]:
        """The equipment_key() of each piece of the catalog the user does not
        have, when they said what they have (names; [] or a name for no
        equipment at all: they have none). None said: nothing."""
        if names is None:
            return set()
        catalog = self.catalog.list_equipment(is_active=True)
        have, _ = _equipment_named(
            catalog, names, hint="; for no equipment at all, give an empty list"
        )
        return {equipment_key(item.name) for item in catalog} - {
            equipment_key(item.name) for item in have
        }

    def _exercise_names(self, exercise_ids: Iterable[int]) -> dict[int, str]:
        """The catalog names of the exercises, by id. Plans and sessions keep
        only the exercise id."""
        names = {}
        for exercise_id in set(exercise_ids):
            exercise = self.catalog.get_exercise_by_id(exercise_id)
            if exercise is not None:
                names[exercise_id] = exercise.name
        return names


def _ids_by_name(items: Sequence[Any], names: Sequence[str], kind: str) -> list[int]:
    """The ids of the catalog items with these names, matched without case.
    An unknown name is an error that lists the names there are."""
    ids = {item.name.casefold(): item.id for item in items}
    if unknown := [name for name in names if name.casefold() not in ids]:
        raise ToolError(
            ToolErrorCode.INVALID_INPUT,
            f"the catalog has no {kind} {', '.join(map(repr, unknown))}; it has {_names(items)}",
        )
    return [ids[name.casefold()] for name in names]


def _names(items: Iterable[Any]) -> str:
    return ", ".join(sorted(item.name for item in items))


def equipment_key(name: str) -> str:
    """An equipment name as it is matched: without case, and with hyphens,
    underscores and runs of spaces as one space ("Pull-up Bar" is "pull up
    bar")."""
    return " ".join(name.replace("-", " ").replace("_", " ").casefold().split())


def _equipment_named(
    catalog: Sequence[Any], names: Sequence[str], *, hint: str
) -> tuple[list[Any], bool]:
    """The catalog equipment with these names, matched by equipment_key(), and
    whether a name says there is no equipment at all (NO_EQUIPMENT), which
    stands for none of it. An unknown name is an error that lists the names
    there are, then the hint."""
    by_key = {equipment_key(item.name): item for item in catalog}
    keys = [equipment_key(name) for name in names]
    if unknown := [
        name
        for name, key in zip(names, keys, strict=True)
        if key not in by_key and key not in NO_EQUIPMENT
    ]:
        raise ToolError(
            ToolErrorCode.INVALID_INPUT,
            f"the catalog has no equipment {', '.join(map(repr, unknown))}; it has "
            f"{_names(catalog)}{hint}",
        )
    return (
        [by_key[key] for key in keys if key in by_key],
        any(key in NO_EQUIPMENT and key not in by_key for key in keys),
    )


def most_relevant(
    exercises: Sequence[Any], *, use: WorkoutSection | None, muscle: str | None
) -> list[Any]:
    """A search's matches, the most relevant first, so the few it returns are
    worth choosing from. Always the same order for the same matches:

    1. in a warm-up or cool-down search, easy CARDIO first: it suits any main
       workout, so a proposal may always use it;
    2. for a muscle, the exercises it is a primary muscle of, then those it is
       a secondary muscle of;
    3. the exercises Formiq classified (with a movement pattern), its own
       among them, then the imported ones it has not;
    4. then one exercise per primary muscle in turn, so that the few returned
       cover several muscles rather than the first names in the alphabet;
    5. by name, then id.
    """
    activity = use in (WARM_UP, COOL_DOWN)
    wanted = muscle.casefold() if muscle else None

    def tier(exercise: Any) -> tuple[bool, bool, bool]:
        return (
            activity and exercise.movement_pattern not in GENERAL_ACTIVITIES,
            wanted is not None
            and not any(
                item.role == MuscleRole.PRIMARY and item.muscle_group.name.casefold() == wanted
                for item in exercise.muscles
            ),
            exercise.movement_pattern is None,
        )

    # each exercise's turn among those of its tier with the same primary muscle
    turns: Counter[tuple] = Counter()
    ranked = []
    for exercise in sorted(exercises, key=lambda item: (tier(item), item.name, item.id)):
        group = (tier(exercise), primary_muscle(exercise))
        ranked.append(((tier(exercise), turns[group], exercise.name, exercise.id), exercise))
        turns[group] += 1
    return [exercise for _, exercise in sorted(ranked, key=lambda pair: pair[0])]


def repeated(exercises: Sequence[Any]) -> list[str]:
    """Each main exercise that repeats an earlier one: the same exercise, or
    one of the same name (completeness.name_key)."""
    # by position: the same exercise twice is one object
    first: dict[str, int] = {}
    repeats = []
    for position, exercise in enumerate(exercises):
        earlier = exercises[first.setdefault(completeness.name_key(exercise.name), position)]
        if first[completeness.name_key(exercise.name)] != position:
            repeats.append(
                f"exercise {exercise.id} ({exercise.name}) is in the main workout twice"
                if earlier.id == exercise.id
                else f"exercise {exercise.id} ({exercise.name}) repeats exercise {earlier.id} "
                f"({earlier.name})"
            )
    return repeats


def movers(region: Any) -> str:
    """The region's main movers, as "A, B or C"."""
    *others, last = REGION_MUSCLES[region]
    return f"{', '.join(others)} or {last}" if others else last


def regions_named(regions: Iterable[Any]) -> str:
    return ", ".join(REGION_NAMES[region] for region in completeness.in_order(regions))


def searches_main(call: ToolCall) -> bool:
    """Whether the call searches for main workout exercises."""
    return call.name == "search_exercises" and call.arguments.get("use") == MAIN


def muscles_of(exercise: Any) -> frozenset[str]:
    """The names of the muscles the exercise trains, primary or secondary."""
    return frozenset(item.muscle_group.name for item in exercise.muscles)


def suited_main(exercise: Any, main: dict[int, frozenset[str]]) -> list[int] | str:
    """The main exercises (their ids, with the muscles they train) that a
    warm-up or cool-down activity may go with: every one ("any") for easy
    CARDIO, which suits any workout, or else those that train a muscle it
    works. propose_workout_plan accepts an activity only with one of them."""
    if exercise.movement_pattern in GENERAL_ACTIVITIES:
        return "any"
    works = muscles_of(exercise)
    return sorted(exercise_id for exercise_id, trained in main.items() if trained & works)


def primary_muscle(exercise: Any) -> str | None:
    """The exercise's first primary muscle (its muscles list them first), or
    its first muscle when none is primary."""
    muscles = list(exercise.muscles)
    primary = [item for item in muscles if item.role == MuscleRole.PRIMARY] or muscles
    return primary[0].muscle_group.name if primary else None


def section_minutes(exercises: Iterable[ProposedExerciseOutput]) -> int:
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


def describe(error: ValidationError) -> str:
    """The validation errors as one line for the model, without the input values."""
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or 'arguments'}: {item['msg']}"
        for item in error.errors()
    )
