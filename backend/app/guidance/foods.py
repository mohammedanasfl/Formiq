"""Food examples that fit a diet pattern and avoid the allergens a user gives.

A small curated catalog, not a meal plan: each food has a serving, its protein and
carbohydrate, and what it contains. The values are USDA FoodData Central's (SR Legacy
data, one fdc_id per food): per 100 g as FDC states them, and the serving's gram weight
from FDC's own portion table, so the serving's amounts are exact arithmetic on them.
Nothing is chosen at random: the selection follows the catalog's order.

The diet patterns are Formiq's own definitions. VEGETARIAN is lacto-vegetarian and
leaves out eggs on purpose: in Indian usage a vegetarian does not eat egg, and leaving
it out is the conservative choice. Eggs are for EGGETARIAN (lacto-ovo). PESCATARIAN
eats fish, shellfish, dairy and eggs but no meat or poultry.

A food's tags describe the plain food as FDC records it: a commercial product may
differ, which is what the always-present check-labels caveat is for.

Pure: no data access, no randomness.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.guidance.sources import SourceId
from app.schemas.recovery_summary import Allergen

# Product choice: how many examples of each kind a summary shows.
MAX_PROTEIN_ITEMS = 4
MAX_CARBOHYDRATE_ITEMS = 3


class DietPattern(StrEnum):
    VEGAN = "VEGAN"
    VEGETARIAN = "VEGETARIAN"
    EGGETARIAN = "EGGETARIAN"
    PESCATARIAN = "PESCATARIAN"
    NO_RESTRICTION = "NO_RESTRICTION"


class PreferenceStatus(StrEnum):
    APPLIED = "APPLIED"
    NOT_SET = "NOT_SET"
    NOT_RECOGNISED = "NOT_RECOGNISED"


class AnimalSource(StrEnum):
    """The animal products a food contains: what a diet pattern rules out."""

    MEAT = "MEAT"
    POULTRY = "POULTRY"
    FISH = "FISH"
    SHELLFISH = "SHELLFISH"
    EGG = "EGG"
    DAIRY = "DAIRY"


class FoodFocus(StrEnum):
    PROTEIN = "PROTEIN"
    CARBOHYDRATE = "CARBOHYDRATE"


MEAT = AnimalSource.MEAT
POULTRY = AnimalSource.POULTRY
FISH = AnimalSource.FISH
SHELLFISH = AnimalSource.SHELLFISH
EGG = AnimalSource.EGG
DAIRY = AnimalSource.DAIRY

# The animal products each pattern allows.
ALLOWED_SOURCES: dict[DietPattern, frozenset[AnimalSource]] = {
    DietPattern.VEGAN: frozenset(),
    DietPattern.VEGETARIAN: frozenset({DAIRY}),
    DietPattern.EGGETARIAN: frozenset({DAIRY, EGG}),
    DietPattern.PESCATARIAN: frozenset({DAIRY, EGG, FISH, SHELLFISH}),
    DietPattern.NO_RESTRICTION: frozenset(AnimalSource),
}

# The dietary preferences of a profile (free text), in the form normalise_diet reduces
# one to: lower case, with spaces and hyphens as underscores.
DIET_ALIASES: dict[str, DietPattern] = {
    "vegan": DietPattern.VEGAN,
    "vegetarian": DietPattern.VEGETARIAN,
    "lacto_vegetarian": DietPattern.VEGETARIAN,
    "eggetarian": DietPattern.EGGETARIAN,
    "lacto_ovo_vegetarian": DietPattern.EGGETARIAN,
    "pescatarian": DietPattern.PESCATARIAN,
    "pescetarian": DietPattern.PESCATARIAN,
    "non_vegetarian": DietPattern.NO_RESTRICTION,
    "omnivore": DietPattern.NO_RESTRICTION,
    "none": DietPattern.NO_RESTRICTION,
    "no_restriction": DietPattern.NO_RESTRICTION,
    "anything": DietPattern.NO_RESTRICTION,
}

# What eating a food means for the allergens: a food with one of these animal products
# must declare the allergen.
IMPLIED_ALLERGENS: dict[AnimalSource, Allergen] = {
    DAIRY: Allergen.MILK,
    EGG: Allergen.EGG,
    FISH: Allergen.FISH,
    SHELLFISH: Allergen.CRUSTACEAN_SHELLFISH,
}


@dataclass(frozen=True)
class Food:
    """One catalog food. fdc_id names its USDA FoodData Central record; the per-100 g
    values are that record's protein and carbohydrate (by difference)."""

    name: str
    serving: str
    serving_g: Decimal
    protein_per_100g: Decimal
    carbohydrate_per_100g: Decimal
    focus: FoodFocus
    contains: frozenset[AnimalSource]
    allergens: frozenset[Allergen]
    fdc_id: int
    source_id: SourceId = SourceId.USDA_FDC

    @property
    def protein_g(self) -> float:
        return _amount(self.protein_per_100g, self.serving_g)

    @property
    def carbohydrate_g(self) -> float:
        return _amount(self.carbohydrate_per_100g, self.serving_g)


