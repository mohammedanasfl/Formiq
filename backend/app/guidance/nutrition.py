"""Post-workout nutrition, hydration and energy estimates: Formiq's own rules, so a
summary is calculated the same way whatever the request.

An estimate is a published per-kg or MET coefficient applied to the user's
recorded data. It is always a range, never a single number, and it carries its
basis (the arithmetic), its assumptions and its sources. When an input is
missing or out of range the rule returns Withheld, saying which input and what
is not given, and never guesses. Nothing here sets a calorie intake target, a
fluid volume or a supplement: the energy range describes what a session used.

Pure: no data access, no clock (the caller passes hours since completion), and
no randomness. Every coefficient names its source (app.guidance.sources); a
number the sources do not state is marked as a product rule.
"""

import math
import re
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.guidance.sources import GuidanceItem, SourceId

# Product gates. No source states these limits: they keep a wrong profile or a
# session left open from producing a confident-looking number.
MIN_WEIGHT_KG = 30
MAX_WEIGHT_KG = 300
ADULT_AGE = 18
MIN_DURATION_MINUTES = 5
MAX_DURATION_MINUTES = 240
# The anabolic effect of a session lasts at least 24 h and likely diminishes with
# time (ISSN_PROTEIN_2017); a post-workout dose is only suggested within that day.
# The cut-off itself is a product rule.
MAX_HOURS_SINCE_COMPLETION = 24
# COMPENDIUM_2024 is "tailored for adults 19-59 years of age" (Herrmann 2024), so the
# energy range is only given inside it; an 18-year-old still gets the other targets.
ENERGY_MIN_AGE = 19
ENERGY_MAX_AGE = 59
# Product rule: the BMI at which the total-body-weight note names the user's BMI.
BMI_NOTE_THRESHOLD = Decimal("30")

# Daily protein, g per kg of body weight (a coefficient is a Decimal, so the
# arithmetic is exact and rounds half up).
# 1.4-2.0: ISSN_PROTEIN_2017 ("1.4-2.0 g protein/kg body weight/day is sufficient for most
# exercising individuals").
GENERAL_PROTEIN_G_PER_KG = (Decimal("1.4"), Decimal("2.0"))
# 1.6 lower bound: MORTON_2018 (gains in muscle mass plateau at 1.62 g/kg/day, 95% CI
# 1.03-2.20); 2.0 upper bound: ISSN_PROTEIN_2017. ISSN also says 2.3-3.1 g/kg/day may be
# needed in resistance-trained people eating less than they use; Formiq gives no
# energy-deficit figure and sets no calorie target, so it does not show that band.
TRAINING_PROTEIN_G_PER_KG = (Decimal("1.6"), Decimal("2.0"))
# One post-workout dose, g per kg: 0.25-0.40 g/kg "of a high-quality source"
# (ISSN_TIMING_2017: "20-40 g protein dose (0.25-0.40 g/kg body mass/dose)"; 0.25 is
# ISSN_PROTEIN_2017's general figure and 0.4 is SCHOENFELD_ARAGON_2018's per-meal target).
POST_WORKOUT_PROTEIN_G_PER_KG = (Decimal("0.25"), Decimal("0.40"))
# Daily carbohydrate, g per kg per day (ACSM_NUTRITION_2016, Table 1: "Light" 3-5 and
# "Moderate, ~1 h/d" 5-7).
LIGHT_CARBOHYDRATE_G_PER_KG = (Decimal("3"), Decimal("5"))
MODERATE_CARBOHYDRATE_G_PER_KG = (Decimal("5"), Decimal("7"))
# UNVERIFIED: Table 1 chooses a row by the athlete's whole daily programme ("low
# intensity or skill-based" vs "~1 h/d"), not by one session's length. Choosing the row
# by this session's length (under 60 minutes, or 60 and over) is Formiq's mapping, and
# above ~1 h/d the table itself lists higher rows (6-10 g/kg/day for 1-3 h/d).
CARBOHYDRATE_BAND_MINUTES = 60
# Speedy refuelling (ACSM_NUTRITION_2016, Table 1): "< 8 h recovery between 2
# fuel-demanding sessions: 1-1.2 g/kg/h for first 4 h, then resume daily fuel needs".
RAPID_REFUEL_G_PER_KG_PER_HOUR = (Decimal("1.0"), Decimal("1.2"))
RAPID_REFUEL_HOURS = 4
RAPID_REFUEL_WINDOW_HOURS = 8
# MET range for resistance training, from the 2024 Adult Compendium (COMPENDIUM_2024):
# code 02054, 3.5, "Resistance (weight) training, multiple exercises, 8-15 reps at varied
# resistance", to code 02050, 6.0, "Resistance (weight lifting - free weight, nautilus or
# universal-type), power lifting or body building, vigorous effort". The Compendium
# defines a MET as about 1.0 kcal/kg/h; active energy is (MET - 1) x kg x hours.
ENERGY_MET = (Decimal("3.5"), Decimal("6.0"))
# the energy range is rounded out to the nearest 10 kcal (low down, high up)
ENERGY_ROUNDING_KCAL = 10

