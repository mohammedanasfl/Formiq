"""Tests for the nutrition rules (app.guidance.nutrition) and the guidance package's
purity. Pure functions: no database, no clock, no model."""

import ast
import inspect
import math
import re
import subprocess
import sys
from pathlib import Path

import pytest

import app
from app.guidance import foods, nutrition, recovery, sources
from app.guidance.nutrition import (
    ADULT_NOTE,
    ENERGY_NOTE,
    LOSE_FAT_NOTE,
    TOTAL_WEIGHT_NOTE,
    UNRECOGNISED_GOAL_NOTE,
    Estimate,
    GoalCategory,
    Profile,
    Withheld,
    active_energy,
    bmi,
    daily_carbohydrate,
    daily_protein,
    duration_is_plausible,
    has_valid_weight,
    hydration_items,
    is_adult,
    normalise_goal,
    post_workout_carbohydrate_items,
    post_workout_protein,
    rapid_refuel,
    round_half_up,
)
from app.guidance.sources import SOURCES, SourceId, cited_sources

ATHLETE = Profile(weight_kg=72.0, age=30, height_cm=175.0, goal="build_muscle")


def protein(profile=ATHLETE, counted=2, hours=1.0):
    return post_workout_protein(profile, counted_exercises=counted, hours_since_completed=hours)


def carbohydrate(profile=ATHLETE, minutes=55.0):
    return daily_carbohydrate(profile, duration_minutes=minutes)


def refuel(profile=ATHLETE, minutes=55.0, hours=1.0):
    return rapid_refuel(profile, duration_minutes=minutes, hours_since_completed=hours)


def energy(profile=ATHLETE, minutes=55.0):
    return active_energy(profile, duration_minutes=minutes)


# Each estimate, called with a profile and with everything else valid.
ESTIMATES = {
    "post_workout_protein": lambda profile: protein(profile),
    "daily_protein": lambda profile: daily_protein(profile),
    "daily_carbohydrate": lambda profile: carbohydrate(profile),
    "rapid_refuel": lambda profile: refuel(profile),
    "active_energy": lambda profile: energy(profile),
}


def the(result) -> Estimate:
    assert isinstance(result, Estimate), result
    return result


# arithmetic and rounding


def test_a_72_kg_muscle_gainer_gets_the_planned_ranges():
    assert (the(protein()).low, the(protein()).high) == (18, 29)
    assert (the(daily_protein(ATHLETE)).low, the(daily_protein(ATHLETE)).high) == (115, 144)
    assert (the(carbohydrate()).low, the(carbohydrate()).high) == (216, 360)
    assert (the(refuel()).low, the(refuel()).high) == (72, 86)
    assert (the(energy()).low, the(energy()).high) == (160, 330)


def test_each_estimate_shows_its_arithmetic_and_its_units():
    assert the(protein()).basis == "0.25-0.40 g/kg x 72.0 kg recorded body weight"
    assert the(protein()).unit == "g"
    assert the(daily_protein(ATHLETE)).basis == "1.6-2.0 g/kg/day x 72.0 kg recorded body weight"
    assert the(carbohydrate()).basis == "3-5 g/kg/day x 72.0 kg recorded body weight"
    assert the(refuel()).unit == "g/h"
    assert "1.0-1.2 g/kg/h x 72.0 kg" in the(refuel()).basis
    assert the(energy()).basis == "(MET 3.5 - 1) to (MET 6.0 - 1) x 72.0 kg x 55 min / 60"
    assert the(energy()).unit == "kcal"


def test_integers_round_half_up_not_to_even():
    assert [round_half_up(value) for value in (0.49, 0.5, 1.5, 2.5, 10.5, 11.5)] == [
        0, 1, 2, 3, 11, 12,
    ]
    # round(10.5) is 10: a 42 kg body at 0.25 g/kg is exactly 10.5 g
    assert the(protein(Profile(weight_kg=42.0, age=30))).low == 11


