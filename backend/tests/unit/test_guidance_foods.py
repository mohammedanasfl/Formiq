"""Tests for the food examples (app.guidance.foods): the catalog's integrity, diet
patterns, allergens and the deterministic selection. Pure functions: no database."""

import pytest

from app.guidance import foods
from app.guidance.foods import (
    ALLOWED_SOURCES,
    DIET_ALIASES,
    FOODS,
    IMPLIED_ALLERGENS,
    MAX_CARBOHYDRATE_ITEMS,
    MAX_PROTEIN_ITEMS,
    AnimalSource,
    DietPattern,
    FoodFocus,
    PreferenceStatus,
    normalise_diet,
    suggest_foods,
    suits,
)
from app.guidance.sources import SOURCES, SourceId, cited_sources
from app.schemas.recovery_summary import Allergen

ANIMAL = {
    AnimalSource.MEAT,
    AnimalSource.POULTRY,
    AnimalSource.FISH,
    AnimalSource.SHELLFISH,
    AnimalSource.EGG,
}

# What USDA FoodData Central (SR Legacy) says for each fdc_id, as checked on 2026-10-17:
# protein and carbohydrate per 100 g, and the serving's gram weight. The catalog repeats
# them, so a typo in either place fails here.
FDC_RECORDS = {
    171477: ("31.02", "0", "86"),  # Chicken, broilers or fryers, breast, meat only, roasted
    175168: ("22.1", "0", "85"),  # Fish, salmon, Atlantic, farmed, cooked, dry heat
    173424: ("12.58", "1.12", "100"),  # Egg, whole, cooked, hard-boiled (2 x 50 g)
    170894: ("10.19", "3.6", "170"),  # Yogurt, Greek, plain, nonfat
    172448: ("9.04", "2.85", "126"),  # Tofu, firm, prepared with calcium sulfate and nigari
    172421: ("9.02", "20.13", "198"),  # Lentils, mature seeds, cooked, boiled, without salt
    173757: ("8.86", "27.42", "164"),  # Chickpeas, mature seeds, cooked, boiled, without salt
    173735: ("8.86", "23.71", "172"),  # Beans, black, mature seeds, cooked, boiled
    172467: ("19.91", "7.62", "100"),  # Tempeh, cooked (no FDC portion: 100 g)
    168411: ("11.91", "8.91", "155"),  # Edamame, frozen, prepared
    172182: ("10.45", "4.76", "226"),  # Cheese, cottage, lowfat, 2% milkfat
    173709: ("19.44", "0", "85"),  # Fish, tuna, light, canned in water, drained solids
    171971: ("22.78", "1.52", "85"),  # Crustaceans, shrimp, cooked, moist heat
    174031: ("26.11", "0", "85"),  # Beef, ground, 90% lean, patty, cooked, broiled
    173905: ("2.54", "12", "234"),  # Cereals, oats, regular and quick, cooked with water
    168878: ("2.69", "28.17", "158"),  # Rice, white, long-grain, regular, enriched, cooked
    173944: ("1.09", "22.84", "118"),  # Bananas, raw (medium)
    168483: ("2.01", "20.71", "200"),  # Sweet potato, cooked, baked in skin, flesh
    170093: ("2.5", "21.15", "173"),  # Potatoes, baked, flesh and skin (medium)
    172688: ("12.45", "42.71", "64"),  # Bread, whole-wheat, commercially prepared (2 x 32 g)
    168917: ("4.4", "21.3", "185"),  # Quinoa, cooked
    169704: ("2.74", "25.58", "202"),  # Rice, brown, long-grain, cooked
    169737: ("5.8", "30.86", "124"),  # Pasta, cooked, enriched, without added salt
    171688: ("0.26", "13.81", "182"),  # Apples, raw, with skin (medium)
}
# protein and carbohydrate in the serving, to one decimal
EXPECTED_AMOUNTS = {
    171477: (26.7, 0.0),
    175168: (18.8, 0.0),
    173424: (12.6, 1.1),
    170894: (17.3, 6.1),
    172448: (11.4, 3.6),
    172421: (17.9, 39.9),
    173757: (14.5, 45.0),
    173735: (15.2, 40.8),
    172467: (19.9, 7.6),
    168411: (18.5, 13.8),
    172182: (23.6, 10.8),
    173709: (16.5, 0.0),
    171971: (19.4, 1.3),
    174031: (22.2, 0.0),
    173905: (5.9, 28.1),
    168878: (4.3, 44.5),
    173944: (1.3, 27.0),
    168483: (4.0, 41.4),
    170093: (4.3, 36.6),
    172688: (8.0, 27.3),
    168917: (8.1, 39.4),
    169704: (5.5, 51.7),
    169737: (7.2, 38.3),
    171688: (0.5, 25.1),
}


