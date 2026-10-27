"""What the coach's tools do with exercises that have no level (UNRATED, the
exercises-dataset import's), and with ids that belong to one source. The services
are mocks: no database is read.

An UNRATED exercise is never offered to a beginner and never a warm-up or
cool-down activity; and the ids Formiq's classification names (hidden
duplicates) are free-exercise-db's, so another source's id is never read as one.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.ai import ToolCall
from app.approvals import ProposalTerms
from app.schemas.exercise import Difficulty, ExerciseSource, MuscleRole
from app.schemas.workout_plan import PlanSection
from app.services import (
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.tools import TOOL_DECLARATIONS, FormiqTools
from app.tools.errors import ToolError
from app.tools.formiq_tools import NOT_FOR_BEGINNERS, from_free_exercise_db, visible

USER = 7
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
MAIN, WARM_UP, COOL_DOWN = (
    PlanSection.MAIN_WORKOUT,
    PlanSection.WARM_UP,
    PlanSection.COOL_DOWN,
)


def exercise(
    id=1, name="Air Bike", difficulty=Difficulty.UNRATED, uses=("MAIN_WORKOUT",), **fields
):
    values = {
        "id": id,
        "name": name,
        "description": None,
        "difficulty": difficulty,
        "movement_pattern": None,
        "uses": list(uses),
        "is_active": True,
        "equipment": [],
        "muscles": [
            SimpleNamespace(
                role=MuscleRole.PRIMARY, muscle_group=SimpleNamespace(name="Core", id=1)
            )
        ],
        "category": None,
        "source": ExerciseSource.EXERCISES_DATASET,
        "source_id": f"{id:04d}",
    }
    return SimpleNamespace(**{**values, **fields})


def tools_with(exercises):
    catalog = Mock(spec=ExerciseCatalogService)
    catalog.get_exercise_by_id.side_effect = lambda id: next(
        (item for item in exercises if item.id == id), None
    )
    catalog.list_exercises.return_value = list(exercises)
    catalog.list_equipment.return_value = []
    catalog.list_muscle_groups.return_value = []
    tools = FormiqTools(
        users=Mock(spec=UserService),
        profiles=Mock(spec=UserProfileService),
        plans=Mock(spec=WorkoutPlanService),
        sessions=Mock(spec=WorkoutSessionService),
        catalog=catalog,
        end_read=Mock(),
        proposal_terms=ProposalTerms(clock=lambda: NOW, ttl=timedelta(minutes=30)),
        conversation=[("user", "Give me a workout.")],
    )
    return tools, catalog


def propose(tools, item, section, *, beginner):
    return tools._proposed_exercise(
        SimpleNamespace(exercise_id=item.id), section, set(), beginner
    )


# --- the proposal gate ---


def test_an_unrated_main_exercise_is_not_offered_to_a_beginner():
    item = exercise(uses=["MAIN_WORKOUT"])
    tools, _ = tools_with([item])

    with pytest.raises(ToolError) as refused:
        propose(tools, item, MAIN, beginner=True)

    assert "UNRATED" in refused.value.message
    assert "not offered to a beginner" in refused.value.message
    # so the model is told what to choose instead
    assert "BEGINNER or INTERMEDIATE" in refused.value.message
    # and someone who is not a beginner may be offered it, once Formiq uses it for a section
    assert propose(tools, item, MAIN, beginner=False) is item


@pytest.mark.parametrize("section", [WARM_UP, COOL_DOWN])
@pytest.mark.parametrize("beginner", [True, False])
def test_an_unrated_exercise_is_never_a_warm_up_or_cool_down_activity(section, beginner):
    # even when Formiq's uses name the section
    item = exercise(uses=["WARM_UP", "COOL_DOWN", "MAIN_WORKOUT"])
    tools, _ = tools_with([item])

    with pytest.raises(ToolError) as refused:
        propose(tools, item, section, beginner=beginner)

    assert "has no difficulty level (UNRATED)" in refused.value.message
    assert "cannot be a light" in refused.value.message
    assert "choose a BEGINNER one" in refused.value.message


@pytest.mark.parametrize("section", [MAIN, WARM_UP, COOL_DOWN])
def test_an_unrated_exercise_that_no_section_uses_cannot_be_proposed_at_all(section):
    # the state every imported exercise starts in: classified for nothing
    item = exercise(uses=[])
    tools, _ = tools_with([item])

    with pytest.raises(ToolError) as refused:
        propose(tools, item, section, beginner=False)

    assert "its uses: none" in refused.value.message


def test_rated_exercises_are_judged_as_before():
    beginner_ok = exercise(1, "Goblet Squat", Difficulty.BEGINNER, source=ExerciseSource.FORMIQ)
    middling = exercise(2, "Lunge", Difficulty.INTERMEDIATE, source=ExerciseSource.FORMIQ)
    hard = exercise(3, "Muscle-Up", Difficulty.ADVANCED, source=ExerciseSource.FORMIQ)
    light = exercise(
        4, "Easy Walk", Difficulty.BEGINNER, uses=["WARM_UP"], source=ExerciseSource.FORMIQ
    )
    heavy_warm_up = exercise(
        5, "Fast Run", Difficulty.INTERMEDIATE, uses=["WARM_UP"], source=ExerciseSource.FORMIQ
    )
    tools, _ = tools_with([beginner_ok, middling, hard, light, heavy_warm_up])

    assert propose(tools, beginner_ok, MAIN, beginner=True) is beginner_ok
    assert propose(tools, middling, MAIN, beginner=True) is middling
    assert propose(tools, light, WARM_UP, beginner=True) is light
    with pytest.raises(ToolError, match="ADVANCED, too hard for a beginner"):
        propose(tools, hard, MAIN, beginner=True)
    assert propose(tools, hard, MAIN, beginner=False) is hard
    with pytest.raises(ToolError, match="is not a light warm-up activity"):
        propose(tools, heavy_warm_up, WARM_UP, beginner=False)


# --- the pool a beginner's workout is suggested from ---


def test_a_beginners_main_pool_leaves_out_unrated_and_advanced_exercises():
    pool = [
        exercise(1, "Goblet Squat", Difficulty.BEGINNER),
        exercise(2, "Lunge", Difficulty.INTERMEDIATE),
        exercise(3, "Muscle-Up", Difficulty.ADVANCED),
        exercise(4, "Air Bike", Difficulty.UNRATED),
    ]
    tools, _ = tools_with(pool)

    assert [item.id for item in tools._main_pool(set(), beginner=True)] == [1, 2]
    assert [item.id for item in tools._main_pool(set(), beginner=False)] == [1, 2, 3, 4]
    assert NOT_FOR_BEGINNERS == {Difficulty.ADVANCED, Difficulty.UNRATED}


# --- what the model is shown ---


def test_a_search_shows_an_exercise_without_a_level_as_unrated():
    item = exercise(1, "Air Bike", uses=[])
    tools, _ = tools_with([item])

    (result,) = tools.run(
        [ToolCall(name="search_exercises", arguments={"name": "air bike"})], user_id=USER
    )

    (found,) = result["output"]["exercises"]
    assert (found["name"], found["difficulty"], found["uses"]) == ("Air Bike", "UNRATED", [])
    assert found["muscles"] == ["Core"]
    assert found["equipment"] == []


def test_the_difficulty_filter_the_model_is_given_has_only_levels():
    (declaration,) = [d for d in TOOL_DECLARATIONS if d.name == "search_exercises"]

    levels = declaration.parameters["properties"]["difficulty"]["enum"]

    assert levels == ["BEGINNER", "INTERMEDIATE", "ADVANCED"]
    assert "UNRATED" in declaration.parameters["properties"]["difficulty"]["description"]


# --- ids belong to a source ---

HIDDEN_ID = "Standing_Hip_Circles"  # free-exercise-db's record, kept by Formiq as "Hip Circles"


def test_only_free_exercise_dbs_ids_are_read_as_hidden_duplicates():
    hidden = exercise(
        1, "Standing Hip Circles", source=ExerciseSource.FREE_EXERCISE_DB, source_id=HIDDEN_ID
    )
    same_id_elsewhere = exercise(2, "Standing Hip Circles Seated", source_id=HIDDEN_ID)
    formiqs = exercise(3, "Hip Circles", source=ExerciseSource.FORMIQ, source_id=None)

    assert from_free_exercise_db(hidden)
    assert not from_free_exercise_db(same_id_elsewhere)
    assert not from_free_exercise_db(formiqs)
    assert visible([hidden, same_id_elsewhere, formiqs]) == [same_id_elsewhere, formiqs]


def test_a_search_by_name_redirects_only_free_exercise_dbs_hidden_duplicates():
    hidden = exercise(
        1, "Standing Hip Circles", Difficulty.BEGINNER, ("WARM_UP",),
        source=ExerciseSource.FREE_EXERCISE_DB, source_id=HIDDEN_ID,
    )  # fmt: skip
    kept = exercise(
        2, "Hip Circles", Difficulty.BEGINNER, ("WARM_UP",),
        source=ExerciseSource.FORMIQ, source_id=None,
    )  # fmt: skip
    # another source's record that happens to have the hidden record's id
    other = exercise(3, "Standing Hip Circles Seated", source_id=HIDDEN_ID)
    tools, _ = tools_with([hidden, kept, other])

    ids, asked_for, kept_as = tools._named("standing hip circles")

    # the hidden record is answered by the exercise kept in its place; the other source's
    # exercise is itself, found by its own name, never redirected to it
    assert kept_as == {"Standing Hip Circles": "Hip Circles"}
    assert asked_for == {2}
    assert ids == {2, 3}


def test_the_hidden_duplicates_are_still_hidden_from_a_search():
    hidden = exercise(
        1, "Standing Hip Circles", Difficulty.BEGINNER, [],
        source=ExerciseSource.FREE_EXERCISE_DB, source_id=HIDDEN_ID,
    )  # fmt: skip
    shown = exercise(2, "Air Bike", uses=[], source_id=HIDDEN_ID)
    tools, _ = tools_with([hidden, shown])

    (result,) = tools.run(
        [ToolCall(name="search_exercises", arguments={"movement_pattern": "STRETCH"})],
        user_id=USER,
    )

    assert [found["name"] for found in result["output"]["exercises"]] == ["Air Bike"]