def _amount(per_100g: Decimal, grams: Decimal) -> float:
    """Grams of a nutrient in a serving, to one decimal, .05 rounded up."""
    return float((per_100g * grams / 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _food(
    name: str,
    serving: str,
    serving_g: str,
    protein: str,
    carbohydrate: str,
    focus: FoodFocus,
    fdc_id: int,
    contains: Iterable[AnimalSource] = (),
    allergens: Iterable[Allergen] = (),
) -> Food:
    return Food(
        name,
        serving,
        Decimal(serving_g),
        Decimal(protein),
        Decimal(carbohydrate),
        focus,
        frozenset(contains),
        frozenset(allergens),
        fdc_id,
    )


P = FoodFocus.PROTEIN
C = FoodFocus.CARBOHYDRATE

# Every food was checked against USDA FoodData Central (SR Legacy): the fdc_id, the
# protein and carbohydrate per 100 g, and the serving's gram weight (an FDC portion;
# "100 g" where FDC lists none). A food is listed by what it is, cooked where it is
# eaten cooked. The order is the order of selection, set so that each pattern's first
# examples differ: a protein food comes before another of its kind.
# fmt: off
FOODS: tuple[Food, ...] = (
    # protein-forward
    _food("Chicken breast, roasted", "half a breast, skin and bone removed (86 g)",
          "86", "31.02", "0", P, 171477, [POULTRY]),
    _food("Salmon, farmed Atlantic, cooked", "3 oz (85 g)",
          "85", "22.1", "0", P, 175168, [FISH], [Allergen.FISH]),
    _food("Eggs, hard-boiled", "2 large (100 g)",
          "100", "12.58", "1.12", P, 173424, [EGG], [Allergen.EGG]),
    _food("Greek yogurt, plain, nonfat", "1 container (170 g)",
          "170", "10.19", "3.6", P, 170894, [DAIRY], [Allergen.MILK]),
    _food("Tofu, firm", "1/2 cup (126 g)",
          "126", "9.04", "2.85", P, 172448, [], [Allergen.SOY]),
    _food("Lentils, boiled", "1 cup (198 g)",
          "198", "9.02", "20.13", P, 172421),
    _food("Chickpeas, boiled", "1 cup (164 g)",
          "164", "8.86", "27.42", P, 173757),
    _food("Black beans, boiled", "1 cup (172 g)",
          "172", "8.86", "23.71", P, 173735),
    _food("Tempeh, cooked", "100 g",
          "100", "19.91", "7.62", P, 172467, [], [Allergen.SOY]),
    _food("Edamame, prepared", "1 cup (155 g)",
          "155", "11.91", "8.91", P, 168411, [], [Allergen.SOY]),
    _food("Cottage cheese, 2% milkfat", "1 cup (226 g)",
          "226", "10.45", "4.76", P, 172182, [DAIRY], [Allergen.MILK]),
    _food("Tuna, light, canned in water, drained", "3 oz (85 g)",
          "85", "19.44", "0", P, 173709, [FISH], [Allergen.FISH]),
    _food("Shrimp, cooked", "3 oz (85 g)",
          "85", "22.78", "1.52", P, 171971, [SHELLFISH], [Allergen.CRUSTACEAN_SHELLFISH]),
    _food("Beef, ground, 90% lean, broiled", "3 oz patty (85 g)",
          "85", "26.11", "0", P, 174031, [MEAT]),
    # carbohydrate-forward
    _food("Oatmeal, cooked in water", "1 cup (234 g)",
          "234", "2.54", "12", C, 173905),
    _food("White rice, cooked", "1 cup (158 g)",
          "158", "2.69", "28.17", C, 168878),
    _food("Banana", "1 medium (118 g)",
          "118", "1.09", "22.84", C, 173944),
    _food("Sweet potato, baked", "1 cup, flesh (200 g)",
          "200", "2.01", "20.71", C, 168483),
    _food("Potato, baked, with skin", "1 medium (173 g)",
          "173", "2.5", "21.15", C, 170093),
    _food("Whole-wheat bread", "2 slices (64 g)",
          "64", "12.45", "42.71", C, 172688, [], [Allergen.WHEAT]),
    _food("Quinoa, cooked", "1 cup (185 g)",
          "185", "4.4", "21.3", C, 168917),
    _food("Brown rice, cooked", "1 cup (202 g)",
          "202", "2.74", "25.58", C, 169704),
    _food("Pasta, cooked", "1 cup of spaghetti (124 g)",
          "124", "5.8", "30.86", C, 169737, [], [Allergen.WHEAT]),
    _food("Apple, with skin", "1 medium (182 g)",
          "182", "0.26", "13.81", C, 171688),
)
# fmt: on


@dataclass(frozen=True)
class Diet:
    """A dietary preference as Formiq reads it: pattern is set only when APPLIED."""

    status: PreferenceStatus
    pattern: DietPattern | None


def normalise_diet(preference: str | None) -> Diet:
    """Read a profile's free-text dietary preference. None or blank is NOT_SET; a known
    value (ignoring case, spaces and hyphens) is APPLIED; anything else NOT_RECOGNISED."""
    if preference is None or not preference.strip():
        return Diet(PreferenceStatus.NOT_SET, None)
    pattern = DIET_ALIASES.get(re.sub(r"[\s_-]+", "_", preference.strip().casefold()))
    if pattern is None:
        return Diet(PreferenceStatus.NOT_RECOGNISED, None)
    return Diet(PreferenceStatus.APPLIED, pattern)


def suits(food: Food) -> tuple[DietPattern, ...]:
    """The diet patterns a food fits, in the order of DietPattern."""
    return tuple(
        pattern for pattern in DietPattern if food.contains <= ALLOWED_SOURCES[pattern]
    )


@dataclass(frozen=True)
class FoodSuggestions:
    preference_status: PreferenceStatus
    dietary_pattern: DietPattern | None
    allergens_excluded: tuple[Allergen, ...]
    items: tuple[Food, ...]
    caveats: tuple[str, ...]
    source_ids: tuple[SourceId, ...]


def suggest_foods(
    dietary_preference: str | None, avoid_allergens: Iterable[Allergen] = ()
) -> FoodSuggestions:
    """Up to 4 protein-forward and 3 carbohydrate-forward foods, in catalog order, that fit
    the diet and avoid the allergens. An unset preference filters nothing (and says so); an
    unrecognised one gives no foods. Allergies are never assumed: with none given, the
    caveat says they are not recorded."""
    diet = normalise_diet(dietary_preference)
    avoided = set(avoid_allergens)
    excluded = tuple(allergen for allergen in Allergen if allergen in avoided)

    items: tuple[Food, ...] = ()
    if diet.status is not PreferenceStatus.NOT_RECOGNISED:
        candidates = [
            food
            for food in FOODS
            if not food.allergens & avoided
            and (diet.pattern is None or food.contains <= ALLOWED_SOURCES[diet.pattern])
        ]
        items = (
            *_first(candidates, FoodFocus.PROTEIN, MAX_PROTEIN_ITEMS),
            *_first(candidates, FoodFocus.CARBOHYDRATE, MAX_CARBOHYDRATE_ITEMS),
        )

    caveats = []
    if diet.status is PreferenceStatus.NOT_SET:
        caveats.append(
            "Your dietary preference is not set, so these examples are not filtered by "
            "diet: check what each one contains."
        )
    elif diet.status is PreferenceStatus.NOT_RECOGNISED:
        caveats.append(
            "Your dietary preference is not one Formiq recognises, so no foods are "
            f"suggested. Accepted values: {', '.join(DIET_ALIASES)}."
        )
    if excluded:
        caveats.append(
            "Foods that contain the allergens you listed were left out. Other allergens are "
            "not checked: check labels."
        )
    else:
        caveats.append("Allergies are not recorded: check labels.")
    if not items and diet.status is not PreferenceStatus.NOT_RECOGNISED:
        caveats.append(
            "No example in Formiq's small food list fits your diet and the allergens you "
            "listed."
        )

    source_ids = ((SourceId.USDA_FDC,) if items else ()) + (
        (SourceId.FDA_ALLERGENS,) if excluded else ()
    )
    return FoodSuggestions(
        diet.status, diet.pattern, excluded, items, tuple(caveats), source_ids
    )


def _first(foods: list[Food], focus: FoodFocus, count: int) -> list[Food]:
    return [food for food in foods if food.focus is focus][:count]
