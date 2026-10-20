"""What the coach is told about a search that finds nothing (live Gemini pass of
2026-10-16, B5): in its instructions, in the tool's description, and in the
shape of the result. The tool's behaviour on the catalog is in
tests/integration/test_search_other_uses.py; the model is not involved here.
"""

from app.agent import COACH_INSTRUCTIONS
from app.tools import TOOL_DECLARATIONS
from app.tools.schemas import (
    OtherUseExerciseOutput,
    OtherUseMatchesOutput,
    SearchExercisesOutput,
)


def test_the_coach_is_told_to_scope_a_negative_catalog_claim_to_the_search():
    text = " ".join(COACH_INSTRUCTIONS.split())

    assert "A search that finds nothing says only that nothing matched that search" in text
    assert "Never tell the user the catalog has no such exercise at all" in text
    assert "matches_for_other_uses" in text


def test_the_tool_says_what_matches_for_other_uses_is_and_is_not():
    (search,) = [tool for tool in TOOL_DECLARATIONS if tool.name == "search_exercises"]

    assert "matches_for_other_uses" in search.description
    assert "not results for that use" in search.description


def test_an_exercise_named_for_another_use_has_no_id_to_propose_it_by():
    assert set(OtherUseExerciseOutput.model_fields) == {"name", "uses", "equipment"}
    assert set(OtherUseMatchesOutput.model_fields) == {"total", "exercises"}


def test_a_search_result_without_the_disclosure_is_what_it_always_was():
    output = SearchExercisesOutput(exercises=[], count=0, total_matches=0)

    assert output.model_dump(mode="json") == {"exercises": [], "count": 0, "total_matches": 0}


def test_the_note_of_a_cut_search_says_how_many_more_there_are():
    from app.tools.formiq_tools import cut_note

    assert cut_note(10, 10) is None and cut_note(3, 3) is None and cut_note(0, 0) is None
    assert cut_note(10, 11) == (
        "Showing 10 of 11 matches, the most relevant first: this is not all of them. "
        "Say that 1 more exists, or narrow the search (muscle, equipment, movement_pattern, "
        "difficulty) to see others."
    )
    assert "Say that 16 more exist," in cut_note(10, 26)


def test_the_search_note_is_there_only_when_a_search_is_cut():
    """A note says only some of the matches were returned (live QA, 2026-10-19: ten of
    eleven stretches were listed as all of them)."""
    cut = SearchExercisesOutput(exercises=[], count=0, total_matches=3, note="Showing 0 of 3.")

    assert cut.model_dump(mode="json")["note"] == "Showing 0 of 3."


def test_the_coach_is_told_not_to_present_some_matches_as_all_of_them():
    from app.agent.graph import COACH_INSTRUCTIONS

    assert "never present them as all of the matches" in COACH_INSTRUCTIONS
    assert "Say plainly when you could not do something the user asked for" in COACH_INSTRUCTIONS
    assert "Never say a workout includes something that is not in it" in COACH_INSTRUCTIONS


def test_the_coach_is_told_to_look_an_exercise_up_by_name_before_saying_it_is_missing():
    """Live QA, 2026-10-19: "Standing hip circles are not in the Formiq catalog", of an
    exercise the catalog keeps as "Hip Circles"."""
    text = " ".join(COACH_INSTRUCTIONS.split())

    assert "look for it by name (search_exercises with name" in text
    assert "and no use, so it is found whichever section it is for" in text
    assert "before telling them the catalog does not have it" in text
    assert "keeps that exercise under another name, say so and use that one" in text
    assert "such as the exercise the catalog keeps in place of a duplicate" in text


def test_the_search_tool_declares_a_name_and_says_when_to_use_it():
    (search,) = [tool for tool in TOOL_DECLARATIONS if tool.name == "search_exercises"]

    name = search.parameters["properties"]["name"]
    assert name["type"] == "string"
    assert "Never an id" in name["description"]
    assert "a duplicate" in name["description"]
    assert "look for it by name" in search.description
    assert "without use" in name["description"]


def test_the_coach_is_told_never_to_give_a_number_of_calories_burned():
    """Live QA, 2026-10-19: "25 to 45 calories" from the model's own knowledge. Calories
    burned are Formiq's only as a sourced range (docs/nutrition-recovery.md)."""
    text = " ".join(COACH_INSTRUCTIONS.split())

    assert "Never give a number of calories burned by a workout, an exercise or a warm-up" in text
    assert "Formiq has no sourced figure for it" in text


def test_a_search_by_name_says_what_a_cut_or_a_kept_name_or_a_miss_means():
    from types import SimpleNamespace

    from app.tools.formiq_tools import search_note

    shown = [SimpleNamespace(name="Hip Circles")]

    # only some of the matches are shown, and the name one went by is kept as another
    assert search_note(None, shown, 1, {}) is None
    assert search_note("hip circle", shown, 1, {"Standing Hip Circles": "Hip Circles"}) == (
        "The catalog keeps 'Standing Hip Circles' as 'Hip Circles'."
    )
    # a kept exercise that is not among the results is not named: it was not found
    assert search_note("hip circle", shown, 1, {"Cat Stretch": "Cat-Cow"}) is None
    cut = search_note("hip", shown * 15, 20, {})
    assert cut.startswith("Showing 15 of 20 matches") and "Say that 5 more exist" in cut
    # nothing matches: that is not the catalog lacking the exercise
    missing = search_note("zzz", [], 0, {})
    assert "No exercise matches every word of 'zzz'" in missing
    assert "not the catalog having no such exercise" in missing
    # unless the exercise exists for another section: and then a name kept as another is said
    assert search_note("zzz", [], 0, {}, elsewhere=["Cat-Cow"]) is None
    assert search_note("cat stretch", [], 0, {"Cat Stretch": "Cat-Cow"}, elsewhere=["Cat-Cow"]) == (
        "The catalog keeps 'Cat Stretch' as 'Cat-Cow'."
    )
    # no name searched, nothing found: as it always was
    assert search_note(None, [], 0, {}) is None