ADULT_NOTE = (
    "Assumes a healthy adult. These ranges do not apply in kidney disease, pregnancy, "
    "breastfeeding or medical nutrition therapy."
)
TOTAL_WEIGHT_NOTE = "Per-kg values use your total recorded body weight."
LOSE_FAT_NOTE = (
    "Your goal is fat loss: these ranges fuel training, they are not a fat-loss plan; "
    "Formiq sets no calorie target."
)
UNRECOGNISED_GOAL_NOTE = (
    "Your recorded goal is not one Formiq recognises, so the general protein band is used."
)
PROTEIN_SOURCE_NOTE = "Assumes a high-quality protein source."
# ISSN_TIMING_2017: "Post-exercise ingestion (immediately to 2-h post) of high-quality
# protein sources stimulates robust increases in MPS"
PROTEIN_TIMING_NOTE = (
    "Meant as one meal or snack, from straight after training to about 2 hours after."
)
CARBOHYDRATE_BAND_NOTE = (
    "The band follows this session's length: under 60 minutes uses the 3-5 g/kg/day row, "
    "60 minutes or more the 5-7 g/kg/day row, of a table written for athletes."
)
ENERGY_NOTE = (
    "Assumes 1 MET is about 1 kcal per kg per hour, and counts the whole session length, "
    "rests included. It is an estimate of energy used, never a food target."
)


class GoalCategory(StrEnum):
    BUILD_MUSCLE = "BUILD_MUSCLE"
    LOSE_FAT = "LOSE_FAT"
    GENERAL = "GENERAL"
    UNRECOGNISED = "UNRECOGNISED"


# The goals in use in profiles, in the form normalise_goal reduces a goal to.
GOAL_ALIASES = {
    "muscle_gain": GoalCategory.BUILD_MUSCLE,
    "build_muscle": GoalCategory.BUILD_MUSCLE,
    "fat_loss": GoalCategory.LOSE_FAT,
    "lose_weight": GoalCategory.LOSE_FAT,
    "general_fitness": GoalCategory.GENERAL,
}


def normalise_goal(goal: str | None) -> GoalCategory:
    """The category of a profile's free-text goal, ignoring case, spaces and hyphens."""
    if goal is None:
        return GoalCategory.UNRECOGNISED
    key = re.sub(r"[\s_-]+", "_", goal.strip().casefold())
    return GOAL_ALIASES.get(key, GoalCategory.UNRECOGNISED)


@dataclass(frozen=True)
class Profile:
    """The profile values the rules use; None where there is no profile or no value."""

    weight_kg: float | None = None
    age: int | None = None
    height_cm: float | None = None
    goal: str | None = None


@dataclass(frozen=True)
class Estimate:
    """A published coefficient applied to recorded data. low <= high, always."""

    low: int
    high: int
    unit: str
    basis: str
    applies_if: str | None
    assumptions: tuple[str, ...]
    source_ids: tuple[SourceId, ...]

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError("an estimate's low is never above its high")


@dataclass(frozen=True)
class Withheld:
    """Why a rule gave no estimate: the input that is missing or out of range, and
    what is not given because of it. Never a guess."""

    field: str
    effect: str


