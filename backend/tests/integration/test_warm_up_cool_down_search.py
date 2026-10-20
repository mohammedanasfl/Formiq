"""What the coach's search finds for the warm-up and the cool-down, on the catalog with the
free-exercise-db dataset imported: the fixes of the live QA of 2026-10-19
(docs/warm-up-cool-down.md).

- the activities that suit the main exercises already found come first, so the few a
  search returns are ones a proposal can use;
- a search cut at its limit says so;
- Formiq's hidden duplicates are not found by a search that gives no section either;
- a treadmill and a recumbent bike are found by their names, and the imported cardio
  records show Formiq's description, never a machine's menu and calorie estimate;
- an exercise is found by the words of its name, a hidden duplicate's name finds the
  exercise the catalog keeps in its place, and a name nothing has does not say the
  catalog lacks the exercise;
- the muscles the user's message names rank the activities, whatever the model searched
  the main workout by (docs/warm-up-cool-down.md, the second fixes of 2026-10-20).
"""

import json
from unittest.mock import Mock

import pytest

from app.ai import ToolCall
from app.catalog.classification import DUPLICATE_OF, HIDDEN_DUPLICATE_IDS
from app.models import Exercise
from app.schemas import ExerciseResponse
from app.services import (
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.tools.formiq_tools import FormiqTools
from app.tools.limits import MAX_SEARCH_RESULTS

GYM = ["Bench", "Dumbbell", "Cable Machine"]


def tools_for(session, message=None):
    """The coach's tools; with message, the one the user wrote (what a search reads the
    muscles they train from)."""
    return FormiqTools(
        users=UserService(session),
        profiles=UserProfileService(session),
        plans=WorkoutPlanService(session),
        sessions=WorkoutSessionService(session),
        catalog=ExerciseCatalogService(session),
        end_read=Mock(),
        conversation=None if message is None else [("user", message)],
    )


@pytest.fixture
def tools(imported_session):
    return tools_for(imported_session)


@pytest.fixture
def saying(imported_session):
    """The tools for a user who wrote this message."""
    return lambda message: tools_for(imported_session, message)


def run(tools, tool, **arguments):
    (result,) = tools.run([ToolCall(name=tool, arguments=arguments, id=f"t-{tool}")], user_id=1)
    return result


def search(tools, **arguments):
    result = run(tools, "search_exercises", **arguments)
    assert "output" in result, result
    return result["output"]


def names(found):
    return [item["name"] for item in found["exercises"]]


def imported(imported_session, source_id):
    return imported_session.query(Exercise).filter_by(source_id=source_id).one()


# --- the activities that suit the main exercises come first ---


def test_a_chest_and_triceps_workout_is_offered_activities_made_for_its_muscles(tools):
    """Live QA: the same ten generic warm-ups came back for every workout, among them
    ankle circles and a back drill that no chest or triceps exercise suits, and none of
    the new chest or triceps drills."""
    for muscle in ("Chest", "Triceps"):
        search(tools, use="MAIN_WORKOUT", muscle=muscle, available_equipment=GYM)

    warm_up = search(tools, use="WARM_UP", available_equipment=GYM)
    cool_down = search(tools, use="COOL_DOWN", available_equipment=GYM)

    for found in (warm_up, cool_down):
        assert found["count"] == MAX_SEARCH_RESULTS
        # no activity that suits no main exercise: a proposal would refuse it
        assert [item["name"] for item in found["exercises"] if item["suits_main"] == []] == []
        assert any(item["suits_main"] == "any" for item in found["exercises"])
    # activities for the chest, the shoulders and the arms are there to choose from, and not
    # the ankle, hip or hamstring ones that filled the list before
    assert {"Dynamic Chest Stretch", "Arm Circles", "Scapular Wall Slide"} <= set(names(warm_up))
    assert {"Doorway Chest Stretch", "Overhead Triceps Stretch"} <= set(names(cool_down))
    assert not set(names(warm_up)) & {"Ankle Circles", "Bodyweight Hip Hinge", "Cat-Cow"}
    assert not set(names(cool_down)) & {"Butterfly Stretch", "90/90 Hamstring"}


def test_without_main_exercises_a_search_is_ranked_as_it_was(tools):
    """The activities carry no suits_main and are not reordered until there is a main
    exercise to suit."""
    warm_up = search(tools, use="WARM_UP", available_equipment=GYM)

    assert all("suits_main" not in item for item in warm_up["exercises"])
    assert names(warm_up)[:4] == ["Brisk Walk", "Marching in Place", "Step Jacks", "Jumping Jacks"]


def test_a_leg_day_is_not_offered_chest_drills(tools):
    for muscle in ("Quadriceps", "Hamstrings", "Glutes"):
        search(tools, use="MAIN_WORKOUT", muscle=muscle, available_equipment=[])

    warm_up = search(tools, use="WARM_UP", available_equipment=[])

    assert "Wall Push-Up" not in names(warm_up)
    assert {"Bodyweight Hip Hinge", "Ankle Circles"} & set(names(warm_up))
    assert [item["name"] for item in warm_up["exercises"] if item["suits_main"] == []] == []


# --- a search cut at its limit says so ---


def test_a_search_cut_at_its_limit_says_how_many_more_match(tools):
    found = search(tools, use="COOL_DOWN", available_equipment=GYM)

    assert found["count"] == MAX_SEARCH_RESULTS
    assert found["total_matches"] > MAX_SEARCH_RESULTS
    more = found["total_matches"] - found["count"]
    assert found["note"].startswith(f"Showing {found['count']} of {found['total_matches']} matches")
    assert f"Say that {more} more exist" in found["note"]


def test_a_search_that_returns_every_match_has_no_note(tools):
    found = search(tools, use="WARM_UP", muscle="Triceps", available_equipment=[])

    assert 0 < found["count"] == found["total_matches"] <= MAX_SEARCH_RESULTS
    assert "note" not in found


def test_every_hamstring_stretch_fits_in_one_search_since_the_limit_is_15(tools):
    """Live QA, with a limit of 10: "the 10 hamstring stretches" when there were 11, and the
    eleventh left out. The longest activity list for one muscle is a little under the limit."""
    found = search(tools, use="COOL_DOWN", muscle="Hamstrings", available_equipment=[])

    assert found["count"] == found["total_matches"] > 10
    assert found["count"] <= MAX_SEARCH_RESULTS
    assert "note" not in found


# --- Formiq's hidden duplicates ---


@pytest.mark.parametrize(
    "filters",
    [
        {"movement_pattern": "CARDIO"},
        {"movement_pattern": "CARDIO", "available_equipment": ["Machine", "Stationary Bike"]},
        {"muscle": "Triceps"},
        {"muscle": "Calves"},
        {"muscle": "Hamstrings", "available_equipment": []},
        {"muscle": "Chest", "available_equipment": []},
    ],
)
def test_a_search_with_no_section_leaves_the_hidden_duplicates_out(
    tools, imported_session, filters
):
    """Live QA: a search by movement pattern returned "Bicycling, Stationary", which sits
    beside Easy Stationary Cycling and which no proposal accepts."""
    hidden = {
        exercise.name
        for exercise in imported_session.query(Exercise).all()
        if exercise.source_id in HIDDEN_DUPLICATE_IDS
    }
    assert len(hidden) == 18

    found = search(tools, **filters)

    assert found["count"] > 0
    assert not set(names(found)) & hidden


def test_the_cardio_pattern_total_is_the_cardio_that_is_not_hidden(tools, imported_session):
    cardio = [e for e in imported_session.query(Exercise).filter_by(movement_pattern="CARDIO")]
    visible = [e for e in cardio if e.source_id not in HIDDEN_DUPLICATE_IDS]

    found = search(tools, movement_pattern="CARDIO")

    assert len(cardio) - len(visible) == 2
    assert found["total_matches"] == len(visible)


def test_a_hidden_duplicate_is_still_read_by_its_id(tools, imported_session):
    for source_id in ("Cat_Stretch", "Walking_Treadmill", "Bicycling_Stationary"):
        hidden = imported(imported_session, source_id)

        read = run(tools, "get_exercise", exercise_id=hidden.id)

        assert read["output"]["name"] == hidden.name
        assert read["output"]["uses"] == []


def test_a_search_for_a_use_that_finds_nothing_does_not_name_a_hidden_duplicate(
    tools, imported_session
):
    """No main exercise is cardio, so a main workout search for cardio matches nothing and
    names what the catalog has for other uses: Easy Walk, not the walk on a treadmill
    that Formiq hides."""
    found = search(tools, use="MAIN_WORKOUT", movement_pattern="CARDIO")

    assert found["count"] == 0
    other = found["matches_for_other_uses"]
    assert {item["name"] for item in other["exercises"]}
    assert not {item["name"] for item in other["exercises"]} & {
        "Walking, Treadmill",
        "Bicycling, Stationary",
    }
    # its total is of the cardio the catalog shows: every cardio record but the hidden two
    cardio = imported_session.query(Exercise).filter_by(movement_pattern="CARDIO").all()
    assert other["total"] == len([e for e in cardio if e.source_id not in HIDDEN_DUPLICATE_IDS])


# --- a treadmill, a recumbent bike, and the cardio records' instructions ---


def test_the_treadmill_and_the_recumbent_bike_are_linked_to_equipment_that_names_them(
    imported_session,
):
    equipment = lambda source_id: [  # noqa: E731
        item.name for item in imported(imported_session, source_id).equipment
    ]

    assert equipment("Jogging_Treadmill") == ["Treadmill"]
    assert equipment("Walking_Treadmill") == ["Treadmill"]
    assert equipment("Recumbent_Bike") == ["Stationary Bike"]
    # the record says "machine" for them, and is kept as it was
    assert imported(imported_session, "Recumbent_Bike").source_record["equipment"] == "machine"
    # other machines are still "Machine"
    assert equipment("Elliptical_Trainer") == ["Machine"]


def test_a_user_with_a_treadmill_is_offered_the_treadmill_warm_up(tools):
    found = search(
        tools,
        use="WARM_UP",
        movement_pattern="CARDIO",
        available_equipment=["Dumbbell", "treadmill"],
    )

    assert "Jogging, Treadmill" in names(found)
    assert "Recumbent Bike" not in names(found)


def test_a_user_with_a_recumbent_bike_is_offered_stationary_cycling_and_the_bike(tools):
    found = search(
        tools, use="COOL_DOWN", movement_pattern="CARDIO", available_equipment=["recumbent bike"]
    )

    assert {"Recumbent Bike", "Easy Stationary Cycling"} <= set(names(found))
    # nothing that needs the strength machines the user did not name
    assert all(item["equipment"] in ([], ["Stationary Bike"]) for item in found["exercises"])


def test_a_blank_name_for_no_equipment_is_the_same_as_none(tools):
    """Live QA: a model sends [""] for none, and was refused: 6 searches in 3 turns."""
    for use in ("WARM_UP", "COOL_DOWN", "MAIN_WORKOUT"):
        assert search(tools, use=use, available_equipment=[""]) == search(
            tools, use=use, available_equipment=[]
        )
    assert search(tools, use="WARM_UP", available_equipment=["", " ", "Dumbbell"]) == search(
        tools, use="WARM_UP", available_equipment=["Dumbbell"]
    )


def test_a_name_for_no_piece_of_equipment_is_still_refused(tools):
    result = run(tools, "search_exercises", use="WARM_UP", available_equipment=["jetpack"])

    assert result["error"]["code"] == "INVALID_INPUT"
    assert "the catalog has no equipment 'jetpack'" in result["error"]["message"]


@pytest.mark.parametrize("source_id", ["Recumbent_Bike", "Jogging_Treadmill", "Bicycling"])
def test_the_cardio_records_show_formiqs_description_and_never_the_machines_menu(
    tools, imported_session, source_id
):
    exercise = imported(imported_session, source_id)

    read = run(tools, "get_exercise", exercise_id=exercise.id)["output"]

    assert "Suggested dose" in read["description"]
    assert read["instructions"] == []
    # nothing a tool gives the coach, or the exercise route gives an app, has the estimate
    served = ExerciseResponse.model_validate(exercise)
    assert served.instructions == []
    for text in (json.dumps(read), served.model_dump_json()):
        assert "calorie" not in text.lower()
        assert "150 lb" not in text
    # the record keeps its own steps, unchanged
    assert exercise.source_record["instructions"]
    assert exercise.category == "cardio"


# --- a search by the words of an exercise's name ---


def test_a_name_finds_the_exercise_the_catalog_keeps_under_another_name(tools):
    """Live QA: "Standing hip circles are not in the Formiq catalog", of an exercise the
    catalog keeps as "Hip Circles" (the imported record is hidden as its duplicate)."""
    found = search(tools, name="standing hip circles")

    assert names(found) == ["Hip Circles"]
    assert found["total_matches"] == 1
    assert found["note"] == "The catalog keeps 'Standing Hip Circles' as 'Hip Circles'."
    assert found["exercises"][0]["uses"] == ["WARM_UP"]


@pytest.mark.parametrize("hidden", sorted(DUPLICATE_OF))
def test_every_hidden_duplicates_name_finds_the_exercise_kept_in_its_place_first(
    tools, imported_session, hidden
):
    record = imported(imported_session, hidden)
    kept = DUPLICATE_OF[hidden]

    found = search(tools, name=record.name)

    # the kept exercise is the first result, and the note says it is kept under that name
    assert names(found)[0] == kept
    assert f"The catalog keeps '{record.name}' as '{kept}'." in found["note"]
    # the hidden one is never a result
    hidden_names = {imported(imported_session, other).name for other in HIDDEN_DUPLICATE_IDS}
    assert not set(names(found)) & hidden_names


def test_the_exercise_kept_in_place_of_a_hidden_duplicate_exists_and_is_visible(imported_session):
    by_name = {e.name: e for e in imported_session.query(Exercise).all()}

    for hidden, kept in DUPLICATE_OF.items():
        assert imported(imported_session, hidden).uses == []
        assert by_name[kept].is_active, kept
        assert by_name[kept].source_id not in HIDDEN_DUPLICATE_IDS, kept
        assert by_name[kept].uses, kept


def test_a_name_with_a_plural_or_no_hyphen_finds_the_exercise(tools):
    assert "Cat-Cow" in names(search(tools, name="cat cow"))
    assert "Cat-Cow" in names(search(tools, name="cat-cows"))
    assert "Push-Up" in names(search(tools, name="push ups", available_equipment=[]))
    assert "Hip Circles" in names(search(tools, name="hip circle"))


def test_a_name_keeps_the_other_filters(tools):
    """The name is one filter among the others: use, equipment, muscle."""
    warm_up = search(tools, name="circle", use="WARM_UP")
    main = search(tools, name="circle", use="MAIN_WORKOUT")
    bodyweight = search(tools, name="push up", available_equipment=[])

    assert "Arm Circles" in names(warm_up)
    assert all("WARM_UP" in item["uses"] for item in warm_up["exercises"])
    assert main["count"] == 0
    assert all(item["equipment"] == [] for item in bodyweight["exercises"])
    curls = search(tools, name="curl", available_equipment=[])
    assert curls["count"] and all(item["equipment"] == [] for item in curls["exercises"])


def test_a_name_nothing_has_says_it_is_not_the_catalog_lacking_the_exercise(tools):
    found = search(tools, name="zzzz nothing")

    assert found["count"] == 0 and found["total_matches"] == 0
    assert "That is not the catalog having no such exercise" in found["note"]
    assert "try fewer or other words" in found["note"]


def test_a_name_that_only_another_section_uses_says_so_and_not_that_nothing_matched(tools):
    """Nothing is used for the main workout with this name, which is no word on the catalog
    having none: Cat-Cow is there, for the warm-up and cool-down."""
    found = search(tools, name="cat cow", use="MAIN_WORKOUT")

    assert found["count"] == 0
    assert [item["name"] for item in found["matches_for_other_uses"]["exercises"]] == ["Cat-Cow"]
    assert "note" not in found


def test_a_hidden_duplicates_name_searched_for_the_wrong_section_still_says_it_is_kept(tools):
    """Live QA, second pass: the model searched "cat stretch" for the main workout, found
    Cat-Cow only as a match for other uses, and told the user Cat Stretch is not in the
    catalog. The note says it is kept as Cat-Cow, and it is the match named first."""
    found = search(tools, name="cat stretch", use="MAIN_WORKOUT")

    assert found["count"] == 0
    assert [item["name"] for item in found["matches_for_other_uses"]["exercises"]] == ["Cat-Cow"]
    assert found["note"] == "The catalog keeps 'Cat Stretch' as 'Cat-Cow'."
    hip = search(tools, name="standing hip circles", use="MAIN_WORKOUT")
    assert hip["note"] == "The catalog keeps 'Standing Hip Circles' as 'Hip Circles'."
    assert hip["matches_for_other_uses"]["exercises"][0]["name"] == "Hip Circles"


def test_a_name_with_a_filler_word_finds_the_exercise(tools):
    found = search(tools, name="walking on a treadmill")

    assert "Brisk Walk" in names(found)
    assert found["note"] == "The catalog keeps 'Walking, Treadmill' as 'Brisk Walk'."


def test_the_name_and_its_note_never_name_a_hidden_duplicate_as_a_result(tools, imported_session):
    hidden = {imported(imported_session, source_id).name for source_id in HIDDEN_DUPLICATE_IDS}

    for query in ("stretch", "walk", "cable", "push", "treadmill", "bicycling", "triceps"):
        found = search(tools, name=query)
        assert not set(names(found)) & hidden, query


# --- the muscles the user says rank the activities ---

BACK_AND_BICEPS = (
    "Back and biceps day today, about 40 minutes. I've got a pull-up bar, dumbbells and "
    "resistance bands."
)
GEAR = ["Pull-up Bar", "Dumbbell", "Resistance Band"]


def test_a_back_and_biceps_message_ranks_its_activities_though_the_main_search_named_no_muscle(
    saying,
):
    """Live QA: the model searched the main workout with no muscle (any ten exercises), so every
    activity fit equally and the biceps drill was never in the few returned."""
    tools = saying(BACK_AND_BICEPS)
    search(tools, use="MAIN_WORKOUT", available_equipment=GEAR)

    warm_up = search(tools, use="WARM_UP", available_equipment=GEAR)
    cool_down = search(tools, use="COOL_DOWN", available_equipment=GEAR)

    assert {"Light Band Biceps Curl", "Band Pull-Apart"} <= set(names(warm_up))
    assert {"Wall Biceps Stretch", "Upper Back Stretch"} <= set(names(cool_down))
    # after the easy cardio, every activity is for the back or the biceps
    for found in (warm_up, cool_down):
        specific = [item for item in found["exercises"] if item["movement_pattern"] != "CARDIO"]
        assert len(specific) >= 5
        for item in specific[:5]:
            assert {"Upper Back", "Lats", "Biceps"} & set(item["muscles"]), item["name"]


def test_without_a_muscle_in_the_message_the_main_exercises_found_rank_the_activities(
    saying, tools
):
    """Nothing said, nothing to go by but the main exercises the searches found, as before."""
    with_words = saying("a workout for today")
    for muscle in ("Chest", "Triceps"):
        search(with_words, use="MAIN_WORKOUT", muscle=muscle, available_equipment=GYM)
        search(tools, use="MAIN_WORKOUT", muscle=muscle, available_equipment=GYM)

    assert search(with_words, use="WARM_UP", available_equipment=GYM) == search(
        tools, use="WARM_UP", available_equipment=GYM
    )


def test_a_muscle_the_user_says_overrides_the_main_exercises_that_were_found(saying):
    """The user said chest; the main search found only exercises for the legs. What they said
    is the workout, and the activities for the chest come first."""
    tools = saying("chest day, 40 minutes, I have a bench and dumbbells")
    search(tools, use="MAIN_WORKOUT", muscle="Quadriceps", available_equipment=GYM)

    warm_up = search(tools, use="WARM_UP", available_equipment=GYM)
    cool_down = search(tools, use="COOL_DOWN", available_equipment=GYM)

    for found, chest_activity in (
        (warm_up, "Dynamic Chest Stretch"),
        (cool_down, "Doorway Chest Stretch"),
    ):
        specific = [
            item["name"] for item in found["exercises"] if item["movement_pattern"] != "CARDIO"
        ]
        assert chest_activity in specific[:3], specific


def test_the_muscles_are_read_from_the_latest_message_and_not_when_the_user_protects_them(saying):
    legs = saying("Leg day today, but my shoulder hurts")
    search(legs, use="MAIN_WORKOUT", available_equipment=[])

    warm_up = search(legs, use="WARM_UP", available_equipment=[])

    leg_drills = [
        item for item in warm_up["exercises"]
        if item["movement_pattern"] != "CARDIO" and item["suits_main"] != []
    ]
    first = [item["name"] for item in leg_drills[:3]]
    assert first
    assert "Arm Circles" not in first, first


def test_the_search_reads_what_the_user_said_only_for_a_warm_up_or_cool_down(saying):
    tools = saying("chest day")

    main = search(tools, use="MAIN_WORKOUT", available_equipment=GYM)

    # a main workout search is ranked as it always was: the muscles are spread
    assert len({item["muscles"][0] for item in main["exercises"] if item["muscles"]}) > 3


# --- searching the main workout by movement pattern (docs/exercise-fields.md) ---

OWN_MAIN = {
    "SQUAT": {"Barbell Back Squat", "Bodyweight Squat", "Goblet Squat", "Leg Press",
              "Smith Machine Squat"},
    "HINGE": {"Dumbbell Romanian Deadlift", "Glute Bridge", "Kettlebell Swing", "Romanian Deadlift"},
    "HORIZONTAL_PUSH": {"Barbell Bench Press", "Dumbbell Bench Press", "Push-Up"},
    "VERTICAL_PULL": {"Lat Pulldown", "Pull-Up"},
    "LUNGE": {"Walking Lunge"},
}  # fmt: skip


@pytest.mark.parametrize("pattern", sorted(OWN_MAIN))
def test_a_pattern_search_finds_the_imported_catalog_after_formiqs_own_exercises(tools, pattern):
    """Before the patterns were given to the imported exercises, a search for SQUAT found the five
    squats Formiq wrote and nothing else (live QA, 2026-10-19: the model searches a leg day by
    pattern). Formiq's own still come first: it wrote and described them."""
    found = search(tools, use="MAIN_WORKOUT", movement_pattern=pattern)

    own = OWN_MAIN[pattern]
    assert found["total_matches"] > len(own) * 2
    shown = names(found)
    assert set(shown[: len(own)]) == own
    assert all(item["movement_pattern"] == pattern for item in found["exercises"])


def test_a_muscle_search_for_the_main_workout_still_starts_with_formiqs_own(tools):
    found = search(tools, use="MAIN_WORKOUT", muscle="Chest")

    assert {"Barbell Bench Press", "Dumbbell Bench Press", "Push-Up"} <= set(names(found)[:4])
    assert found["total_matches"] > 30


@pytest.mark.parametrize(
    "pattern",
    ["SQUAT", "HINGE", "LUNGE", "HORIZONTAL_PUSH", "VERTICAL_PUSH", "HORIZONTAL_PULL",
     "VERTICAL_PULL", "CARRY", "ROTATION", "ISOLATION"],
)  # fmt: skip
def test_every_main_pattern_finds_exercises_a_proposal_can_use(tools, pattern):
    found = search(tools, use="MAIN_WORKOUT", movement_pattern=pattern)

    assert found["count"] >= 4
    assert all("MAIN_WORKOUT" in item["uses"] for item in found["exercises"])