def names(suggestions):
    return [food.name for food in suggestions.items]


def count(suggestions, focus):
    return sum(food.focus is focus for food in suggestions.items)


# catalog integrity


def test_the_catalog_has_the_24_checked_foods():
    assert len(FOODS) == 24
    assert {food.fdc_id for food in FOODS} == set(FDC_RECORDS) == set(EXPECTED_AMOUNTS)


def test_every_food_has_an_fdc_source_and_a_unique_record():
    assert len({food.fdc_id for food in FOODS}) == len(FOODS)
    assert len({food.name for food in FOODS}) == len(FOODS)
    registered = {source.id for source in SOURCES}
    for food in FOODS:
        assert food.fdc_id > 0, food.name
        assert food.source_id is SourceId.USDA_FDC, food.name
        assert food.source_id in registered


def test_each_food_repeats_what_fdc_states():
    for food in FOODS:
        protein, carbohydrate, grams = FDC_RECORDS[food.fdc_id]
        assert str(food.protein_per_100g) == protein, food.name
        assert str(food.carbohydrate_per_100g) == carbohydrate, food.name
        assert str(food.serving_g) == grams, food.name
        assert f"({grams} g)" in food.serving or food.serving == f"{grams} g", food.name


def test_each_servings_amounts_are_exact_arithmetic_on_the_fdc_values():
    for food in FOODS:
        assert (food.protein_g, food.carbohydrate_g) == EXPECTED_AMOUNTS[food.fdc_id], food.name
        # a serving cannot hold more nutrient than it weighs
        assert food.protein_g + food.carbohydrate_g <= float(food.serving_g), food.name


def test_a_protein_food_is_protein_forward_and_a_carbohydrate_food_carbohydrate_forward():
    for food in FOODS:
        if food.focus is FoodFocus.PROTEIN:
            assert food.protein_g >= 10, food.name
        else:
            assert food.carbohydrate_g >= 20, food.name
    assert {food.focus for food in FOODS} == set(FoodFocus)
    assert sum(food.focus is FoodFocus.PROTEIN for food in FOODS) == 14
    assert sum(food.focus is FoodFocus.CARBOHYDRATE for food in FOODS) == 10


def test_foods_use_only_the_known_animal_sources_and_allergens():
    for food in FOODS:
        assert all(isinstance(item, AnimalSource) for item in food.contains), food.name
        assert all(isinstance(item, Allergen) for item in food.allergens), food.name


def test_no_meat_poultry_fish_shellfish_or_egg_food_suits_vegetarian_or_vegan():
    animal_foods = [food for food in FOODS if food.contains & ANIMAL]
    assert len(animal_foods) == 6
    for food in animal_foods:
        assert DietPattern.VEGETARIAN not in suits(food), food.name
        assert DietPattern.VEGAN not in suits(food), food.name
    for food in FOODS:
        if AnimalSource.DAIRY in food.contains:
            assert DietPattern.VEGETARIAN in suits(food) or food.contains & ANIMAL, food.name
            assert DietPattern.VEGAN not in suits(food), food.name