def _decimal(value: float | int | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def round_half_up(value: float | int | Decimal) -> int:
    """An integer, with .5 rounded up (Python's round() rounds it to even)."""
    return int(_decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _round_to(value: Decimal, step: int, rounding: str) -> int:
    return int((value / step).to_integral_value(rounding=rounding)) * step


def has_valid_weight(weight_kg: float | None) -> bool:
    return weight_kg is not None and MIN_WEIGHT_KG <= weight_kg <= MAX_WEIGHT_KG


def is_adult(age: int | None) -> bool:
    return age is not None and age >= ADULT_AGE


def duration_is_plausible(minutes: float | None) -> bool:
    """A session left open would inflate its duration, so only 5 to 240 minutes counts."""
    return minutes is not None and MIN_DURATION_MINUTES <= minutes <= MAX_DURATION_MINUTES


def bmi(weight_kg: float | None, height_cm: float | None) -> float | None:
    """Body mass index to one decimal, or None without a valid weight and a height."""
    if not has_valid_weight(weight_kg) or height_cm is None:
        return None
    if not math.isfinite(height_cm) or height_cm <= 0:
        return None
    metres = _decimal(height_cm) / 100
    value = _decimal(weight_kg) / (metres * metres)
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _kg(weight_kg: float) -> str:
    weight = _decimal(weight_kg)
    tenths = weight.quantize(Decimal("0.1"))
    return str(tenths) if weight == tenths else f"{weight.normalize():f}"


def _plain(value: float | int | Decimal) -> str:
    return f"{_decimal(value).normalize():f}"


def _band(band: tuple[Decimal, Decimal]) -> str:
    return f"{band[0]}-{band[1]}"


def _checked_weight(profile: Profile, what: str) -> float | Withheld:
    """The weight every per-kg estimate needs, if it is valid and the person is an
    adult; otherwise why not."""
    weight = profile.weight_kg
    if weight is None:
        return Withheld("weight_kg", f"no body weight is recorded, so {what} is not given")
    if not has_valid_weight(weight):
        return Withheld(
            "weight_kg",
            f"the recorded body weight is outside {MIN_WEIGHT_KG}-{MAX_WEIGHT_KG} kg, "
            f"so {what} is not given",
        )
    if profile.age is None:
        return Withheld("age", f"no age is recorded, so {what} is not given")
    if not is_adult(profile.age):
        return Withheld("age", f"these targets are for adults, so {what} is not given")
    return weight


def _checked_duration(minutes: float | None, what: str) -> float | Withheld:
    if minutes is None:
        return Withheld(
            "duration_minutes", f"the session length is not known, so {what} is not given"
        )
    if not duration_is_plausible(minutes):
        return Withheld(
            "duration_minutes",
            f"the session length is not plausible ({MIN_DURATION_MINUTES} to "
            f"{MAX_DURATION_MINUTES} minutes), so {what} is not given",
        )
    return minutes


def _recency_gate(hours_since_completed: float, what: str) -> Withheld | None:
    if hours_since_completed > MAX_HOURS_SINCE_COMPLETION:
        return Withheld(
            "hours_since_completed",
            f"the workout finished more than {MAX_HOURS_SINCE_COMPLETION} hours ago, "
            f"so {what} is not given",
        )
    return None


def _assumptions(profile: Profile, *specific: str) -> tuple[str, ...]:
    """The assumptions every estimate carries, then the ones of this rule."""
    notes = [ADULT_NOTE, TOTAL_WEIGHT_NOTE]
    reading = bmi(profile.weight_kg, profile.height_cm)
    if reading is not None and _decimal(reading) >= BMI_NOTE_THRESHOLD:
        notes.append(
            f"Your BMI is {reading} (30 or more): per-kg values may overestimate for you."
        )
    if normalise_goal(profile.goal) is GoalCategory.LOSE_FAT:
        notes.append(LOSE_FAT_NOTE)
    return (*notes, *specific)


def _per_kg_range(weight_kg: float, band: tuple[Decimal, Decimal]) -> tuple[int, int]:
    weight = _decimal(weight_kg)
    return round_half_up(band[0] * weight), round_half_up(band[1] * weight)


def post_workout_protein(
    profile: Profile, *, counted_exercises: int, hours_since_completed: float
) -> Estimate | Withheld:
    """One post-workout protein dose, from 0.25 to 0.40 g/kg."""
    what = "a post-workout protein range"
    weight = _checked_weight(profile, what)
    if isinstance(weight, Withheld):
        return weight
    if counted_exercises < 1:
        return Withheld(
            "exercises", f"no main-workout exercise was counted, so {what} is not given"
        )
    if (late := _recency_gate(hours_since_completed, what)) is not None:
        return late
    low, high = _per_kg_range(weight, POST_WORKOUT_PROTEIN_G_PER_KG)
    return Estimate(
        low,
        high,
        "g",
        f"{_band(POST_WORKOUT_PROTEIN_G_PER_KG)} g/kg x {_kg(weight)} kg recorded body weight",
        None,
        _assumptions(profile, PROTEIN_SOURCE_NOTE, PROTEIN_TIMING_NOTE),
        (SourceId.ISSN_TIMING_2017, SourceId.ISSN_PROTEIN_2017, SourceId.SCHOENFELD_ARAGON_2018),
    )


def daily_protein(profile: Profile) -> Estimate | Withheld:
    """The day's protein: 1.6-2.0 g/kg to build muscle or lose fat, otherwise 1.4-2.0 g/kg."""
    weight = _checked_weight(profile, "a daily protein range")
    if isinstance(weight, Withheld):
        return weight
    category = normalise_goal(profile.goal)
    training = category in {GoalCategory.BUILD_MUSCLE, GoalCategory.LOSE_FAT}
    band = TRAINING_PROTEIN_G_PER_KG if training else GENERAL_PROTEIN_G_PER_KG
    low, high = _per_kg_range(weight, band)
    notes = (UNRECOGNISED_GOAL_NOTE,) if category is GoalCategory.UNRECOGNISED else ()
    # the 1.6 lower bound is Morton's; the general band is ISSN's alone
    sources = (SourceId.ISSN_PROTEIN_2017,) + ((SourceId.MORTON_2018,) if training else ())
    return Estimate(
        low,
        high,
        "g/day",
        f"{_band(band)} g/kg/day x {_kg(weight)} kg recorded body weight",
        None,
        _assumptions(profile, *notes),
        sources,
    )


def daily_carbohydrate(profile: Profile, *, duration_minutes: float | None) -> Estimate | Withheld:
    """The day's carbohydrate: 3-5 g/kg for a session under 60 minutes, 5-7 g/kg from 60."""
    what = "a daily carbohydrate range"
    weight = _checked_weight(profile, what)
    if isinstance(weight, Withheld):
        return weight
    minutes = _checked_duration(duration_minutes, what)
    if isinstance(minutes, Withheld):
        return minutes
    longer = minutes >= CARBOHYDRATE_BAND_MINUTES
    band = MODERATE_CARBOHYDRATE_G_PER_KG if longer else LIGHT_CARBOHYDRATE_G_PER_KG
    low, high = _per_kg_range(weight, band)
    return Estimate(
        low,
        high,
        "g/day",
        f"{_band(band)} g/kg/day x {_kg(weight)} kg recorded body weight",
        None,
        _assumptions(profile, CARBOHYDRATE_BAND_NOTE),
        (SourceId.ACSM_NUTRITION_2016,),
    )


def rapid_refuel(
    profile: Profile, *, duration_minutes: float | None, hours_since_completed: float
) -> Estimate | Withheld:
    """Carbohydrate per hour for the first 4 hours, only if training hard again within 8."""
    what = "a rapid-refuel range"
    weight = _checked_weight(profile, what)
    if isinstance(weight, Withheld):
        return weight
    minutes = _checked_duration(duration_minutes, what)
    if isinstance(minutes, Withheld):
        return minutes
    if (late := _recency_gate(hours_since_completed, what)) is not None:
        return late
    low, high = _per_kg_range(weight, RAPID_REFUEL_G_PER_KG_PER_HOUR)
    return Estimate(
        low,
        high,
        "g/h",
        f"{_band(RAPID_REFUEL_G_PER_KG_PER_HOUR)} g/kg/h x {_kg(weight)} kg recorded body "
        f"weight, for the first {RAPID_REFUEL_HOURS} hours after training",
        f"you train hard again within {RAPID_REFUEL_WINDOW_HOURS} hours",
        _assumptions(profile),
        (SourceId.ACSM_NUTRITION_2016,),
    )


def active_energy(profile: Profile, *, duration_minutes: float | None) -> Estimate | Withheld:
    """Energy the session used above rest: (MET - 1) x kg x hours, as a range in kcal."""
    what = "an active-energy range"
    weight = _checked_weight(profile, what)
    if isinstance(weight, Withheld):
        return weight
    if profile.age is None or not ENERGY_MIN_AGE <= profile.age <= ENERGY_MAX_AGE:
        return Withheld(
            "age",
            f"the energy values cover ages {ENERGY_MIN_AGE} to {ENERGY_MAX_AGE}, "
            f"so {what} is not given",
        )
    minutes = _checked_duration(duration_minutes, what)
    if isinstance(minutes, Withheld):
        return minutes
    low_met, high_met = ENERGY_MET
    kg_hours = _decimal(weight) * _decimal(minutes) / 60
    return Estimate(
        _round_to((low_met - 1) * kg_hours, ENERGY_ROUNDING_KCAL, ROUND_FLOOR),
        _round_to((high_met - 1) * kg_hours, ENERGY_ROUNDING_KCAL, ROUND_CEILING),
        "kcal",
        f"(MET {low_met} - 1) to (MET {high_met} - 1) x {_kg(weight)} kg x "
        f"{_plain(minutes)} min / 60",
        None,
        _assumptions(profile, ENERGY_NOTE),
        (SourceId.COMPENDIUM_2024,),
    )


# No fluid volume is ever computed: loss was not measured, so these are fixed text.
# The one per-kg figure is a self-check the user applies to their own weighing; it is
# never multiplied by anything.
FLUID_LOSS_MEASURED = False


def hydration_items() -> tuple[GuidanceItem, ...]:
    """General hydration guidance. It takes no arguments, so no item can depend on a
    user's weight or session."""
    return (
        GuidanceItem(
            "HYDRATION_NOT_MEASURED",
            "Formiq did not measure how much fluid you lost in this workout, so it gives no "
            "amount of fluid for you to drink.",
            # individual sweat rate is estimated by weighing before and after exercise
            (SourceId.ACSM_FLUID_2007,),
        ),
        GuidanceItem(
            "DRINK_WITH_MEALS_TO_THIRST",
            "Drink with your meals and to thirst over the next few hours.",
            (SourceId.ACSM_NUTRITION_2016,),
        ),
        GuidanceItem(
            "PALE_YELLOW_URINE",
            "Pale-yellow urine is a simple sign that you are drinking enough.",
            # UNVERIFIED: the source gives pale-yellow urine as the aim of drinking before
            # exercise, and urine specific gravity below 1.020 as euhydration; using the
            # colour as a check after training is a simplification.
            (SourceId.ACSM_NUTRITION_2016,),
        ),
        GuidanceItem(
            "SALTY_FOODS_KEEP_FLUID",
            "Salty foods help your body keep the fluid you drink.",
            (SourceId.ACSM_NUTRITION_2016,),
        ),
        GuidanceItem(
            "DO_NOT_OVERDRINK",
            "Do not drink far more than you lost: over-drinking can dilute the sodium in "
            "your blood (hyponatraemia).",
            (SourceId.ACSM_NUTRITION_2016,),
        ),
        GuidanceItem(
            "WEIGH_YOURSELF_CHECK",
            "If you weighed yourself before and after training, the guideline is about "
            "1.25-1.5 L of fluid for every 1 kg lost. Formiq has no before and after "
            "weights, so this is a check for you to make, not a number for you.",
            # 1.25-1.5 L per kg lost: ACSM_NUTRITION_2016 ("125 to 150% of the remaining
            # fluid deficit (e.g., 1.25 to 1.5 L fluid for every 1 kg BW lost)")
            (SourceId.ACSM_NUTRITION_2016, SourceId.ACSM_FLUID_2007),
        ),
    )


def post_workout_carbohydrate_items() -> tuple[GuidanceItem, ...]:
    """General carbohydrate guidance, with no number of its own: the numbers are the
    daily and rapid-refuel estimates."""
    return (
        GuidanceItem(
            "CARBOHYDRATE_REFILLS_FUEL",
            "Carbohydrate refills the fuel your muscles used. As long as the day's total is "
            "enough, you can choose foods and timing to suit you.",
            # ACSM_NUTRITION_2016: "As long as total intake of carbohydrate and energy is
            # adequate ... meals and snacks can be chosen ... according to personal
            # preferences of type and timing of intake"
            (SourceId.ACSM_NUTRITION_2016,),
        ),
        GuidanceItem(
            "CARBOHYDRATE_EARLY_IF_TRAINING_SOON",
            f"If you will train hard again within {RAPID_REFUEL_WINDOW_HOURS} hours, eat "
            "carbohydrate early in the recovery rather than waiting.",
            # ACSM_NUTRITION_2016, Table 1 "Speedy refuelling" and its recovery text
            (SourceId.ACSM_NUTRITION_2016,),
        ),
    )
