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