def test_per_kg_arithmetic_is_exact_for_a_weight_with_decimals():
    # 70.2 x 0.4 = 28.08 (a float would give 28.080000000000002)
    result = the(protein(Profile(weight_kg=70.2, age=30)))
    assert (result.low, result.high) == (18, 28)
    assert "70.2 kg" in result.basis
    assert "72.25 kg" in the(protein(Profile(weight_kg=72.25, age=30))).basis


def test_the_energy_range_rounds_down_then_up_to_10_kcal():
    # 2.5 x 72 x 55/60 = 165 and 5 x 72 x 55/60 = 330
    assert (the(energy()).low, the(energy()).high) == (160, 330)
    # exact multiples stay put: 2.5 x 80 = 200 and 5 x 80 = 400
    exact = the(energy(Profile(weight_kg=80.0, age=30), minutes=60))
    assert (exact.low, exact.high) == (200, 400)
    # 2.5 x 40.4 = 101 rounds down to 100; 5 x 40.4 = 202 rounds up to 210
    off = the(energy(Profile(weight_kg=40.4, age=30), minutes=60))
    assert (off.low, off.high) == (100, 210)


# goal normalisation


@pytest.mark.parametrize(
    "goal, category",
    [
        ("muscle_gain", GoalCategory.BUILD_MUSCLE),
        ("build_muscle", GoalCategory.BUILD_MUSCLE),
        ("fat_loss", GoalCategory.LOSE_FAT),
        ("lose_weight", GoalCategory.LOSE_FAT),
        ("general_fitness", GoalCategory.GENERAL),
        ("Muscle Gain", GoalCategory.BUILD_MUSCLE),
        ("  FAT-LOSS ", GoalCategory.LOSE_FAT),
        ("General  Fitness", GoalCategory.GENERAL),
        ("lose-weight", GoalCategory.LOSE_FAT),
        ("marathon", GoalCategory.UNRECOGNISED),
        ("", GoalCategory.UNRECOGNISED),
        (None, GoalCategory.UNRECOGNISED),
    ],
)
def test_goals_are_normalised(goal, category):
    assert normalise_goal(goal) is category


@pytest.mark.parametrize(
    "goal, band",
    [
        ("muscle_gain", (115, 144)),
        ("build_muscle", (115, 144)),
        ("fat_loss", (115, 144)),
        ("lose_weight", (115, 144)),
        ("general_fitness", (101, 144)),
        ("something else", (101, 144)),
        (None, (101, 144)),
    ],
)
def test_the_daily_protein_band_follows_the_goal(goal, band):
    result = the(daily_protein(Profile(weight_kg=72.0, age=30, goal=goal)))
    assert (result.low, result.high) == band


def test_an_unrecognised_goal_gets_the_default_band_and_a_note():
    assert UNRECOGNISED_GOAL_NOTE in the(daily_protein(Profile(72.0, 30, goal="yoga"))).assumptions
    assert UNRECOGNISED_GOAL_NOTE in the(daily_protein(Profile(72.0, 30))).assumptions
    for goal in ("general_fitness", "build_muscle", "fat_loss"):
        known = the(daily_protein(Profile(72.0, 30, goal=goal)))
        assert UNRECOGNISED_GOAL_NOTE not in known.assumptions


def test_the_note_about_an_unrecognised_goal_does_not_echo_it():
    note = the(daily_protein(Profile(72.0, 30, goal="my secret goal"))).assumptions
    assert not any("secret" in item for item in note)


# the duration bands and the plausible duration


@pytest.mark.parametrize(
    "minutes, band",
    [
        (5, (108, 180)),
        (30, (108, 180)),
        (59, (108, 180)),
        (59.9, (108, 180)),
        (60, (180, 252)),
        (90, (180, 252)),
        (240, (180, 252)),
    ],
)
def test_the_carbohydrate_band_follows_the_session_length(minutes, band):
    result = the(carbohydrate(Profile(weight_kg=36.0, age=30), minutes=minutes))
    assert (result.low, result.high) == band


