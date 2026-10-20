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
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, NamedTuple

from pydantic import BaseModel, ValidationError

from app.agent.safety import SAFE
from app.ai import ToolCall
from app.approvals import (
    PROPOSAL_ACTIONS,
    ProposalDraft,
    ProposalTerms,
    SafetyBlocked,
    WriteAction,
    WriteProposal,
    propose,
    restore,
)
from app.catalog.classification import DUPLICATE_OF, HIDDEN_DUPLICATE_IDS
from app.schemas.coach import (
    CoverageLimitation,
    ProposalCoverage,
    ProposalRevision,
    RevisionKind,
    SessionFocus,
)
from app.schemas.exercise import (
    Difficulty,
    ExerciseFilters,
    ExerciseSource,
    MovementPattern,
    MuscleRole,
    WorkoutSection,
)
from app.schemas.workout_plan import PlanSection, WorkoutPlanFilters, WorkoutPlanStatus
from app.tools import completeness
from app.tools.completeness import FOCUS_RULES, REGION_MUSCLES, REGION_NAMES
from app.tools.declarations import TOOL_DECLARATIONS
from app.tools.equipment import (
    NO_EQUIPMENT,
    StatedEquipment,
    equipment_key,
    read_equipment_name,
    stated_equipment,
)
from app.tools.errors import ToolError, ToolErrorCode
from app.tools.exercise_names import name_matches, name_words
from app.tools.limits import (
    DEFAULT_REST_SECONDS,
    MAX_ACTIVITY_SETS,
    MAX_EXECUTED_TOOL_CALLS_PER_TURN,
    MAX_EXERCISES,
    MAX_INSTRUCTION_STEPS,
    MAX_LISTED_PLAN_EXERCISES,
    MAX_LISTED_PLANS,
    MAX_OTHER_USE_MATCHES,
    MAX_SUGGESTIONS,
    MAX_PROPOSAL_DAYS_AHEAD,
    MAX_SEARCH_RESULTS,
    MAX_SECTION_MINUTES,
    MAX_SETS,
    MAX_STRETCH_HOLD_SECONDS,
    MAX_TEXT_LENGTH,
    MIN_COUNTED_SETS,
    SECONDS_PER_REP,
    SET_SECONDS,
)
from app.tools.muscles import muscles_named
from app.tools.schemas import (
    CurrentWorkoutPlanOutput,
    ExerciseChangeOutput,
    ExerciseOutput,
    ExerciseSummaryOutput,
    GetCurrentWorkoutPlanInput,
    GetExerciseInput,
    GetLatestWorkoutSessionInput,
    GetPendingProposalInput,
    GetUserProfileInput,
    GetWorkoutPlanInput,
    GetWorkoutSessionInput,
    LatestWorkoutSessionOutput,
    OtherUseExerciseOutput,
    OtherUseMatchesOutput,
    ListWorkoutPlansInput,
    MuscleOutput,
    PendingProposalOutput,
    PlanExerciseOutput,
    PlanSummaryOutput,
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
    WorkoutChangesOutput,
    WorkoutPlanListOutput,
    WorkoutPlanOutput,
    WorkoutSessionOutput,
    WorkoutSetOutput,
)

