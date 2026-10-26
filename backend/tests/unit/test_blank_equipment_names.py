"""A model that means "no equipment" sometimes sends [""]: it reads as [] (live QA of
2026-10-19: 6 refused searches in 3 turns). A name that is not blank is read as before."""

import pytest
from pydantic import ValidationError

from app.tools.schemas import ProposeWorkoutPlanInput, SearchExercisesInput, without_blank_names


def test_blank_names_are_dropped_from_a_list():
    assert without_blank_names([""]) == []
    assert without_blank_names(["", "  ", "Dumbbell", "\t"]) == ["Dumbbell"]
    assert without_blank_names(["Dumbbell", "Bench"]) == ["Dumbbell", "Bench"]


def test_anything_that_is_not_a_list_is_left_to_validation():
    assert without_blank_names(None) is None
    assert without_blank_names("") == ""
    assert without_blank_names([3]) == [3]


def test_a_search_with_a_blank_name_asks_for_no_equipment():
    request = SearchExercisesInput(use="WARM_UP", available_equipment=[""])

    assert request.available_equipment == []
    mixed = SearchExercisesInput(use="WARM_UP", available_equipment=["", "Bench"])
    assert mixed.available_equipment == ["Bench"]
    # not saying anything is still not saying anything
    assert SearchExercisesInput(use="WARM_UP").available_equipment is None


def test_a_search_still_refuses_what_is_not_a_list_of_names():
    for bad in ("Dumbbell", [3], [["Dumbbell"]], {"name": "Dumbbell"}):
        with pytest.raises(ValidationError):
            SearchExercisesInput(use="WARM_UP", available_equipment=bad)


def test_a_search_for_one_piece_still_needs_a_name():
    with pytest.raises(ValidationError):
        SearchExercisesInput(use="WARM_UP", equipment="")


ACTIVITY = {"exercise_id": 1, "sets": 1, "duration_seconds": 60}


def proposal(**fields):
    return ProposeWorkoutPlanInput(
        user_id=1,
        name="Plan",
        warm_up=[ACTIVITY],
        exercises=[{"exercise_id": 2, "sets": 3, "reps": 10}],
        cool_down=[ACTIVITY],
        **fields,
    )


def test_a_proposal_with_blank_names_says_no_equipment_and_none_unavailable():
    request = proposal(available_equipment=[""], unavailable_equipment=["", " "])

    assert request.available_equipment == []
    assert request.unavailable_equipment == []
    assert proposal(unavailable_equipment=["", "Barbell"]).unavailable_equipment == ["Barbell"]
