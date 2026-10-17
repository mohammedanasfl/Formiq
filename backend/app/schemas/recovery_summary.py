"""The recovery summary of a completed workout: the structured inputs a user may give
(how they feel, which allergens to avoid) and the response built from them. Only enum
values and a number are ever accepted, never free text, so no note or message can reach
the rules that judge them, and the response never echoes what was sent.

The response's groups make the three kinds of statement structural: `calculated` is
exact arithmetic on recorded data, `estimates` applies a published coefficient (always a
range), and `guidance` carries no user-specific number.

app.guidance imports the enums below, so this module must not import app.guidance.
The response therefore names statuses as Literal strings; a unit test pins each of
them to the matching app.guidance enum.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.exercise import MuscleRole, WorkoutSection


class BodyArea(StrEnum):
    """Where a user feels discomfort. Each area stands for the muscle groups of
    the catalog listed in app.guidance.recovery.AREA_MUSCLES."""

    NECK = "NECK"
    SHOULDERS = "SHOULDERS"
    CHEST = "CHEST"
    UPPER_BACK = "UPPER_BACK"
    LOWER_BACK = "LOWER_BACK"
    ARMS = "ARMS"
    ELBOWS = "ELBOWS"
    WRISTS_HANDS = "WRISTS_HANDS"
    CORE = "CORE"
    HIPS = "HIPS"
    GLUTES = "GLUTES"
    FRONT_THIGHS = "FRONT_THIGHS"
    BACK_THIGHS = "BACK_THIGHS"
    KNEES = "KNEES"
    CALVES = "CALVES"
    ANKLES_FEET = "ANKLES_FEET"


class DiscomfortKind(StrEnum):
    SORENESS = "SORENESS"
    PAIN = "PAIN"
    KNOWN_INJURY = "KNOWN_INJURY"


class WarningSign(StrEnum):
    """Signs that need medical care, not coaching: reporting any one of them
    withholds every nutrition, hydration and recovery-timing item."""

    CHEST_PAIN = "CHEST_PAIN"
    SHORTNESS_OF_BREATH = "SHORTNESS_OF_BREATH"
    FAINTING_OR_DIZZINESS = "FAINTING_OR_DIZZINESS"
    DARK_URINE = "DARK_URINE"
    SEVERE_SWELLING = "SEVERE_SWELLING"
    NUMBNESS_OR_TINGLING = "NUMBNESS_OR_TINGLING"
    SUDDEN_SEVERE_PAIN = "SUDDEN_SEVERE_PAIN"


class Allergen(StrEnum):
    """The nine major food allergens the FDA names (FALCPA and the FASTER Act)."""

    MILK = "MILK"
    EGG = "EGG"
    FISH = "FISH"
    CRUSTACEAN_SHELLFISH = "CRUSTACEAN_SHELLFISH"
    TREE_NUTS = "TREE_NUTS"
    PEANUTS = "PEANUTS"
    WHEAT = "WHEAT"
    SOY = "SOY"
    SESAME = "SESAME"


# The most items a request may carry. A warning sign or an allergen can be given once, so
# their caps are the number of values there are; the discomfort cap is a product limit
# that keeps one request's work small.
MAX_DISCOMFORT_REPORTS = 10
MAX_WARNING_SIGNS = len(WarningSign)
MAX_ALLERGENS = len(Allergen)

# Strict: a JSON integer only. "5", 5.5 and true would otherwise be read as a severity.
Severity = Annotated[int, Field(strict=True, ge=0, le=10)]


class DiscomfortReport(BaseModel):
    """Where it hurts, what kind of discomfort it is, and how strongly (0 none, 10 worst)."""

    model_config = ConfigDict(extra="forbid")

    area: BodyArea
    kind: DiscomfortKind
    severity: Severity


class RecoverySummaryRequest(BaseModel):
    """What the user reports for one summary. All of it is optional, none of it is stored,
    and there is no free-text field: the user is the access token's, never the body's."""

    model_config = ConfigDict(extra="forbid")

    discomfort: list[DiscomfortReport] = Field(
        default_factory=list, max_length=MAX_DISCOMFORT_REPORTS
    )
    warning_signs: list[WarningSign] = Field(default_factory=list, max_length=MAX_WARNING_SIGNS)
    avoid_allergens: list[Allergen] = Field(default_factory=list, max_length=MAX_ALLERGENS)

    @field_validator("discomfort")
    @classmethod
    def check_discomfort_unique(cls, reports: list[DiscomfortReport]) -> list[DiscomfortReport]:
        """One report for each area and kind; the same area may have soreness and pain."""
        pairs = [(report.area, report.kind) for report in reports]
        if len(set(pairs)) != len(pairs):
            raise ValueError("report each area and kind of discomfort once")
        return reports

    @field_validator("warning_signs")
    @classmethod
    def check_warning_signs_unique(cls, signs: list[WarningSign]) -> list[WarningSign]:
        if len(set(signs)) != len(signs):
            raise ValueError("give each warning sign once")
        return signs

    @field_validator("avoid_allergens")
    @classmethod
    def check_allergens_unique(cls, allergens: list[Allergen]) -> list[Allergen]:
        if len(set(allergens)) != len(allergens):
            raise ValueError("give each allergen once")
        return allergens


# The response is built by the service from the app.guidance dataclasses, so its models
# also reject unknown fields: a typo there fails at once instead of dropping a value.
# Texts such as SafetyNotice.message and GuidanceNote.text are Formiq's own fixed text,
# never the user's.
SafetyStatusName = Literal["OK", "CAUTION", "SEEK_MEDICAL_CARE"]
MuscleStatusName = Literal["REST", "ALSO_WORKED", "SEE_PROFESSIONAL"]
GoalCategoryName = Literal["BUILD_MUSCLE", "LOSE_FAT", "GENERAL", "UNRECOGNISED"]
PreferenceStatusName = Literal["APPLIED", "NOT_SET", "NOT_RECOGNISED"]
DietPatternName = Literal["VEGAN", "VEGETARIAN", "EGGETARIAN", "PESCATARIAN", "NO_RESTRICTION"]


class SafetyNotice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    source_ids: list[str]


class SafetySummary(BaseModel):
    """How far the summary can go. SEEK_MEDICAL_CARE withholds every estimate, hydration,
    food and recovery-timing item and leaves only the calculated facts."""

    model_config = ConfigDict(extra="forbid")

    status: SafetyStatusName
    notices: list[SafetyNotice]


class ExerciseStatus(StrEnum):
    """What the session recorded for an exercise: completed sets, sets none of which were
    completed, or no sets at all (a timed exercise has none)."""

    TRAINED = "TRAINED"
    LOGGED_WITHOUT_SETS = "LOGGED_WITHOUT_SETS"
    SKIPPED = "SKIPPED"


class ExerciseSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_exercise_id: int
    exercise_id: int
    name: str
    section: WorkoutSection
    status: ExerciseStatus
    sets_logged: int
    completed_sets: int
    total_reps: int
    # None, never 0, when no completed set has a weight (or an rpe)
    volume_kg: float | None
    average_rpe: float | None


class MuscleTrained(BaseModel):
    """A muscle group worked in the main workout. role is PRIMARY if it is the primary
    muscle of any counted exercise."""

    model_config = ConfigDict(extra="forbid")

    muscle: str
    role: MuscleRole
    completed_sets: int
    exercises: list[str]


class ProfileValuesUsed(BaseModel):
    """The profile values the estimates were computed from, so each can be checked."""

    model_config = ConfigDict(extra="forbid")

    weight_kg: float
    age: int
    bmi: float | None
    goal: str | None
    goal_category: GoalCategoryName
    dietary_preference: str | None
    sleep_hours: float | None


class CalculatedFacts(BaseModel):
    """Exact arithmetic on recorded data, with no assumption beyond its accuracy."""

    model_config = ConfigDict(extra="forbid")

    duration_minutes: float | None
    duration_plausible: bool
    exercises: list[ExerciseSummary]
    completed_sets: int
    total_reps: int
    volume_kg: float | None
    muscles_trained: list[MuscleTrained]
    # None when the user has no profile
    profile_values_used: ProfileValuesUsed | None


class EstimateRange(BaseModel):
    """A published coefficient applied to recorded data: always a range, with the
    arithmetic (basis), what it assumes, and where it comes from."""

    model_config = ConfigDict(extra="forbid")

    low: int
    high: int
    unit: str
    basis: str
    applies_if: str | None
    assumptions: list[str]
    source_ids: list[str]

    @model_validator(mode="after")
    def check_range(self) -> Self:
        if self.low > self.high:
            raise ValueError("an estimate's low is never above its high")
        return self


class Estimates(BaseModel):
    """Each estimate, or None where the rules withheld it (see missing_data)."""

    model_config = ConfigDict(extra="forbid")

    post_workout_protein_g: EstimateRange | None = None
    daily_protein_g: EstimateRange | None = None
    daily_carbohydrate_g: EstimateRange | None = None
    rapid_refuel_carbohydrate_g_per_hour: EstimateRange | None = None
    active_energy_kcal: EstimateRange | None = None


class GuidanceNote(BaseModel):
    """One piece of general guidance. It holds no number computed from the user's data."""

    model_config = ConfigDict(extra="forbid")

    code: str
    text: str
    source_ids: list[str]


