"""What the coach's tools do with the equipment saved in the user's profile.

get_user_profile tells the model what the profile says, by the catalog's names and never an
id; and every workout search and proposal leaves out what the user lacks, which now includes
every piece the saved list does not hold (or every piece, for a user with no equipment) until
the conversation says otherwise. The services are mocks: no database is read.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.agent import ConversationTurn
from app.ai import ToolCall
from app.approvals import ProposalTerms
from app.services import (
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.tools import FormiqTools
from app.tools.equipment import saved_equipment
from app.services.coach_service import read_equipment

USER = 7
CATALOG = [
    SimpleNamespace(id=1, name="Dumbbell", is_active=True),
    SimpleNamespace(id=2, name="Bench", is_active=True),
    SimpleNamespace(id=3, name="Resistance Band", is_active=True),
    SimpleNamespace(id=4, name="Barbell", is_active=True),
]
NAMES = [item.name for item in CATALOG]
HOME = saved_equipment(["Dumbbell", "Resistance Band"], none=False)
BODYWEIGHT = saved_equipment([], none=True)
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


def profile(equipment=(), no_equipment=False):
    return SimpleNamespace(
        first_name="Asha", last_name="Rao", age=30, height_cm=165.0, weight_kg=60.0,
        gender="female", fitness_experience="beginner", goal="fat_loss", target_weight_kg=None,
        goal_period_weeks=None, training_frequency_per_week=3, training_location="home",
        activity_level="moderate", sleep_hours=7.0, dietary_preference=None,
        no_equipment=no_equipment, equipment=list(equipment),
    )  # fmt: skip


def tools_for(saved_profile=None, stated=None, message="Give me a workout."):
    users, profiles = Mock(spec=UserService), Mock(spec=UserProfileService)
    catalog = Mock(spec=ExerciseCatalogService)
    users.get_user_by_id.return_value = SimpleNamespace(id=USER)
    profiles.get_profile_by_user_id.return_value = saved_profile or profile()
    catalog.list_equipment.return_value = CATALOG
    catalog.list_muscle_groups.return_value = []
    catalog.list_exercises.return_value = []
    tools = FormiqTools(
        users=users,
        profiles=profiles,
        plans=Mock(spec=WorkoutPlanService),
        sessions=Mock(spec=WorkoutSessionService),
        catalog=catalog,
        end_read=Mock(),
        proposal_terms=ProposalTerms(clock=lambda: NOW, ttl=timedelta(minutes=30)),
        conversation=[("user", message)],
        stated=stated,
    )
    return tools, catalog


def run(tools, tool, **arguments):
    (result,) = tools.run([ToolCall(name=tool, arguments=arguments)], user_id=USER)
    return result


# --- get_user_profile ---


def test_the_profile_lists_the_saved_equipment_by_name():
    tools, _ = tools_for(profile([CATALOG[2], CATALOG[0]]))

    output = run(tools, "get_user_profile")["output"]

    assert output["equipment"] == {"status": "LISTED", "equipment": ["Dumbbell", "Resistance Band"]}


def test_the_profile_says_when_the_user_has_no_equipment():
    tools, _ = tools_for(profile(no_equipment=True))

    assert run(tools, "get_user_profile")["output"]["equipment"] == {
        "status": "NONE",
        "equipment": [],
    }


def test_the_profile_says_when_it_never_said():
    tools, _ = tools_for(profile())

    assert run(tools, "get_user_profile")["output"]["equipment"] == {
        "status": "NOT_SAVED",
        "equipment": [],
    }


def test_equipment_retired_since_is_not_offered_to_the_model():
    retired = SimpleNamespace(id=9, name="Old Machine", is_active=False)
    tools, _ = tools_for(profile([CATALOG[0], retired]))

    assert run(tools, "get_user_profile")["output"]["equipment"]["equipment"] == ["Dumbbell"]


def test_the_model_is_never_given_an_equipment_id():
    tools, _ = tools_for(profile([CATALOG[0], CATALOG[1]]))

    output = run(tools, "get_user_profile")["output"]

    assert set(output["equipment"]) == {"status", "equipment"}
    assert all(isinstance(name, str) for name in output["equipment"]["equipment"])
    assert "equipment_ids" not in str(output) and "'id'" not in str(output)


def test_the_profile_still_never_gives_contact_details():
    tools, _ = tools_for(profile([CATALOG[0]]))

    output = run(tools, "get_user_profile")["output"]

    assert not {"email", "phone"} & set(output["profile"])
    assert set(output) == {"user_id", "profile", "equipment"}


# --- a workout search leaves out what the user lacks ---


def search(tools, catalog, **arguments):
    """The filters and the equipment limit of the search's own catalog read (the first: an
    empty result reads the catalog again to say what matched for another use)."""
    run(tools, "search_exercises", **arguments)
    call = catalog.list_exercises.call_args_list[0]
    return call.args[0], call.kwargs["available_equipment_ids"]


def test_a_user_with_no_equipment_is_offered_exercises_that_need_none():
    stated, _ = read_equipment([], "Give me a workout.", NAMES, BODYWEIGHT)
    tools, catalog = tools_for(stated=stated)

    filters, available = search(tools, catalog, use="MAIN_WORKOUT")

    assert filters.use == "MAIN_WORKOUT"
    # an empty list is the repository's "no equipment but none": only what needs none
    assert available == []


def test_a_user_with_saved_equipment_is_offered_only_what_it_needs():
    stated, _ = read_equipment([], "Give me a workout.", NAMES, HOME)
    tools, catalog = tools_for(stated=stated)

    _, available = search(tools, catalog, use="MAIN_WORKOUT")

    # Dumbbell and Resistance Band: not the bench or the barbell the profile does not list
    assert available == [1, 3]


def test_the_search_says_which_equipment_it_left_out():
    stated, _ = read_equipment([], "Give me a workout.", NAMES, HOME)
    tools, _ = tools_for(stated=stated)

    output = run(tools, "search_exercises", use="MAIN_WORKOUT")["output"]

    assert output["excluded_equipment"] == ["Barbell", "Bench"]


def test_a_user_whose_profile_never_said_is_offered_everything_as_before():
    stated, _ = read_equipment([], "Give me a workout.", NAMES, None)
    tools, catalog = tools_for(stated=stated)

    _, available = search(tools, catalog, use="MAIN_WORKOUT")

    assert available is None


def test_what_the_user_says_today_replaces_the_profile_for_the_search():
    stated, _ = read_equipment([], "I have dumbbells and a bench today.", NAMES, BODYWEIGHT)
    tools, catalog = tools_for(stated=stated, message="I have dumbbells and a bench today.")

    _, available = search(tools, catalog, use="MAIN_WORKOUT")

    assert available == [1, 2]


def test_a_correction_from_earlier_in_the_conversation_still_holds():
    history = [ConversationTurn("user", "I don't have a bench today."), ConversationTurn("coach", "Ok.")]
    stated, _ = read_equipment(history, "Another one please.", NAMES, saved_equipment(NAMES, False))
    tools, catalog = tools_for(stated=stated)

    _, available = search(tools, catalog, use="MAIN_WORKOUT")

    assert available == [1, 3, 4]


def test_a_search_by_name_is_not_narrowed_by_the_profile():
    # without a use the search is a lookup (what is this exercise?), as it always was
    stated, _ = read_equipment([], "Give me a workout.", NAMES, BODYWEIGHT)
    tools, catalog = tools_for(stated=stated)

    _, available = search(tools, catalog, name="Bench Press")

    assert available is None


# --- a proposal fits what the user has ---


def proposal_with(exercise_equipment):
    main = SimpleNamespace(
        id=20, name="Goblet Squat", difficulty="BEGINNER", uses=["MAIN_WORKOUT"], is_active=True,
        movement_pattern="SQUAT", equipment=exercise_equipment,
        muscles=[SimpleNamespace(muscle_group=SimpleNamespace(name="Quadriceps"), role="PRIMARY")],
    )  # fmt: skip
    return main, {
        "name": "Leg day",
        "warm_up": [{"exercise_id": 10, "sets": 1, "duration_seconds": 60}],
        "exercises": [{"exercise_id": 20, "sets": 3, "reps": 10}],
        "cool_down": [{"exercise_id": 11, "sets": 1, "duration_seconds": 60}],
    }


def activity(exercise_id, use):
    return SimpleNamespace(
        id=exercise_id, name=f"Activity {exercise_id}", difficulty="BEGINNER", uses=[use],
        is_active=True, movement_pattern="CARDIO", equipment=[],
        muscles=[SimpleNamespace(muscle_group=SimpleNamespace(name="Calves"), role="PRIMARY")],
    )  # fmt: skip


def propose(tools, catalog, exercise_equipment, **extra):
    main, arguments = proposal_with(exercise_equipment)
    found = {10: activity(10, "WARM_UP"), 11: activity(11, "COOL_DOWN"), 20: main}
    catalog.get_exercise_by_id.side_effect = found.get
    return run(tools, "propose_workout_plan", **arguments, **extra)


def test_a_proposal_with_equipment_is_refused_for_a_user_with_no_equipment():
    stated, _ = read_equipment([], "Give me a leg workout.", NAMES, BODYWEIGHT)
    tools, catalog = tools_for(stated=stated)

    result = propose(tools, catalog, [CATALOG[0]])

    assert result["error"]["code"] == "INVALID_INPUT"
    assert "exercise 20 needs Dumbbell, which the user cannot use" in result["error"]["message"]


def test_a_proposal_with_a_piece_the_profile_does_not_list_is_refused():
    stated, _ = read_equipment([], "Give me a leg workout.", NAMES, HOME)
    tools, catalog = tools_for(stated=stated)

    result = propose(tools, catalog, [CATALOG[3]])

    assert "exercise 20 needs Barbell, which the user cannot use" in result["error"]["message"]


def test_a_proposal_with_a_piece_the_user_said_they_have_today_is_not_refused_for_it():
    stated, _ = read_equipment(
        [], "I have a barbell at the gym today.", NAMES, HOME
    )
    tools, catalog = tools_for(stated=stated)

    result = propose(tools, catalog, [CATALOG[3]])

    # whatever else the proposal is checked for, the barbell is not what refuses it
    assert "cannot use" not in str(result)


def test_the_model_may_name_what_the_profile_lists_as_what_the_user_has():
    stated, _ = read_equipment([], "Give me a leg workout.", NAMES, HOME)
    tools, catalog = tools_for(stated=stated)

    result = propose(tools, catalog, [CATALOG[0]], available_equipment=["Dumbbell", "Resistance Band"])

    assert "available_equipment is only what the user said" not in str(result)


def test_the_model_may_not_name_equipment_the_profile_does_not_list_as_the_users():
    stated, _ = read_equipment([], "Give me a leg workout.", NAMES, HOME)
    tools, catalog = tools_for(stated=stated)

    result = propose(tools, catalog, [CATALOG[0]], available_equipment=["Dumbbell", "Barbell"])

    message = result["error"]["message"]
    assert "available_equipment is only what the user said they have" in message
    # a piece the saved list does not hold is one they lack, as when they say "only dumbbells"
    assert "they do not have Barbell:" in message


def test_no_equipment_in_the_profile_lets_the_model_send_an_empty_list():
    stated, _ = read_equipment([], "Give me a leg workout.", NAMES, BODYWEIGHT)
    tools, catalog = tools_for(stated=stated)

    result = propose(tools, catalog, [], available_equipment=[])

    assert "available_equipment is only what the user said" not in str(result)
    assert "cannot use" not in str(result)