@pytest.mark.parametrize("minutes", [None, 0, 4.9, 240.1, 600, -5])
def test_an_implausible_duration_withholds_the_duration_estimates(minutes):
    for result in (
        carbohydrate(minutes=minutes),
        refuel(minutes=minutes),
        energy(minutes=minutes),
    ):
        assert isinstance(result, Withheld)
        assert result.field == "duration_minutes"
    # the estimates that need no duration are unaffected
    assert isinstance(protein(), Estimate)
    assert isinstance(daily_protein(ATHLETE), Estimate)


@pytest.mark.parametrize(
    "minutes, plausible", [(4.9, False), (5, True), (240, True), (240.1, False)]
)
def test_the_plausible_duration_is_5_to_240_minutes(minutes, plausible):
    assert duration_is_plausible(minutes) is plausible
    assert duration_is_plausible(None) is False


# the gates


@pytest.mark.parametrize("weight, valid", [(29.9, False), (30, True), (300, True), (300.1, False)])
def test_a_weight_is_valid_from_30_to_300_kg_inclusive(weight, valid):
    assert has_valid_weight(weight) is valid
    for name, estimate in ESTIMATES.items():
        result = estimate(Profile(weight_kg=weight, age=30))
        assert isinstance(result, Estimate) is valid, name
        if not valid:
            assert result.field == "weight_kg", name


@pytest.mark.parametrize("weight", [None, 0, -70, math.nan, math.inf])
def test_no_usable_weight_gives_no_per_kg_estimate(weight):
    for name, estimate in ESTIMATES.items():
        result = estimate(Profile(weight_kg=weight, age=30))
        assert isinstance(result, Withheld), name
        assert result.field == "weight_kg", name


@pytest.mark.parametrize(
    "age, adult", [(None, False), (17, False), (18, True), (59, True), (60, True)]
)
def test_an_adult_is_18_or_older(age, adult):
    assert is_adult(age) is adult
    for name in ("post_workout_protein", "daily_protein", "daily_carbohydrate", "rapid_refuel"):
        result = ESTIMATES[name](Profile(weight_kg=72.0, age=age))
        assert isinstance(result, Estimate) is adult, name
        if not adult:
            assert result.field == "age", name
            assert "adult" in result.effect or "age" in result.effect, name


@pytest.mark.parametrize(
    "age, given",
    [(17, False), (18, False), (19, True), (59, True), (60, False), (75, False)],
)
def test_the_energy_range_is_for_ages_19_to_59_only(age, given):
    result = energy(Profile(weight_kg=72.0, age=age))
    assert isinstance(result, Estimate) is given
    if not given:
        assert result.field == "age"
    # the other targets stay for an older adult
    if age >= 18:
        assert isinstance(daily_protein(Profile(weight_kg=72.0, age=age)), Estimate)
        assert isinstance(protein(Profile(weight_kg=72.0, age=age)), Estimate)


def test_an_unknown_age_gives_no_estimate():
    assert isinstance(daily_protein(Profile(weight_kg=72.0)), Withheld)
    assert isinstance(energy(Profile(weight_kg=72.0)), Withheld)


def test_no_profile_gives_no_estimate_and_says_why():
    for name, estimate in ESTIMATES.items():
        result = estimate(Profile())
        assert isinstance(result, Withheld), name
        assert result.field == "weight_kg"
        assert result.effect


@pytest.mark.parametrize(
    "hours, given", [(0, True), (23.9, True), (24, True), (24.01, False), (72, False)]
)
def test_the_post_workout_estimates_are_withheld_after_24_hours(hours, given):
    assert isinstance(protein(hours=hours), Estimate) is given
    assert isinstance(refuel(hours=hours), Estimate) is given
    if not given:
        assert protein(hours=hours).field == "hours_since_completed"
        assert refuel(hours=hours).field == "hours_since_completed"
    # the daily targets and the energy range stay
    assert isinstance(daily_protein(ATHLETE), Estimate)
    assert isinstance(carbohydrate(), Estimate)
    assert isinstance(energy(), Estimate)


def test_nothing_counted_gives_no_post_workout_protein():
    result = protein(counted=0)
    assert isinstance(result, Withheld)
    assert result.field == "exercises"
    # only the protein dose needs a counted exercise
    assert isinstance(protein(counted=1), Estimate)
    assert isinstance(refuel(), Estimate)