def test_a_food_declares_the_allergens_its_animal_sources_imply():
    for food in FOODS:
        for source, allergen in IMPLIED_ALLERGENS.items():
            if source in food.contains:
                assert allergen in food.allergens, (food.name, allergen)
    milk = [food for food in FOODS if AnimalSource.DAIRY in food.contains]
    assert {food.name for food in milk} == {
        "Greek yogurt, plain, nonfat",
        "Cottage cheese, 2% milkfat",
    }
    assert all(Allergen.MILK in food.allergens for food in milk)


def test_a_food_made_of_soy_or_wheat_declares_it():
    soy = {food.name for food in FOODS if Allergen.SOY in food.allergens}
    assert soy == {"Tofu, firm", "Tempeh, cooked", "Edamame, prepared"}
    wheat = {food.name for food in FOODS if Allergen.WHEAT in food.allergens}
    assert wheat == {"Whole-wheat bread", "Pasta, cooked"}


def test_only_the_fdas_nine_allergens_are_ever_declared():
    assert len(Allergen) == 9
    assert {item for food in FOODS for item in food.allergens} <= set(Allergen)


def test_each_pattern_allows_the_animal_products_it_is_defined_by():
    assert ALLOWED_SOURCES[DietPattern.VEGAN] == frozenset()
    # lacto-vegetarian: dairy, and deliberately no egg
    assert ALLOWED_SOURCES[DietPattern.VEGETARIAN] == {AnimalSource.DAIRY}
    assert ALLOWED_SOURCES[DietPattern.EGGETARIAN] == {AnimalSource.DAIRY, AnimalSource.EGG}
    assert ALLOWED_SOURCES[DietPattern.PESCATARIAN] == {
        AnimalSource.DAIRY,
        AnimalSource.EGG,
        AnimalSource.FISH,
        AnimalSource.SHELLFISH,
    }
    assert ALLOWED_SOURCES[DietPattern.NO_RESTRICTION] == set(AnimalSource)


def test_the_fdc_and_allergen_sources_are_registered_for_the_foods():
    assert [source.id for source in cited_sources([SourceId.USDA_FDC, SourceId.FDA_ALLERGENS])] == [
        SourceId.USDA_FDC,
        SourceId.FDA_ALLERGENS,
    ]


# diet normalisation


@pytest.mark.parametrize(
    "preference, pattern",
    [
        ("vegan", DietPattern.VEGAN),
        ("vegetarian", DietPattern.VEGETARIAN),
        ("Vegetarian", DietPattern.VEGETARIAN),
        ("lacto-vegetarian", DietPattern.VEGETARIAN),
        ("eggetarian", DietPattern.EGGETARIAN),
        ("lacto ovo vegetarian", DietPattern.EGGETARIAN),
        ("pescatarian", DietPattern.PESCATARIAN),
        ("pescetarian", DietPattern.PESCATARIAN),
        ("non_vegetarian", DietPattern.NO_RESTRICTION),
        ("Non-Vegetarian", DietPattern.NO_RESTRICTION),
        ("omnivore", DietPattern.NO_RESTRICTION),
        ("none", DietPattern.NO_RESTRICTION),
        ("no_restriction", DietPattern.NO_RESTRICTION),
        ("anything", DietPattern.NO_RESTRICTION),
        ("  NO  RESTRICTION  ", DietPattern.NO_RESTRICTION),
    ],
)
def test_a_known_preference_is_applied(preference, pattern):
    diet = normalise_diet(preference)
    assert diet.status is PreferenceStatus.APPLIED
    assert diet.pattern is pattern


@pytest.mark.parametrize("preference", [None, "", "   "])
def test_no_preference_is_not_set(preference):
    diet = normalise_diet(preference)
    assert diet.status is PreferenceStatus.NOT_SET
    assert diet.pattern is None


@pytest.mark.parametrize("preference", ["keto", "halal", "vegetarian but eats fish", "x"])
def test_an_unknown_preference_is_not_recognised(preference):
    diet = normalise_diet(preference)
    assert diet.status is PreferenceStatus.NOT_RECOGNISED
    assert diet.pattern is None


