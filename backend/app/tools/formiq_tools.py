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
from app.schemas.exercise import Difficulty, ExerciseFilters, MovementPattern
from app.schemas.workout_plan import PlanSection
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
        "message"}}. Only the first MAX_EXECUTED_TOOL_CALLS_PER_TURN calls are run."""
        try:
            return [
                self._run_call(call, user_id)
                if index < MAX_EXECUTED_TOOL_CALLS_PER_TURN
                else error_result(
                    ToolErrorCode.TOOL_LIMIT_REACHED,
                    f"only {MAX_EXECUTED_TOOL_CALLS_PER_TURN} tool calls are run per turn; "
                    "this one was not",
                )
                for index, call in enumerate(calls)
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
        the main workout, and the whole fits the date and the user's stated
        time and equipment. It saves nothing."""
        if self.proposal_terms is None:
            raise ToolError(ToolErrorCode.TOOL_ERROR, "a plan cannot be proposed here")
        scheduled = request.scheduled_date or self.today
        days = (scheduled - self.today).days
        if not 0 <= days <= MAX_PROPOSAL_DAYS_AHEAD:
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"scheduled_date must be today or up to {MAX_PROPOSAL_DAYS_AHEAD} days later",
            )
        unavailable = {name.casefold() for name in request.unavailable_equipment}
        sections = (
            (WARM_UP, request.warm_up),
            (MAIN, request.exercises),
            (COOL_DOWN, request.cool_down),
        )
        found = {
            section: [self._proposed_exercise(item, section, unavailable) for item in items]
            for section, items in sections
        }
        trained = {
            muscle.muscle_group.name for exercise in found[MAIN] for muscle in exercise.muscles
        }
        for section in (WARM_UP, COOL_DOWN):
            for exercise in found[section]:
                if exercise.movement_pattern in GENERAL_ACTIVITIES:
                    continue
                if not trained & {muscle.muscle_group.name for muscle in exercise.muscles}:
                    raise ToolError(
                        ToolErrorCode.INVALID_INPUT,
                        f"exercise {exercise.id} ({exercise.name}) works none of the muscles "
                        f"the main exercises train, so it does not belong in this "
                        f"{SECTION_NAMES[section]}: choose one for those muscles, or easy CARDIO",
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
            expires_at=proposal.expires_at,
        )
        self.proposals.append((proposal, output))
        return output

    def _proposed_exercise(
        self,
        item: ProposedExerciseInput | ProposedActivityInput,
        section: PlanSection,
        unavailable: set[str],
    ) -> Any:
        """The catalog exercise of a proposed plan's item, once it is active,
        needs nothing the user cannot use, and Formiq uses it for the item's
        section."""
        exercise = self.catalog.get_exercise_by_id(item.exercise_id)
        if exercise is None or not exercise.is_active:
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"exercise {item.exercise_id} is not an active Formiq catalog exercise",
            )
        equipment = [equipment.name for equipment in exercise.equipment]
        if needed := [name for name in equipment if name.casefold() in unavailable]:
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
        return exercise

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
            equipment = self.catalog.list_equipment(is_active=True)
            available = _ids_by_name(equipment, request.available_equipment, "equipment")
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
        exercises = matches[:MAX_SEARCH_RESULTS]
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
                )
                for exercise in exercises
            ],
            count=len(exercises),
            total_matches=len(matches),
        )

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
            f"the catalog has no {kind} {', '.join(map(repr, unknown))}; it has "
            f"{', '.join(sorted(item.name for item in items))}",
        )
    return [ids[name.casefold()] for name in names]


def section_minutes(exercises: Iterable[ProposedExerciseOutput]) -> int:
    """How long a section's exercises take, roughly: each set (its own duration
    when timed) and the rest after it. A main exercise without a rest gets
    the default; a warm-up or cool-down activity has none."""
    seconds = 0
    for item in exercises:
        rest = item.rest_seconds
        if rest is None:
            rest = DEFAULT_REST_SECONDS if item.section is MAIN else 0
        seconds += item.sets * ((item.duration_seconds or SET_SECONDS) + rest)
    return math.ceil(seconds / 60)


def describe(error: ValidationError) -> str:
    """The validation errors as one line for the model, without the input values."""
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or 'arguments'}: {item['msg']}"
        for item in error.errors()
    )