def test_a_withheld_result_names_the_input_and_what_is_not_given():
    result = protein(Profile(weight_kg=20.0, age=30))
    assert result == Withheld(
        "weight_kg",
        "the recorded body weight is outside 30-300 kg, so a post-workout protein range "
        "is not given",
    )


# never a guess, never a single number


def test_low_is_never_above_high_and_the_energy_range_is_never_a_single_number():
    for weight in (30, 30.5, 42, 55.5, 72, 99.9, 180, 300):
        for age in (19, 30, 59):
            for minutes in (5, 20, 59.9, 60, 90, 240):
                profile = Profile(weight_kg=weight, age=age, goal="fat_loss")
                for name, make in {
                    "protein": lambda p: protein(p),
                    "daily_protein": lambda p: daily_protein(p),
                    "carbohydrate": lambda p: carbohydrate(p, minutes),
                    "refuel": lambda p: refuel(p, minutes),
                    "energy": lambda p: energy(p, minutes),
                }.items():
                    result = the(make(profile))
                    assert result.low <= result.high, (name, weight, minutes)
                energy_range = the(energy(profile, minutes))
                assert energy_range.low < energy_range.high, (weight, age, minutes)
                assert energy_range.low % 10 == 0 and energy_range.high % 10 == 0


def test_an_estimate_refuses_a_low_above_its_high():
    with pytest.raises(ValueError):
        Estimate(10, 5, "g", "basis", None, (), ())


def test_no_estimate_is_a_calorie_intake_target():
    # the only energy figure is what the session used, and it says so
    assert the(energy()).unit == "kcal"
    assert ENERGY_NOTE in the(energy()).assumptions
    assert "never a food target" in ENERGY_NOTE
    for name, estimate in ESTIMATES.items():
        result = the(estimate(ATHLETE))
        assert result.unit in {"g", "g/day", "g/h", "kcal"}
        if name != "active_energy":
            assert result.unit != "kcal"


# assumptions


def test_every_estimate_carries_the_adult_and_total_weight_assumptions():
    for name, estimate in ESTIMATES.items():
        assumptions = the(estimate(ATHLETE)).assumptions
        assert ADULT_NOTE in assumptions, name
        assert TOTAL_WEIGHT_NOTE in assumptions, name
    assert "kidney disease" in ADULT_NOTE and "pregnancy" in ADULT_NOTE
    assert "breastfeeding" in ADULT_NOTE and "medical nutrition therapy" in ADULT_NOTE


@pytest.mark.parametrize(
    "weight, height, expected",
    [(120.0, 200.0, True), (119.5, 200.0, False), (92.0, 175.0, True), (72.0, 175.0, False)],
)
def test_a_bmi_of_30_or_more_adds_its_note(weight, height, expected):
    for name, estimate in ESTIMATES.items():
        assumptions = the(estimate(Profile(weight_kg=weight, age=30, height_cm=height))).assumptions
        has_note = any("BMI is" in item and "overestimate" in item for item in assumptions)
        assert has_note is expected, name


def test_the_bmi_note_is_left_out_without_a_height():
    assumptions = the(daily_protein(Profile(weight_kg=150.0, age=30))).assumptions
    assert not any("BMI" in item for item in assumptions)


def test_the_bmi_note_names_the_bmi():
    assumptions = the(daily_protein(Profile(weight_kg=120.0, age=30, height_cm=200.0))).assumptions
    assert "Your BMI is 30.0 (30 or more): per-kg values may overestimate for you." in assumptions


@pytest.mark.parametrize("goal", ["fat_loss", "lose_weight", "Lose Weight"])
def test_a_fat_loss_goal_adds_the_note_that_these_ranges_are_not_a_plan(goal):
    for name, estimate in ESTIMATES.items():
        assert LOSE_FAT_NOTE in the(estimate(Profile(72.0, 30, goal=goal))).assumptions, name
    assert "not a fat-loss plan" in LOSE_FAT_NOTE
    assert "Formiq sets no calorie target" in LOSE_FAT_NOTE