# selection


def test_a_vegetarian_gets_no_meat_fish_or_egg_whatever_the_allergens():
    for avoided in ([], [Allergen.MILK], [Allergen.SOY], list(Allergen)):
        result = suggest_foods("vegetarian", avoided)
        assert result.preference_status is PreferenceStatus.APPLIED
        assert result.dietary_pattern is DietPattern.VEGETARIAN
        for food in result.items:
            assert not food.contains & ANIMAL, food.name
            assert AnimalSource.EGG not in food.contains
    assert "Greek yogurt, plain, nonfat" in names(suggest_foods("vegetarian"))
    assert "Eggs, hard-boiled" not in names(suggest_foods("vegetarian"))


def test_an_eggetarian_gets_eggs_but_no_meat_or_fish():
    result = suggest_foods("eggetarian")
    assert names(result)[0] == "Eggs, hard-boiled"
    assert not any(food.contains & (ANIMAL - {AnimalSource.EGG}) for food in result.items)


def test_a_vegan_gets_no_animal_food_at_all():
    for food in suggest_foods("vegan").items:
        assert food.contains == frozenset(), food.name
    assert names(suggest_foods("vegan"))[:4] == [
        "Tofu, firm",
        "Lentils, boiled",
        "Chickpeas, boiled",
        "Black beans, boiled",
    ]


def test_a_pescatarian_gets_fish_but_no_meat_or_poultry():
    result = suggest_foods("pescatarian")
    assert "Salmon, farmed Atlantic, cooked" in names(result)
    for food in result.items:
        assert not food.contains & {AnimalSource.MEAT, AnimalSource.POULTRY}, food.name


def test_an_omnivore_gets_the_first_foods_of_the_catalog():
    result = suggest_foods("non_vegetarian")
    assert names(result)[:2] == ["Chicken breast, roasted", "Salmon, farmed Atlantic, cooked"]


def test_an_unset_preference_filters_nothing_and_says_so():
    result = suggest_foods(None)
    assert result.preference_status is PreferenceStatus.NOT_SET
    assert result.dietary_pattern is None
    assert result.items
    assert any(food.contains & ANIMAL for food in result.items)
    assert any("not filtered by diet" in caveat for caveat in result.caveats)
    # each example still shows what it fits and contains
    assert all(suits(food) for food in result.items)


def test_an_unrecognised_preference_gives_no_foods_and_lists_the_accepted_values():
    result = suggest_foods("keto")
    assert result.preference_status is PreferenceStatus.NOT_RECOGNISED
    assert result.dietary_pattern is None
    assert result.items == ()
    caveat = next(item for item in result.caveats if "not one Formiq recognises" in item)
    for accepted in DIET_ALIASES:
        assert accepted in caveat
    assert result.source_ids == ()


def test_the_selection_has_at_most_4_protein_and_3_carbohydrate_foods_in_catalog_order():
    for preference in (None, "vegan", "vegetarian", "eggetarian", "pescatarian", "omnivore"):
        result = suggest_foods(preference)
        assert count(result, FoodFocus.PROTEIN) == MAX_PROTEIN_ITEMS == 4
        assert count(result, FoodFocus.CARBOHYDRATE) == MAX_CARBOHYDRATE_ITEMS == 3
        positions = [FOODS.index(food) for food in result.items]
        protein_positions = positions[:4]
        carbohydrate_positions = positions[4:]
        assert protein_positions == sorted(protein_positions)
        assert carbohydrate_positions == sorted(carbohydrate_positions)
        assert all(food.focus is FoodFocus.PROTEIN for food in result.items[:4])


def test_the_selection_is_deterministic():
    for preference in (None, "vegan", "vegetarian", "keto"):
        for avoided in ([], [Allergen.SOY], [Allergen.MILK, Allergen.PEANUTS]):
            assert suggest_foods(preference, avoided) == suggest_foods(preference, avoided)


# allergens