if TYPE_CHECKING:
    # Only for type hints: the tools get service instances from CoachService, so
    # this package imports no services (or anything below them) when it runs.
    from app.services import (
        ExerciseCatalogService,
        PlanProposalService,
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


def error_result(
    code: ToolErrorCode, message: str, suggestions: Sequence[dict] = ()
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code.value, "message": message}
    if suggestions:
        # Formiq's own: catalog exercises that would correct the call
        error["suggestions"] = list(suggestions)
    return {"error": error}


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
# The upstream categories of the specialised main exercises: a search lists the standard
# lifts first (most_relevant).
SPECIALISED_CATEGORIES = frozenset({"plyometrics", "olympic weightlifting", "strongman"})
SECTION_NAMES = {WARM_UP: "warm-up", MAIN: "main workout", COOL_DOWN: "cool-down"}

# What an unknown name in available_equipment is answered with, after the
# catalog's names: a model that guessed the user's equipment (from a gym
# training location, say) is told to leave the filter out.
AVAILABLE_EQUIPMENT_HINT = (
    "; for no equipment at all, give an empty list, and when the user did not say what "
    "equipment they have, leave available_equipment out"
)


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

    With user_words, what the user wrote, the equipment they said they lack
    is left out of every proposal and workout search, and a proposal may say
    they have only equipment they said they have. The coach service reads that
    from every user turn the client sent, and gives it as stated, so what the
    tools hold is what the model's context says of it, however long ago the
    user said it; without stated, it is read from user_words.
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
        pending_proposals: "PlanProposalService | None" = None,
        conversation: Sequence[tuple[str, str]] | None = None,
        stated: StatedEquipment | None = None,
    ) -> None:
        self.users = users
        self.profiles = profiles
        self.plans = plans
        self.sessions = sessions
        self.catalog = catalog
        self.today = today if today is not None else utc_today()
        self.proposal_terms = proposal_terms
        # the user's proposals awaiting approval, read for the user of the
        # request only (get_pending_proposal); None: none can be read
        self.pending_proposals = pending_proposals
        # The conversation the model sees, as (role, text) turns, oldest first,
        # the user's message last; None when it is not known. What the user
        # said about their equipment there holds for every proposal and
        # workout search (app.tools.equipment), and a revision must be of a
        # plan it makes clear.
        self.conversation = conversation
        self.user_words = (
            None
            if conversation is None
            else [text for role, text in conversation if role == "user"]
        )
        # What the user said about their equipment: read from user_words when first
        # needed, unless the caller read it from the whole conversation (stated).
        self._stated: StatedEquipment | None = stated
        self._equipment_known = stated is not None or self.user_words is not None
        # the main exercises this request's searches returned, by id, with the
        # muscles they train: what a warm-up or cool-down search says each
        # activity suits (suited_main)
        self.main_candidates: dict[int, frozenset[str]] = {}
        # the muscles the user's latest message names (app.tools.muscles), read when first
        # needed: what a warm-up or cool-down search ranks the activities by
        self._said_muscles: frozenset[str] | None = None
        # the plans proposed in this request, in order, with what the model was told
        self.proposals: list[tuple[WriteProposal, ProposedWorkoutPlanOutput]] = []
        # the proposal awaiting the user's approval, as get_pending_proposal
        # last read it: the coach may show it to them again, as it is kept
        self.pending_shown: tuple[WriteProposal, ProposedWorkoutPlanOutput] | None = None
        # Called after each batch of calls to end the read transaction, so no
        # database connection is held while the model answers.
        self.end_read = end_read
        # How long each call of the last run() took, in milliseconds and in the
        # order of its calls (None for a call it did not run): measured, for
        # observability only.
        self.last_durations_ms: list[float | None] = []
        self._tools: dict[str, tuple[type[BaseModel], Callable[[Any], BaseModel]]] = {
            "get_user_profile": (GetUserProfileInput, self.get_user_profile),
            "get_workout_plan": (GetWorkoutPlanInput, self.get_workout_plan),
            "list_workout_plans": (ListWorkoutPlansInput, self.list_workout_plans),
            "get_workout_session": (GetWorkoutSessionInput, self.get_workout_session),
            "get_current_workout_plan": (GetCurrentWorkoutPlanInput, self.get_current_workout_plan),
            "get_latest_workout_session": (
                GetLatestWorkoutSessionInput,
                self.get_latest_workout_session,
            ),
            "get_pending_proposal": (GetPendingProposalInput, self.get_pending_proposal),
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
        self.last_durations_ms = [None] * len(calls)
        try:
            results = {}
            for index in order:
                started = time.perf_counter()
                results[index] = self._run_call(runnable[index], user_id)
                self.last_durations_ms[index] = round((time.perf_counter() - started) * 1000, 1)
            return [
                results[index]
                if index < MAX_EXECUTED_TOOL_CALLS_PER_TURN
                else error_result(
                    ToolErrorCode.TOOL_LIMIT_REACHED,
                    f"only {MAX_EXECUTED_TOOL_CALLS_PER_TURN} tool calls are run per turn; "
                    "this one was not: if you still need what it asks for (a warm-up or "
                    "cool-down search, say), call it again in your next round, before you "
                    "propose",
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
            return error_result(error.code, error.message, error.suggestions)
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
        plan = self._owned_plan(request.user_id, request.plan_id)
        output = self._plan_output(plan)
        if request.compare_with_plan_id is not None:
            other = self._owned_plan(request.user_id, request.compare_with_plan_id)
            output.changes = workout_changes(
                plan_rows(plan), plan.name, plan.scheduled_date, other
            )
        return output

    def _owned_plan(self, user_id: int, plan_id: int) -> Any:
        # None also for another user's plan, which is not told apart from a missing one
        plan = self.plans.get_plan(user_id, plan_id)
        if plan is None:
            raise ToolError(
                ToolErrorCode.RESOURCE_NOT_FOUND, f"the user has no workout plan {plan_id}"
            )
        return plan

    def list_workout_plans(self, request: ListWorkoutPlansInput) -> WorkoutPlanListOutput:
        """The user's saved plans, the ones to do first: PLANNED from the next
        one on, then their past PLANNED plans, then the DRAFT and CANCELLED
        ones, the latest first. None at all is a list of none, not an error."""
        if self.users.get_user_by_id(request.user_id) is None:
            raise ToolError(ToolErrorCode.USER_NOT_FOUND, "the user does not exist")
        plans = self.plans.list_plans(request.user_id, WorkoutPlanFilters())
        current = self.plans.get_current_plan(request.user_id, self.today)
        matching = sorted(
            (plan for plan in plans if request.status in (None, plan.status)),
            key=self._listing_order,
        )
        listed = matching[:MAX_LISTED_PLANS]
        return WorkoutPlanListOutput(
            today=self.today,
            plans=[
                PlanSummaryOutput(
                    plan_id=plan.id,
                    name=plan.name,
                    status=plan.status,
                    scheduled_date=plan.scheduled_date,
                    days_from_today=self._days_from_today(plan.scheduled_date),
                    main_exercises=[
                        row.name for row in plan_rows(plan) if row.section is MAIN
                    ][:MAX_LISTED_PLAN_EXERCISES],
                    exercise_count=len(plan.exercises),
                    is_current=current is not None and plan.id == current.id,
                )
                for plan in listed
            ],
            count=len(listed),
            total=len(matching),
            planned=sum(plan.status == WorkoutPlanStatus.PLANNED for plan in plans),
            truncated=len(matching) > len(listed),
        )

    def _days_from_today(self, day: date | None) -> int | None:
        return None if day is None else (day - self.today).days

    def _listing_order(self, plan: Any) -> tuple:
        days = self._days_from_today(plan.scheduled_date)
        if plan.status == WorkoutPlanStatus.PLANNED:
            if days is None:
                return (2, 0, -plan.id)
            # the next one first, then the most recent past one
            return (0, days, -plan.id) if days >= 0 else (1, -days, -plan.id)
        return (3 if plan.status == WorkoutPlanStatus.DRAFT else 4, 0, -plan.id)

    def get_pending_proposal(self, request: GetPendingProposalInput) -> PendingProposalOutput:
        """The workout proposal of the user's that awaits their approval: the
        one Formiq showed them last, from its records, for the user of the
        request only. It is read, never changed."""
        waiting = (
            [] if self.pending_proposals is None
            else self.pending_proposals.awaiting_approval(request.user_id)
        )  # fmt: skip
        if not waiting:
            raise ToolError(
                ToolErrorCode.RESOURCE_NOT_FOUND,
                "the user has no workout proposal awaiting approval: none was made, or it was "
                "approved or expired; there is no id to ask for",
            )
        stored = waiting[0]
        output = self._pending_output(request.user_id, stored, earlier=len(waiting) - 1)
        if output.coverage is not None:
            self.pending_shown = (
                restore(
                    proposal_id=stored.proposal_id,
                    trusted_user_id=stored.user_id,
                    action=WriteAction(stored.action),
                    parameters=stored.parameters,
                    created_at=stored.created_at,
                    expires_at=stored.expires_at,
                ),
                ProposedWorkoutPlanOutput(
                    **output.model_dump(
                        include={
                            "name", "scheduled_date", "days_from_today", "exercises",
                            "warm_up_minutes", "main_minutes", "cool_down_minutes",
                            "estimated_minutes", "coverage", "revision",
                        }
                    ),
                    expires_at=stored.expires_at,
                ),
            )  # fmt: skip
        return output

    def _pending_output(self, user_id: int, stored: Any, *, earlier: int) -> PendingProposalOutput:
        values = stored.parameters
        exercises = []
        for kept in sorted(values["exercises"], key=lambda item: item["exercise_order"]):
            exercise = self.catalog.get_exercise_by_id(kept["exercise_id"])
            exercises.append(
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
                    notes=clip(kept.get("notes")),
                )
            )
        minutes = {
            section: section_minutes(item for item in exercises if item.section is section)
            for section in PlanSection
        }
        scheduled = date.fromisoformat(values["scheduled_date"])
        coverage = None
        if (focus := values.get("focus")) is not None:
            coverage = self._recorded_coverage(
                SessionFocus(focus),
                [item for item in exercises if item.section is MAIN],
                values.get("max_minutes"),
            )
        revision = changes = unchanged = None
        replaced_id = values.get("replaces_plan_id")
        compared = None
        if replaced_id is not None:
            compared = self.plans.get_plan(user_id, replaced_id)
            unchanged = (
                compared is not None
                and compared.status == WorkoutPlanStatus.PLANNED
                and self.plans.version_of(compared) == values.get("replaces_plan_digest")
            )
            if compared is not None and values.get("revision") is not None:
                before = {
                    completeness.name_key(row.name)
                    for row in plan_rows(compared)
                    if row.section is MAIN
                }
                revision = ProposalRevision(
                    replaces_plan_id=compared.id,
                    replaces_plan_name=compared.name,
                    kind=values["revision"],
                    kept_exercises=[
                        item.exercise_name
                        for item in exercises
                        if item.section is MAIN
                        and completeness.name_key(item.exercise_name) in before
                    ],
                )
        else:
            compared = self.plans.get_current_plan(user_id, self.today)
        if compared is not None:
            changes = workout_changes(proposed_rows(exercises), values["name"], scheduled, compared)
        now = self.proposal_terms.clock() if self.proposal_terms else datetime.now(UTC)
        return PendingProposalOutput(
            name=values["name"],
            scheduled_date=scheduled,
            days_from_today=(scheduled - self.today).days,
            expires_in_minutes=max(0, math.ceil((stored.expires_at - now).total_seconds() / 60)),
            exercises=exercises,
            warm_up_minutes=minutes[WARM_UP],
            main_minutes=minutes[MAIN],
            cool_down_minutes=minutes[COOL_DOWN],
            estimated_minutes=sum(minutes.values()),
            coverage=coverage,
            revision=revision,
            replaced_plan_unchanged=unchanged,
            changes=changes,
            earlier_proposals_awaiting_approval=earlier,
        )

    def _recorded_coverage(
        self, focus: SessionFocus, main: Sequence[ProposedExerciseOutput], max_minutes: int | None
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
                    completed_sets=sum(1 for workout_set in item.sets if workout_set.completed),
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
        original = self._plan_to_revise(request)
        unavailable = (
            self._unavailable_equipment(request.unavailable_equipment)
            | self._equipment_lacking(request.available_equipment)
            | self._stated_lacking()
        )
        if unsaid := self._unsaid_equipment(request.available_equipment):
            raise ToolError(ToolErrorCode.INVALID_INPUT, unsaid)
        beginner = self._beginner(request.user_id)
        sections = (
            (WARM_UP, request.warm_up),
            (MAIN, request.exercises),
            (COOL_DOWN, request.cool_down),
        )
        # Every way the workout fails, at once, so one correction can fix them
        # all, with catalog exercises that would (suggestions, whose ids the
        # model may use): first each exercise on its own, then the whole.
        suggestions = Suggestions(self, unavailable, beginner, request.focus)
        found: dict[PlanSection, list[Any]] = {}
        refused = []
        for section, items in sections:
            found[section] = []
            for item in items:
                try:
                    found[section].append(
                        self._proposed_exercise(item, section, unavailable, beginner)
                    )
                except ToolError as error:
                    refused.append(error.message)
                    suggestions.instead_of(item.exercise_id, section)
        if refused:
            raise ToolError(ToolErrorCode.INVALID_INPUT, "; ".join(refused), suggestions.made)
        suggestions.exclude(exercise for chosen in found.values() for exercise in chosen)
        problems = []
        if repeats := repeated(found[MAIN]):
            problems.append(
                f"{'; '.join(repeats)}: list each main exercise once, and give it more sets "
                "for more work"
            )
        main = {exercise.id: muscles_of(exercise) for exercise in found[MAIN]}
        trained = set().union(*main.values())
        misfits = [
            (section, exercise)
            for section in (WARM_UP, COOL_DOWN)
            for exercise in found[section]
            if not suited_main(exercise, main)
        ]
        if misfits:
            problems.append(
                "; ".join(
                    f"exercise {exercise.id} ({exercise.name}) works none of the muscles the "
                    f"main exercises train, so it does not belong in this {SECTION_NAMES[section]}"
                    for section, exercise in misfits
                )
                + f": the main exercises train {', '.join(sorted(trained)) or 'no listed muscle'}"
                "; choose activities that work one of them, or easy CARDIO"
            )
            for section in dict.fromkeys(section for section, _ in misfits):
                suggestions.easy_cardio(section)

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
                problems.append(
                    f"the {SECTION_NAMES[section]} takes about {minutes[section]} minutes, more "
                    f"than {MAX_SECTION_MINUTES}: keep it light and short"
                )
        total = sum(minutes.values())
        if request.max_minutes is not None and total > request.max_minutes:
            problems.append(
                f"this plan takes about {total} minutes (warm-up {minutes[WARM_UP]}, main "
                f"{minutes[MAIN]}, cool-down {minutes[COOL_DOWN]}), more than the "
                f"{request.max_minutes} the user has: use fewer sets or exercises, shorter "
                "rests, or a shorter warm-up or cool-down"
            )
        # every way the workout falls short of its focus
        shortfalls, coverage = self._coverage(
            request, found[MAIN], unavailable, beginner, suggestions
        )
        problems += shortfalls
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
        revision = None
        if original is not None:
            kept = self._revision_problems(
                request, original, found[MAIN], exercises, unavailable, beginner, problems,
                suggestions,
            )  # fmt: skip
            revision = ProposalRevision(
                replaces_plan_id=original.id,
                replaces_plan_name=original.name,
                kind=request.revision,
                kept_exercises=[exercise.name for exercise in kept],
            )
        if problems:
            raise ToolError(ToolErrorCode.INVALID_INPUT, "; ".join(problems), suggestions.made)
        if self._awaits_approval_unchanged(request.user_id, exercises, scheduled, original):
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                "this workout is the one already awaiting the user's approval, unchanged: do not "
                "propose it again; tell the user it is there to review and approve "
                "(get_pending_proposal reads it), or make the change they asked for",
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
                # what it is for, so it can be described again while it waits
                # (get_pending_proposal): its focus and the user's time
                "focus": str(request.focus),
                **({"max_minutes": request.max_minutes} if request.max_minutes else {}),
                # the plan its approval cancels, as it was when proposed: an
                # approval after it changed is refused
                **(
                    {
                        "replaces_plan_id": original.id,
                        "replaces_plan_digest": self.plans.version_of(original),
                        "revision": str(request.revision),
                    }
                    if original is not None
                    else {}
                ),
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
            revision=revision,
        )
        self.proposals.append((proposal, output))
        return output

    def _plan_to_revise(self, request: ProposeWorkoutPlanInput) -> Any:
        """The user's saved plan the proposal revises, when it revises one: it
        must be theirs, and PLANNED."""
        if request.revises_plan_id is None:
            return None
        # None also for another user's plan, which is not told apart from a missing one
        plan = self.plans.get_plan(request.user_id, request.revises_plan_id)
        if plan is None:
            raise ToolError(
                ToolErrorCode.RESOURCE_NOT_FOUND,
                f"the user has no workout plan {request.revises_plan_id}",
            )
        if plan.status != WorkoutPlanStatus.PLANNED:
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"workout plan {plan.id} is {plan.status}, and only a PLANNED plan can be "
                "revised: propose a new workout, without revises_plan_id and revision",
            )
        if (unclear := self._unclear_revision(request.user_id, plan)) is not None:
            raise ToolError(ToolErrorCode.INVALID_INPUT, unclear)
        return plan

    def _unclear_revision(self, user_id: int, plan: Any) -> str | None:
        """Why the conversation does not make clear that the user means this
        plan, of their several PLANNED ones, or None: the model must not
        choose one for them. They mean it when it is their only PLANNED plan,
        when they or the coach named it (its id or its name) in the
        conversation, when the proposal awaiting their approval revises it,
        or when it is their current plan and they speak of today's or their
        next workout. Nothing to check when the conversation is not known."""
        if self.conversation is None:
            return None
        planned = self.plans.list_plans(
            user_id, WorkoutPlanFilters(status=WorkoutPlanStatus.PLANNED)
        )
        if len(planned) <= 1:
            return None
        said = " ".join(text for _, text in self.conversation).casefold()
        message = self.conversation[-1][1].casefold()
        name = " ".join(plan.name.casefold().split())
        current = self.plans.get_current_plan(user_id, self.today)
        waiting = (
            [] if self.pending_proposals is None
            else self.pending_proposals.awaiting_approval(user_id)
        )  # fmt: skip
        if (
            re.search(rf"(?<!\d){plan.id}(?!\d)", " ".join(self.user_words or ()))
            or (name and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", " ".join(said.split())))
            or any(item.parameters.get("replaces_plan_id") == plan.id for item in waiting[:1])
            or (
                current is not None
                and current.id == plan.id
                and re.search(r"\b(today|tonight|tomorrow|next|current|upcoming)\b", message)
            )
        ):
            return None
        listed = "; ".join(
            f"plan {item.id}, {clip(item.name)!r}"
            + (f", on {item.scheduled_date.isoformat()}" if item.scheduled_date else "")
            for item in sorted(planned, key=self._listing_order)[:MAX_LISTED_PLANS]
        )
        return (
            f"the user has {len(planned)} PLANNED plans ({listed}) and has not made clear which "
            "one they want changed: do not choose one for them; ask which one, with "
            "ASK_CLARIFICATION, naming them"
        )

    def _awaits_approval_unchanged(
        self, user_id: int, exercises: Sequence[ProposedExerciseOutput], scheduled: date,
        original: Any,
    ) -> bool:  # fmt: skip
        """Whether the workout is the user's proposal awaiting approval again,
        unchanged: the same day, plan revised and prescription, every
        section's."""
        if self.pending_proposals is None:
            return False
        waiting = self.pending_proposals.awaiting_approval(user_id)
        if not waiting:
            return False
        values = waiting[0].parameters
        before = [
            (
                kept["section"], kept["exercise_id"], kept["sets"], kept.get("reps"),
                kept.get("duration_seconds"), kept.get("rest_seconds"),
            )
            for kept in sorted(values["exercises"], key=lambda item: item["exercise_order"])
        ]  # fmt: skip
        after = [
            (
                str(item.section), item.exercise_id, item.sets, item.reps,
                item.duration_seconds, item.rest_seconds,
            )
            for item in exercises
        ]  # fmt: skip
        return (
            before == after
            and values["scheduled_date"] == scheduled.isoformat()
            and values.get("replaces_plan_id") == (original.id if original is not None else None)
        )

    def _revision_problems(
        self,
        request: ProposeWorkoutPlanInput,
        original: Any,
        main: Sequence[Any],
        exercises: Sequence[ProposedExerciseOutput],
        unavailable: set[str],
        beginner: bool,
        problems: list[str],
        suggestions: "Suggestions",
    ) -> list[Any]:
        """The main exercises the proposal keeps from the plan it revises (the
        same exercise, or one of the same name), adding to problems how it
        fails to revise it: an ADJUST that changes nothing, or an ALTERNATIVE
        that keeps an exercise the catalog has a replacement for.

        An ALTERNATIVE may keep an exercise only when the catalog leaves no
        choice: no other main exercise the user can do (their equipment and
        experience) for a part of the body it trains, that neither the plan
        nor the proposal holds already. How many may be kept is the
        catalog's to say, not a fixed share."""
        before = sorted(original.exercises, key=lambda item: item.exercise_order)
        before_main = [item.exercise for item in before if item.section == MAIN]
        before_keys = {completeness.name_key(exercise.name) for exercise in before_main}
        kept = [
            exercise for exercise in main if completeness.name_key(exercise.name) in before_keys
        ]

        if request.revision is RevisionKind.ADJUST:
            if prescribed(exercises) == prescribed(before):
                problems.append(
                    f"this is workout plan {original.id} unchanged: make the changes the user "
                    "asked for"
                )
            return kept

        rule = FOCUS_RULES[request.focus]
        used = before_keys | {completeness.name_key(exercise.name) for exercise in main}
        # the other exercises the user could do instead, one per name
        fresh: dict[str, Any] = {}
        for exercise in suggestions.pool:
            key = completeness.name_key(exercise.name)
            if key not in used and completeness.regions_of(exercise) & rule.allowed:
                fresh.setdefault(key, exercise)
        replaceable = []
        for exercise in kept:
            regions = completeness.regions_of(exercise) & rule.allowed
            other = next(
                (key for key, item in fresh.items() if completeness.regions_of(item) & regions),
                None,
            )
            if other is not None:
                suggestions.add(
                    [item for item in fresh.values() if completeness.regions_of(item) & regions],
                    f"instead of exercise {exercise.id} ({exercise.name})",
                )
                del fresh[other]
                replaceable.append((exercise, regions))
        if replaceable:
            regions = set().union(*(regions for _, regions in replaceable))
            muscles = ", ".join(
                REGION_MUSCLES[region][0] for region in completeness.in_order(regions)
            )
            problems.append(
                f"the user asked for a different workout than plan {original.id}, but this one "
                "keeps "
                + ", ".join(
                    f"exercise {exercise.id} ({exercise.name})" for exercise, _ in replaceable
                )
                + f" from it, and the catalog has other {regions_named(regions)} exercises the "
                "user can do: replace them with ones the plan does not have, such as "
                f"search_exercises finds with use MAIN_WORKOUT and muscle {muscles}; or give "
                "revision ADJUST if the user asked only for some changes"
            )
        return kept

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
        if (
            section is not MAIN
            and exercise.movement_pattern == MovementPattern.STRETCH
            and (getattr(item, "duration_seconds", None) or 0) > MAX_STRETCH_HOLD_SECONDS
        ):
            raise ToolError(
                ToolErrorCode.INVALID_INPUT,
                f"exercise {item.exercise_id} ({exercise.name}) is a held stretch: hold it at "
                f"most {MAX_STRETCH_HOLD_SECONDS} seconds a set (about 30 is usual), and use up "
                f"to {MAX_ACTIVITY_SETS} sets, or another activity, for more time",
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
        suggestions: "Suggestions",
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
        unsaid = (
            request.available_equipment is None
            and not request.unavailable_equipment
            and not self._stated_lacking()
        )
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
            pool = suggestions.pool
            for region in completeness.in_order(assessment.missing):
                if completeness.trainable(pool, region):
                    suggestions.for_region(region)
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
                    suggestions.for_focus()
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
        catalog_equipment = self.catalog.list_equipment(is_active=True)
        if request.available_equipment is not None:
            # a name for no equipment adds nothing: what needs none is always found
            equipment, _ = _equipment_named(
                catalog_equipment, request.available_equipment, hint=AVAILABLE_EQUIPMENT_HINT
            )
            available = [item.id for item in equipment]
        excluded = []
        if request.use is not None and (lacked := self._stated_lacking()):
            # for a workout, never what needs equipment the user said they lack
            excluded = [item for item in catalog_equipment if equipment_key(item.name) in lacked]
            usable = {item.id for item in catalog_equipment} - {item.id for item in excluded}
            available = sorted(usable if available is None else usable & set(available))
        needed = (
            None
            if request.equipment is None
            else _equipment_needed(catalog_equipment, request.equipment)
        )
        # active exercises only, the catalog API's default
        filters = {
            "muscle_group_id": muscle_group_id,
            "equipment_id": None if needed is None else needed.id,
            "movement_pattern": request.movement_pattern,
            "difficulty": request.difficulty,
        }
        matches = visible(
            self.catalog.list_exercises(
                ExerciseFilters(use=request.use, **filters), available_equipment_ids=available
            )
        )
        named: set[int] | None = None
        asked_for: set[int] = set()
        kept_as: dict[str, str] = {}
        if request.name is not None:
            named, asked_for, kept_as = self._named(request.name)
            matches = [exercise for exercise in matches if exercise.id in named]
        # what each activity may go with, once there are main exercises to go with
        activity = request.use in (WARM_UP, COOL_DOWN)
        main = self.main_candidates if activity else {}
        exercises = most_relevant(
            matches,
            use=request.use,
            muscle=request.muscle,
            main=main,
            said=self._said_muscles_named() if activity else frozenset(),
        )
        # the exercise the user named comes first, whatever else has the words
        exercises = sorted(exercises, key=lambda exercise: exercise.id not in asked_for)
        exercises = exercises[:MAX_SEARCH_RESULTS]
        other_uses = None
        if request.use is not None and not matches:
            # Nothing is used for this section, which says nothing of the catalog as a
            # whole: name what matches every other filter, and is used for another
            # section (a rowing machine exercise for the warm-up, none for the main
            # workout). Apart from the results, and not one to choose for this use.
            beyond = visible(
                self.catalog.list_exercises(
                    ExerciseFilters(**filters), available_equipment_ids=available
                )
            )
            if named is not None:
                beyond = [exercise for exercise in beyond if exercise.id in named]
            if beyond:
                other_uses = OtherUseMatchesOutput(
                    total=len(beyond),
                    exercises=[
                        OtherUseExerciseOutput(
                            name=exercise.name,
                            uses=exercise.uses,
                            equipment=[item.name for item in exercise.equipment],
                        )
                        for exercise in sorted(
                            most_relevant(beyond, use=None, muscle=request.muscle),
                            key=lambda exercise: exercise.id not in asked_for,
                        )[:MAX_OTHER_USE_MATCHES]
                    ],
                )
        if request.use == MAIN:
            self.main_candidates.update(
                (exercise.id, muscles_of(exercise)) for exercise in exercises
            )
        annotate = bool(main)
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
            excluded_equipment=sorted(item.name for item in excluded) or None,
            matches_for_other_uses=other_uses,
            note=search_note(
                request.name,
                exercises,
                len(matches),
                kept_as,
                elsewhere=[item.name for item in other_uses.exercises] if other_uses else None,
            ),
        )

    def _named(self, name: str) -> tuple[set[int], set[int], dict[str, str]]:
        """The ids of the exercises whose names have every word of name; those among them
        the name asks for (exactly its words, or the exercise the catalog keeps in place of
        a hidden duplicate that has them); and each such hidden duplicate's name with the name
        of the exercise kept: "Standing Hip Circles" is not "not in the catalog" when it is
        kept as "Hip Circles". The whole catalog is read, so a hidden duplicate is found
        whatever the other filters are."""
        everyone = self.catalog.list_exercises(ExerciseFilters())
        by_name = {exercise.name.casefold(): exercise for exercise in everyone}
        wanted = name_words(name)
        ids: set[int] = set()
        asked_for: set[int] = set()
        kept_as: dict[str, str] = {}
        for exercise in everyone:
            if not name_matches(exercise.name, name):
                continue
            kept = DUPLICATE_OF.get(exercise.source_id)
            if kept is None:
                ids.add(exercise.id)
                if name_words(exercise.name) == wanted:
                    asked_for.add(exercise.id)
            elif (twin := by_name.get(kept.casefold())) is not None:
                ids.add(twin.id)
                asked_for.add(twin.id)
                kept_as[exercise.name] = twin.name
        return ids, asked_for, kept_as

    def _said_muscles_named(self) -> frozenset[str]:
        """The muscles the user's latest message names (app.tools.muscles.muscles_named),
        none when it is not known."""
        if self._said_muscles is None:
            self._said_muscles = frozenset()
            if self.conversation and self.conversation[-1][0] == "user":
                known = {group.name for group in self.catalog.list_muscle_groups(is_active=True)}
                self._said_muscles = muscles_named(self.conversation[-1][1], known)
        return self._said_muscles

    def _stated_equipment(self) -> StatedEquipment:
        """What the user said about their equipment (app.tools.equipment);
        nothing when what they wrote is not known."""
        if self._stated is None:
            keys = [] if not self.user_words else [
                equipment_key(item.name) for item in self.catalog.list_equipment(is_active=True)
            ]
            self._stated = stated_equipment(self.user_words or (), keys)
        return self._stated

    def _stated_lacking(self) -> set[str]:
        """The equipment_key() of each piece of the catalog the user said they
        lack: named ("no bench"), or all but what they have ("I don't have any
        equipment", "I only have dumbbells")."""
        stated = self._stated_equipment()
        if not stated.said:
            return set()
        return stated.lacked(
            equipment_key(item.name) for item in self.catalog.list_equipment(is_active=True)
        )

    def _unsaid_equipment(self, names: Sequence[str] | None) -> str | None:
        """Why the equipment a proposal says the user has is not what they said,
        or None: a piece they said they lack, or one they never said they have
        (mentioning it is not having it). Nothing to check when the proposal
        says nothing, or what the user wrote is not known."""
        if names is None or not self._equipment_known:
            return None
        catalog = self.catalog.list_equipment(is_active=True)
        have, _ = _equipment_named(catalog, names, hint=AVAILABLE_EQUIPMENT_HINT)
        stated = self._stated_equipment()
        lacked = self._stated_lacking()
        said_lacking = [item.name for item in have if equipment_key(item.name) in lacked]
        unsaid = [
            item.name
            for item in have
            if equipment_key(item.name) not in stated.has | lacked
        ]
        problems = []
        if said_lacking:
            problems.append(f"the user said they do not have {', '.join(said_lacking)}")
        if unsaid:
            problems.append(f"the user did not say they have {', '.join(unsaid)}")
        if not problems:
            return None
        return (
            f"available_equipment is only what the user said they have, and {'; '.join(problems)}"
            ": give the equipment they said they have ([] for none), or leave "
            "available_equipment out when they did not say"
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
        equipment, no_equipment = _equipment_named(catalog, names, hint=hint, lacked=True)
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
        have, _ = _equipment_named(catalog, names, hint=AVAILABLE_EQUIPMENT_HINT)
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


def _equipment_named(
    catalog: Sequence[Any], names: Sequence[str], *, hint: str, lacked: bool = False
) -> tuple[list[Any], bool]:
    """The catalog equipment these names mean (read_equipment_name(): the
    catalog's name, its plural or another name for it), and whether a name
    says there is no equipment at all (NO_EQUIPMENT), which stands for none
    of it. The names say what the user has, or, with lacked, what they lack.

    An unknown name is an error that lists the names there are, then the
    hint. So is a name for what the user has that says they lack it ("no
    dumbbells") or may not have it ("maybe a kettlebell"): it is never read
    as theirs. A name for what they lack may say so."""
    by_key = {equipment_key(item.name): item for item in catalog}
    found, unknown, unsure = [], [], []
    no_equipment = False
    for name in names:
        read = read_equipment_name(name, by_key)
        if read.key is None:
            unknown.append(name)
        elif read.key == NO_EQUIPMENT:
            no_equipment = True
        elif not lacked and (read.negated or read.doubtful):
            unsure.append(f"{name!r} does not say the user has {by_key[read.key].name}")
        else:
            found.append(by_key[read.key])
    if unknown:
        raise ToolError(
            ToolErrorCode.INVALID_INPUT,
            f"the catalog has no equipment {', '.join(map(repr, unknown))}; it has "
            f"{_names(catalog)}{hint}",
        )
    if unsure:
        raise ToolError(
            ToolErrorCode.INVALID_INPUT,
            f"{'; '.join(unsure)}: available_equipment lists only what the user has; "
            "give what they lack in unavailable_equipment",
        )
    return found, no_equipment


def _equipment_needed(catalog: Sequence[Any], name: str) -> Any:
    """The catalog equipment an exercise must use, from the name the model gave
    (read_equipment_name(): the catalog's name, its plural or another name for
    it). An unknown name is an error that lists the names there are. So is a
    name for no equipment, which is what available_equipment [] says, and one
    that negates or doubts itself. A piece the catalog has that no exercise
    needs is no error: the search finds nothing."""
    by_key = {equipment_key(item.name): item for item in catalog}
    read = read_equipment_name(name, by_key)
    if read.key is None:
        raise ToolError(
            ToolErrorCode.INVALID_INPUT,
            f"the catalog has no equipment {name!r}; it has {_names(catalog)}",
        )
    if read.key == NO_EQUIPMENT:
        raise ToolError(
            ToolErrorCode.INVALID_INPUT,
            f"{name!r} is no equipment an exercise needs: for exercises that need none, give "
            "available_equipment as an empty list",
        )
    if read.negated or read.doubtful:
        raise ToolError(
            ToolErrorCode.INVALID_INPUT,
            f"{name!r} does not name a piece of equipment an exercise must use: give the piece "
            f"itself, as the catalog names it ({_names(catalog)})",
        )
    return by_key[read.key]


def most_relevant(
    exercises: Sequence[Any],
    *,
    use: WorkoutSection | None,
    muscle: str | None,
    main: dict[int, frozenset[str]] | None = None,
    said: frozenset[str] = frozenset(),
) -> list[Any]:
    """A search's matches, the most relevant first, so the few it returns are
    worth choosing from. Always the same order for the same matches:

    1. in a warm-up or cool-down search, easy CARDIO first: it suits any main
       workout, so a proposal may always use it;
    2. for a muscle, the exercises it is a primary muscle of, then those it is
       a secondary muscle of;
    3. in a warm-up or cool-down search once there are main exercises (main: the
       ids of those the request's searches returned, with the muscles they
       train), the activities that fit them: first those whose primary muscle a
       main exercise trains, then those that work one of its muscles in some
       other role, and last those no main exercise suits, which a proposal could
       not use (suited_main). Live QA (2026-10-19) found a chest and triceps
       workout offered the same ten generic activities as any other, so the
       activities made for its muscles were never seen. The muscles the user
       said they train (said, from app.tools.muscles) take the place of the main
       exercises' when there are any: a main workout searched without a muscle
       returns exercises for every muscle, which tells the activities apart no
       better than none;
    4. those some section uses before those none does (a stretch Formiq keeps but
       does not use for any section cannot go into a workout);
    5. outside a warm-up or cool-down search, Formiq's own exercises before the
       imported ones, which are all classified now (app.catalog.patterns): its
       own are the ones it wrote and described;
    6. outside a warm-up or cool-down search, the standard lifts (strength and
       powerlifting) before the specialised ones (plyometrics, Olympic lifts and
       strongman): the jumps, skips and bounds of a pattern search would otherwise
       crowd the lunges and squats out of the few returned;
    7. the exercises Formiq classified (with a movement pattern), then the ones
       it has not;
    8. then one exercise per primary muscle in turn, so that the few returned
       cover several muscles rather than the first names in the alphabet;
    9. by name, then id.
    """
    activity = use in (WARM_UP, COOL_DOWN)
    wanted = muscle.casefold() if muscle else None
    trained = set(said) if activity and said else set()
    if activity and main and not trained:
        trained = set().union(*main.values())

    def fit(exercise: Any) -> int:
        if not trained or exercise.movement_pattern in GENERAL_ACTIVITIES:
            return 0
        if any(
            item.role == MuscleRole.PRIMARY and item.muscle_group.name in trained
            for item in exercise.muscles
        ):
            return 0
        return 1 if muscles_of(exercise) & trained else 2

    def tier(exercise: Any) -> tuple[bool, bool, int, bool, bool, bool, bool]:
        return (
            activity and exercise.movement_pattern not in GENERAL_ACTIVITIES,
            wanted is not None
            and not any(
                item.role == MuscleRole.PRIMARY and item.muscle_group.name.casefold() == wanted
                for item in exercise.muscles
            ),
            fit(exercise),
            not exercise.uses,
            not activity and exercise.source != ExerciseSource.FORMIQ,
            not activity and exercise.category in SPECIALISED_CATEGORIES,
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


def cut_note(shown: int, total: int) -> str | None:
    """What a search says when it returned only some of its matches, or None when it
    returned them all: so a list is never given to the user as every match."""
    if total <= shown:
        return None
    more = total - shown
    return (
        f"Showing {shown} of {total} matches, the most relevant first: this is not all of "
        f"them. Say that {more} more {'exists' if more == 1 else 'exist'}, or narrow the "
        "search (muscle, equipment, movement_pattern, difficulty) to see others."
    )


def search_note(
    name: str | None,
    shown: Sequence[Any],
    total: int,
    kept_as: dict[str, str],
    *,
    elsewhere: Sequence[str] | None = None,
) -> str | None:
    """What a search tells the model beyond its results, or None: that they are only some
    of the matches (cut_note); for a search by name, that the exercise a name belongs to
    is kept under another one, or that nothing has those words (unless exercises that do
    are named for another section: elsewhere, their names), which is not saying the
    catalog does not have the exercise."""
    notes = [cut_note(len(shown), total)]
    if name is not None:
        returned = {exercise.name for exercise in shown} | set(elsewhere or ())
        notes += [
            f"The catalog keeps '{hidden}' as '{kept}'."
            for hidden, kept in sorted(kept_as.items())
            if kept in returned
        ]
        if total == 0 and elsewhere is None:
            notes.append(
                f"No exercise matches every word of {name!r} with the "
                "other filters. That is not the catalog having no such exercise: try fewer "
                "or other words (the main word of its name), or search by muscle or "
                "movement_pattern, before saying it is not there."
            )
    return " ".join(note for note in notes if note) or None


def visible(exercises: Iterable[Any]) -> list[Any]:
    """A search's matches without Formiq's hidden duplicates (app.catalog.
    classification): an imported record of an exercise the catalog keeps under
    another name. They suit no section, so a search by use never returns them;
    this keeps them out of one that gives no use too (a search by movement
    pattern or muscle), where they would sit beside the exercise kept in their
    place. They stay in the catalog, readable by id, and in the plans that hold
    them."""
    return [exercise for exercise in exercises if exercise.source_id not in HIDDEN_DUPLICATE_IDS]


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


class Suggestions:
    """Catalog exercises that would correct a refused proposal, for the model
    to use: each one the user can do (their equipment, and not ADVANCED for a
    beginner), none already in the workout, at most MAX_SUGGESTIONS for each
    thing to correct, the most relevant first (most_relevant). Their ids come
    from Formiq, so the model may use them."""

    def __init__(
        self, tools: FormiqTools, unavailable: set[str], beginner: bool, focus: SessionFocus
    ) -> None:
        self.tools = tools
        self.unavailable = unavailable
        self.beginner = beginner
        self.focus = focus
        self.made: list[dict[str, Any]] = []
        # the names already in the workout, or suggested
        self._used: set[str] = set()
        self._pool: list[Any] | None = None

    @property
    def pool(self) -> list[Any]:
        """The main exercises the user could do (FormiqTools._main_pool)."""
        if self._pool is None:
            self._pool = self.tools._main_pool(self.unavailable, self.beginner)
        return self._pool

    def exclude(self, exercises: Iterable[Any]) -> None:
        self._used |= {completeness.name_key(exercise.name) for exercise in exercises}

    def add(self, exercises: Iterable[Any], reason: str) -> None:
        added = 0
        for exercise in exercises:
            key = completeness.name_key(exercise.name)
            if key in self._used:
                continue
            self._used.add(key)
            self.made.append(
                {
                    "exercise_id": exercise.id,
                    "name": exercise.name,
                    "for": reason,
                    "difficulty": str(exercise.difficulty),
                    "equipment": [item.name for item in exercise.equipment],
                }
            )
            added += 1
            if added == MAX_SUGGESTIONS:
                return

    def for_region(self, region: Any) -> None:
        """Main exercises that cover a region the workout misses."""
        covering = [item for item in self.pool if region in completeness.covered_by(item)]
        self.add(most_relevant(covering, use=MAIN, muscle=None), f"the {REGION_NAMES[region]}")

    def for_focus(self) -> None:
        """More main exercises that count towards the workout's focus."""
        counted = FOCUS_RULES[self.focus].counted
        fitting = [item for item in self.pool if completeness.regions_of(item) & counted]
        self.add(most_relevant(fitting, use=MAIN, muscle=None), f"a {self.focus} workout")

    def instead_of(self, exercise_id: int, section: PlanSection) -> None:
        """What may replace a refused exercise: a main exercise for the same
        part of the body, or easy cardio for a warm-up or cool-down."""
        if section is not MAIN:
            self.easy_cardio(section)
            return
        exercise = self.tools.catalog.get_exercise_by_id(exercise_id)
        regions = (
            set() if exercise is None
            else completeness.regions_of(exercise) & FOCUS_RULES[self.focus].allowed
        )  # fmt: skip
        if not regions:
            self.for_focus()
            return
        alike = [item for item in self.pool if completeness.regions_of(item) & regions]
        self.add(most_relevant(alike, use=MAIN, muscle=None), f"instead of exercise {exercise_id}")

    def easy_cardio(self, section: PlanSection) -> None:
        """Easy cardio for a warm-up or cool-down, which suits any workout."""
        catalog = self.tools.catalog
        available = None
        if self.unavailable:
            available = [
                item.id
                for item in catalog.list_equipment(is_active=True)
                if equipment_key(item.name) not in self.unavailable
            ]
        cardio = catalog.list_exercises(
            ExerciseFilters(
                use=section, movement_pattern=MovementPattern.CARDIO, difficulty=Difficulty.BEGINNER
            ),
            available_equipment_ids=available,
        )
        self.add(most_relevant(cardio, use=section, muscle=None), f"the {SECTION_NAMES[section]}")


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
    """A proposal's exercises as prescribed, in order (a proposal sets no weight)."""
    return [
        Row(
            item.section,
            item.exercise_name,
            item.sets,
            item.reps,
            item.duration_seconds,
            item.rest_seconds,
            None,
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


def workout_changes(
    rows: Sequence[Row], name: str, scheduled_date: date | None, plan: Any
) -> WorkoutChangesOutput:
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
            added.append(ExerciseChangeOutput(
                section=row.section, exercise_name=row.name, before=None, after=prescription(row)
            ))  # fmt: skip
            continue
        unmatched.remove(same)
        if prescription(same) == prescription(row):
            unchanged.append(row.name)
        else:
            changed.append(ExerciseChangeOutput(
                section=row.section, exercise_name=row.name, before=prescription(same),
                after=prescription(row),
            ))  # fmt: skip
    removed = [
        ExerciseChangeOutput(
            section=item.section, exercise_name=item.name, before=prescription(item), after=None
        )
        for item in unmatched
    ]
    return WorkoutChangesOutput(
        compared_with_plan_id=plan.id,
        compared_with_plan_name=plan.name,
        added=added,
        removed=removed,
        changed=changed,
        unchanged=unchanged,
        name_changed=name != plan.name,
        scheduled_date_changed=scheduled_date != plan.scheduled_date,
        identical=not (added or removed or changed),
    )


def prescribed(items: Iterable[Any]) -> list[tuple]:
    """What a workout's exercises prescribe, in order: how a revision tells
    whether it changed the plan. Weights and notes aside: a proposal sets no
    weight, so dropping a plan's weights alone is no revision."""
    return [
        (
            str(item.section),
            item.exercise_id,
            item.sets,
            item.reps,
            item.duration_seconds,
            item.rest_seconds,
        )
        for item in items
    ]


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