@pytest.mark.parametrize("goal", ["muscle_gain", "general_fitness", None, "yoga"])
def test_the_fat_loss_note_is_only_for_a_fat_loss_goal(goal):
    for name, estimate in ESTIMATES.items():
        assert LOSE_FAT_NOTE not in the(estimate(Profile(72.0, 30, goal=goal))).assumptions, name


def test_the_post_workout_protein_dose_is_one_meal_or_snack_of_high_quality_protein():
    assumptions = the(protein()).assumptions
    assert any("high-quality" in item for item in assumptions)
    assert any("one meal or snack" in item and "2 hours" in item for item in assumptions)


def test_rapid_refuel_applies_only_if_training_hard_again_within_8_hours():
    assert the(refuel()).applies_if == "you train hard again within 8 hours"
    assert "first 4 hours" in the(refuel()).basis
    for name, estimate in ESTIMATES.items():
        if name != "rapid_refuel":
            assert the(estimate(ATHLETE)).applies_if is None, name


def test_the_carbohydrate_band_is_chosen_by_this_sessions_length_and_says_so():
    assert any("session's length" in item for item in the(carbohydrate()).assumptions)


# BMI


def test_bmi_is_calculated_to_one_decimal():
    assert bmi(72.0, 175.0) == 23.5
    assert bmi(120.0, 200.0) == 30.0
    # 77.3 / 1.7^2 = 26.747...
    assert bmi(77.3, 170.0) == 26.7


@pytest.mark.parametrize(
    "weight, height",
    [
        (None, 175.0),
        (29.9, 175.0),
        (300.1, 175.0),
        (72.0, None),
        (72.0, 0),
        (72.0, -170.0),
        (72.0, math.nan),
    ],
)
def test_bmi_needs_a_valid_weight_and_a_height(weight, height):
    assert bmi(weight, height) is None


# hydration: fixed text, never a computed volume


def test_hydration_guidance_says_fluid_loss_was_not_measured():
    assert nutrition.FLUID_LOSS_MEASURED is False
    items = hydration_items()
    assert items[0].code == "HYDRATION_NOT_MEASURED"
    assert "did not measure" in items[0].text


def test_hydration_items_take_nothing_in_so_they_cannot_depend_on_the_user():
    assert inspect.signature(hydration_items).parameters == {}
    assert hydration_items() == hydration_items()


SELF_CHECK = "1.25-1.5 L of fluid for every 1 kg lost"


def test_hydration_items_contain_no_computed_volume():
    texts = [item.text for item in hydration_items()]
    # the one per-kg figure is a self-check the user applies to their own weighing
    assert sum(SELF_CHECK in text for text in texts) == 1
    for text in texts:
        remaining = text.replace(SELF_CHECK, "")
        assert not re.search(r"\d", remaining), remaining
        units = r"\b(ml|mL|litres?|liters?|cups?|glass(es)?|oz)\b"
        assert not re.search(units, remaining), remaining
    # and it is not multiplied by the user's weight: no weight-derived figure appears anywhere
    for weight in (50, 72, 100):
        assert not any(str(round(weight * 1.5)) in text for text in texts)
        assert not any(str(round(weight * 1.25)) in text for text in texts)


def test_hydration_items_cover_the_planned_advice_with_codes_and_sources():
    items = hydration_items()
    codes = [item.code for item in items]
    assert len(set(codes)) == len(codes)
    text = " ".join(item.text for item in items)
    for phrase in ("meals", "thirst", "Pale-yellow", "Salty foods", "hyponatraemia", "weighed"):
        assert phrase in text
    for item in items:
        assert item.source_ids, item.code
        assert set(item.source_ids) <= {SourceId.ACSM_FLUID_2007, SourceId.ACSM_NUTRITION_2016}


def test_post_workout_carbohydrate_guidance_has_no_number_of_its_own():
    for item in post_workout_carbohydrate_items():
        assert item.source_ids
        assert not re.search(r"\d+\s*(g|kcal|L|ml)\b", item.text)


# sources