@pytest.mark.parametrize("allergen", list(Allergen))
def test_a_food_with_an_avoided_allergen_is_never_suggested(allergen):
    for preference in (None, "vegan", "vegetarian", "eggetarian", "pescatarian", "omnivore"):
        result = suggest_foods(preference, [allergen])
        assert result.allergens_excluded == (allergen,)
        assert all(allergen not in food.allergens for food in result.items)


def test_soy_is_left_out_when_avoided():
    assert not {"Tofu, firm", "Tempeh, cooked", "Edamame, prepared"} & set(
        names(suggest_foods("vegan", [Allergen.SOY]))
    )
    assert "Tofu, firm" in names(suggest_foods("vegan"))


def test_the_excluded_allergens_are_listed_once_in_a_fixed_order():
    result = suggest_foods("vegan", [Allergen.SOY, Allergen.MILK, Allergen.SOY, Allergen.EGG])
    assert result.allergens_excluded == (Allergen.MILK, Allergen.EGG, Allergen.SOY)
    assert suggest_foods("vegan").allergens_excluded == ()


def test_allergies_are_never_assumed_and_the_caveat_says_to_check_labels():
    assert "Allergies are not recorded: check labels." in suggest_foods("vegan").caveats
    assert "Allergies are not recorded: check labels." in suggest_foods("keto").caveats
    given = suggest_foods("vegan", [Allergen.SOY])
    assert "Allergies are not recorded: check labels." not in given.caveats
    assert any("check labels" in caveat for caveat in given.caveats)
    assert any("Other allergens are not checked" in caveat for caveat in given.caveats)


def test_the_sources_cited_are_the_ones_used():
    assert suggest_foods("vegan").source_ids == (SourceId.USDA_FDC,)
    assert suggest_foods("vegan", [Allergen.SOY]).source_ids == (
        SourceId.USDA_FDC,
        SourceId.FDA_ALLERGENS,
    )


@pytest.mark.parametrize(
    "preference", ["vegan", "vegetarian", "eggetarian", "pescatarian", "omnivore"]
)
@pytest.mark.parametrize("allergen", list(Allergen))
def test_each_pattern_keeps_3_protein_and_2_carbohydrate_foods_after_any_one_allergen(
    preference, allergen
):
    result = suggest_foods(preference, [allergen])
    assert count(result, FoodFocus.PROTEIN) >= 3
    assert count(result, FoodFocus.CARBOHYDRATE) >= 2


def test_every_pattern_keeps_foods_even_if_all_nine_allergens_are_avoided():
    # the beans and lentils, and the plain grains, fruit and potatoes, declare no allergen
    for preference in ("vegan", "vegetarian", "eggetarian", "pescatarian", "omnivore"):
        result = suggest_foods(preference, list(Allergen))
        assert count(result, FoodFocus.PROTEIN) >= 3, preference
        assert count(result, FoodFocus.CARBOHYDRATE) >= 2, preference


def test_an_empty_result_carries_a_caveat(monkeypatch):
    chicken_only = tuple(food for food in FOODS if food.name.startswith("Chicken"))
    monkeypatch.setattr(foods, "FOODS", chicken_only)
    result = suggest_foods("vegan")
    assert result.preference_status is PreferenceStatus.APPLIED
    assert result.items == ()
    assert any("No example in Formiq's small food list fits" in item for item in result.caveats)
    assert result.source_ids == ()
    # a pattern that allows chicken still gets it
    assert suggest_foods("omnivore").items == chicken_only


def test_an_avoided_allergen_can_empty_the_result_and_the_caveat_says_so(monkeypatch):
    salmon_only = tuple(food for food in FOODS if food.name.startswith("Salmon"))
    monkeypatch.setattr(foods, "FOODS", salmon_only)
    result = suggest_foods("pescatarian", [Allergen.FISH])
    assert result.items == ()
    assert any("No example in Formiq's small food list fits" in item for item in result.caveats)
    assert any("check labels" in item for item in result.caveats)
    assert result.source_ids == (SourceId.FDA_ALLERGENS,)