class MuscleRecoveryPlan(BaseModel):
    """What a muscle needs. Only REST has a window: a muscle for a professional, or one
    only worked as a supporting muscle, never has a rest time or a return-to-training time."""

    model_config = ConfigDict(extra="forbid")

    muscle: str
    # None for a muscle the user reported but did not train in this workout
    role: MuscleRole | None
    status: MuscleStatusName
    rest_hours: int | None
    rest_until: datetime | None
    reasons: list[str]
    source_ids: list[str]

    @model_validator(mode="after")
    def check_window(self) -> Self:
        has_window = self.rest_hours is not None and self.rest_until is not None
        has_none = self.rest_hours is None and self.rest_until is None
        if self.status == "REST" and not has_window:
            raise ValueError("a muscle that rests has rest_hours and rest_until")
        if self.status != "REST" and not has_none:
            raise ValueError("only a muscle that rests has rest_hours and rest_until")
        return self


class RecoveryGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    muscles: list[MuscleRecoveryPlan]
    general: list[GuidanceNote]


class FoodItemOut(BaseModel):
    """One food example. Amounts are floats (a Decimal would be sent as a string)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    serving: str
    protein_g: float
    carbohydrate_g: float
    suits: list[str]
    contains: list[str]
    allergens: list[Allergen]
    source_id: str


class FoodSuggestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preference_status: PreferenceStatusName
    dietary_pattern: DietPatternName | None
    allergens_excluded: list[Allergen]
    items: list[FoodItemOut]
    caveats: list[str]


class Guidance(BaseModel):
    """General guidance, with no user-specific number. recovery and food_suggestions are
    None and the lists empty when a warning sign withholds guidance."""

    model_config = ConfigDict(extra="forbid")

    post_workout_carbohydrate: list[GuidanceNote] = Field(default_factory=list)
    hydration: list[GuidanceNote] = Field(default_factory=list)
    # Formiq never measures fluid loss, so it never states a fluid volume: always False.
    fluid_loss_measured: Literal[False] = False
    sleep: GuidanceNote | None = None
    recovery: RecoveryGuidance | None = None
    food_suggestions: FoodSuggestions | None = None


class MissingData(BaseModel):
    """An input that was missing or out of range, and what is not given because of it."""

    model_config = ConfigDict(extra="forbid")

    field: str
    effect: str


class SourceReference(BaseModel):
    """A published source cited in this response."""

    model_config = ConfigDict(extra="forbid")

    id: str
    citation: str
    url: str


class RecoverySummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: int
    completed_at: datetime
    hours_since_completed: float
    safety: SafetySummary
    calculated: CalculatedFacts
    estimates: Estimates
    guidance: Guidance
    missing_data: list[MissingData]
    # only the sources cited in this response
    sources: list[SourceReference]