def test_every_source_an_estimate_cites_is_registered():
    registered = {source.id for source in SOURCES}
    for name, estimate in ESTIMATES.items():
        result = the(estimate(ATHLETE))
        assert result.source_ids, name
        assert set(result.source_ids) <= registered, name
        assert len(cited_sources(result.source_ids)) == len(set(result.source_ids))
    for item in (*hydration_items(), *post_workout_carbohydrate_items()):
        assert set(item.source_ids) <= registered


def test_the_estimates_cite_the_sources_their_numbers_come_from():
    assert SourceId.ISSN_TIMING_2017 in the(protein()).source_ids
    assert SourceId.SCHOENFELD_ARAGON_2018 in the(protein()).source_ids
    assert SourceId.MORTON_2018 in the(daily_protein(ATHLETE)).source_ids
    # the general band is ISSN's alone
    general = the(daily_protein(Profile(72.0, 30, goal="general_fitness")))
    assert general.source_ids == (SourceId.ISSN_PROTEIN_2017,)
    assert the(carbohydrate()).source_ids == (SourceId.ACSM_NUTRITION_2016,)
    assert the(refuel()).source_ids == (SourceId.ACSM_NUTRITION_2016,)
    assert the(energy()).source_ids == (SourceId.COMPENDIUM_2024,)


def test_cited_sources_lists_each_cited_source_once_in_registry_order():
    cited = cited_sources(
        [SourceId.USDA_FDC, SourceId.ISSN_PROTEIN_2017, "USDA_FDC", SourceId.ISSN_PROTEIN_2017]
    )
    assert [source.id for source in cited] == [SourceId.ISSN_PROTEIN_2017, SourceId.USDA_FDC]
    assert cited_sources([]) == ()


def test_an_unregistered_source_id_is_a_bug_not_a_gap():
    with pytest.raises(ValueError):
        cited_sources(["NOT_A_SOURCE"])


def test_every_registered_source_has_a_citation_and_a_link():
    assert len({source.id for source in SOURCES}) == len(SOURCES) == len(SourceId)
    for source in SOURCES:
        assert len(source.citation) > 30, source.id
        assert source.url.startswith("https://"), source.id


# the guidance package imports no data and reads no clock

GUIDANCE_MODULES = [nutrition, recovery, foods, sources]
APP_ROOT = Path(app.__file__).parent
FORBIDDEN_IMPORTS = (
    "sqlalchemy",
    "app.db",
    "app.models",
    "app.repositories",
    "app.services",
    "app.agent",
    "app.ai",
    "app.tools",
    "app.core",
    "app.api",
    "app.approvals",
    "app.observability",
)
# the only application modules a guidance module may import
ALLOWED_APP_IMPORTS = ("app.guidance", "app.schemas.recovery_summary", "app.schemas.exercise")


def imported_names(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }


@pytest.mark.parametrize("module", GUIDANCE_MODULES, ids=lambda module: module.__name__)
def test_the_guidance_modules_have_no_access_to_data(module):
    imported = {name for name in imported_names(module) if name}
    for forbidden in FORBIDDEN_IMPORTS:
        assert not any(name.startswith(forbidden) for name in imported), forbidden
    for name in imported:
        if name.startswith("app"):
            assert name.startswith(ALLOWED_APP_IMPORTS), name


@pytest.mark.parametrize("module", GUIDANCE_MODULES, ids=lambda module: module.__name__)
def test_the_guidance_modules_read_no_clock_and_use_no_randomness(module):
    source = inspect.getsource(module)
    for call in ("datetime.now", "utcnow", ".today(", "time.time", "monotonic"):
        assert call not in source, call
    assert not {"random", "secrets", "uuid", "os", "time"} & imported_names(module)


def test_importing_the_guidance_package_loads_no_data_layer_module():
    # the static check above covers each module's own imports; this one covers what they
    # import in turn, in a fresh interpreter
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(APP_ROOT.parent)!r})\n"
        "import app.guidance.nutrition, app.guidance.recovery, app.guidance.foods\n"
        "import app.guidance.sources\n"
        "bad = sorted(name for name in sys.modules if name.split('.')[0] == 'sqlalchemy' or "
        f"name.startswith({FORBIDDEN_IMPORTS[1:]!r}))\n"
        "print(','.join(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""
