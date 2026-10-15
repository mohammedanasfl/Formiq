"""The user's equipment, as the coach's tools hold it, on the seeded catalog.

A tool reads equipment by its common names (plurals, "a pair of dumbbells",
"cable", "pullup bar", "nothing"), and never reads a name that negates or
doubts a piece as one the user has. What the user said in the conversation
holds for every workout: equipment they said they lack is left out of workout
searches and refused in a proposal, whatever the model gives, and a proposal
may say they have only what they said they have.

The model is not involved here, except in the last test, where it is scripted.
They require the local PostgreSQL container to be running.
"""

from unittest.mock import Mock

import pytest

from app.agent import ConversationTurn
from app.ai import ToolCall
from app.api.dependencies import PROPOSAL_TTL
from app.approvals import ProposalTerms
from app.services import (
    CoachService,
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.tools import FormiqTools
from tests.coach import call, fake_provider, respond_turn, tool_turn
from tests.integration.test_coach_daily import TODAY, create_user, daily_reads, received
from tests.integration.test_plan_proposals import (
    Clock,
    bodyweight,
    main_of,
    problem,
    proposal,
    workout,
)
from tests.integration.workout_plans import add_user


@pytest.fixture(autouse=True)
def today(monkeypatch):
    """Formiq's date, fixed for these tests."""
    monkeypatch.setattr("app.tools.formiq_tools.utc_today", lambda: TODAY)


@pytest.fixture
def terms():
    return ProposalTerms(clock=Clock(), ttl=PROPOSAL_TTL)


@pytest.fixture
def ids(catalog_exercise_ids):
    return catalog_exercise_ids


@pytest.fixture
def user(db_session):
    return add_user(db_session, "equipment@example.com")


@pytest.fixture
def tools_for(db_session, terms):
    """The tools of a request whose user wrote these words (None: not known)."""

    def make(*words):
        return FormiqTools(
            users=UserService(db_session),
            profiles=UserProfileService(db_session),
            plans=WorkoutPlanService(db_session),
            sessions=WorkoutSessionService(db_session),
            catalog=ExerciseCatalogService(db_session),
            end_read=Mock(),
            today=TODAY,
            proposal_terms=terms,
            conversation=[("user", text) for text in words] if words else None,
        )

    return make


def run(tools, user, name, **arguments):
    (result,) = tools.run([ToolCall(name=name, arguments=arguments)], user_id=user.id)
    return result


def search(tools, user, **filters):
    result = run(tools, user, "search_exercises", **filters)
    assert "output" in result, result
    return result["output"]


def propose(tools, user, **arguments):
    (result,) = tools.run([proposal(**arguments)], user_id=user.id)
    return result


def dumbbell_workout(ids, **fields):
    return workout(
        ids,
        *main_of(
            ids, "Goblet Squat", "Dumbbell Shoulder Press", "One-Arm Dumbbell Row", "Bird Dog"
        ),
        **fields,
    )


# --- names ---


@pytest.mark.parametrize(
    ("said", "means"),
    [
        (["dumbbells"], ["Dumbbell"]),
        (["a pair of dumbbells"], ["Dumbbell"]),
        (["resistance bands"], ["Resistance Band"]),
        (["bands"], ["Resistance Band"]),
        (["kettlebells"], ["Kettlebell"]),
        (["cable"], ["Cable Machine"]),
        (["pullup bar"], ["Pull-up Bar"]),
        (["nothing"], []),
        (["nothing available"], []),
        (["without equipment"], []),
        (["Dumbbells", "bands", "bodyweight"], ["Dumbbell", "Resistance Band"]),
    ],
)
def test_a_search_reads_equipment_by_its_common_names(tools_for, user, said, means):
    tools = tools_for()

    def found(available):
        return search(tools, user, use="MAIN_WORKOUT", available_equipment=available)

    assert found(said) == found(means)


@pytest.mark.parametrize(
    ("said", "named"),
    [
        (["no dumbbells"], "'no dumbbells' does not say the user has Dumbbell"),
        (
            ["bands", "maybe a kettlebell"],
            "'maybe a kettlebell' does not say the user has Kettlebell",
        ),
        (["dumbbells if available"], "'dumbbells if available' does not say the user has Dumbbell"),
    ],
)
def test_a_name_that_negates_or_doubts_a_piece_is_never_read_as_the_users(
    tools_for, user, ids, said, named
):
    tools = tools_for()

    searched = run(tools, user, "search_exercises", use="MAIN_WORKOUT", available_equipment=said)
    proposed = propose(tools, user, **dumbbell_workout(ids, available_equipment=said))

    for result in (searched, proposed):
        message = problem(result)
        assert message.startswith(named)
        assert "give what they lack in unavailable_equipment" in message


def test_what_a_proposal_says_the_user_lacks_may_be_negated(tools_for, user, ids):
    tools = tools_for()

    result = propose(tools, user, **dumbbell_workout(ids, unavailable_equipment=["no dumbbells"]))

    assert problem(result).startswith(
        f"exercise {ids['Goblet Squat']} needs Dumbbell, which the user cannot use"
    )


def test_an_unknown_name_is_still_refused_never_guessed(tools_for, user):
    result = run(tools_for(), user, "search_exercises", available_equipment=["Dumbells"])

    assert problem(result).startswith("the catalog has no equipment 'Dumbells'; it has ")


# --- what the user said ---


@pytest.mark.parametrize(
    "said",
    ["I don't have any equipment.", "No equipment, bodyweight only", "I have no equipment at home"],
)
def test_a_user_without_equipment_gets_only_what_needs_none(tools_for, user, ids, said):
    tools = tools_for("Create a full-body workout I can do at home.", said)

    found = search(tools, user, use="MAIN_WORKOUT", difficulty="BEGINNER")

    assert found["count"] > 0
    assert all(item["equipment"] == [] for item in found["exercises"])
    assert "Dumbbell" in found["excluded_equipment"]
    # the same, whatever the model gives: Formiq refuses what needs equipment
    refused = propose(tools, user, **dumbbell_workout(ids))
    assert problem(refused).startswith(
        f"exercise {ids['Goblet Squat']} needs Dumbbell, which the user cannot use"
    )


def test_a_search_for_anything_but_a_workout_is_not_narrowed(tools_for, user):
    tools = tools_for("I don't have any equipment.")

    found = search(tools, user, muscle="Chest")

    assert "excluded_equipment" not in found
    assert any(item["equipment"] for item in found["exercises"])


def test_a_user_with_some_equipment_gets_it_and_nothing_else(tools_for, user, ids):
    tools = tools_for("I only have dumbbells and resistance bands. Make me a workout")

    found = search(tools, user, use="MAIN_WORKOUT")
    assert {piece for item in found["exercises"] for piece in item["equipment"]} <= {
        "Dumbbell",
        "Resistance Band",
    }
    # what they have, by any name, makes a proposal
    accepted = propose(
        tools, user, **dumbbell_workout(ids, available_equipment=["dumbbells", "resistance bands"])
    )
    assert "output" in accepted, accepted
    assert "output" in propose(tools, user, **dumbbell_workout(ids))
    # what needs anything else is refused, said or not
    barbell = main_of(ids, "Barbell Back Squat", "Push-Up", "Resistance Band Row", "Bird Dog")
    assert problem(propose(tools, user, **workout(ids, *barbell))).startswith(
        f"exercise {ids['Barbell Back Squat']} needs Barbell, Squat Rack, which the user cannot use"
    )


@pytest.mark.parametrize(
    ("words", "available", "message"),
    [
        (
            ("I only have dumbbells",),
            ["Dumbbell", "Bench"],
            "available_equipment is only what the user said they have, and the user said they "
            "do not have Bench",
        ),
        (
            ("I don't have dumbbells, only bands",),
            ["Dumbbell", "Resistance Band"],
            "available_equipment is only what the user said they have, and the user said they "
            "do not have Dumbbell",
        ),
        (
            (
                "What is a kettlebell swing?",
                "Is a kettlebell good for beginners?",
                "Make me a workout",
            ),
            ["Kettlebell"],
            "available_equipment is only what the user said they have, and the user did not "
            "say they have Kettlebell",
        ),
        (
            ("I'm at the gym today",),
            ["Dumbbell", "Barbell"],
            "available_equipment is only what the user said they have, and the user did not "
            "say they have Dumbbell, Barbell",
        ),
    ],
)
def test_a_proposal_may_say_the_user_has_only_what_they_said_they_have(
    tools_for, user, ids, words, available, message
):
    tools = tools_for(*words)

    result = propose(tools, user, **dumbbell_workout(ids, available_equipment=available))

    assert problem(result).startswith(message)
    assert problem(result).endswith(
        ": give the equipment they said they have ([] for none), or leave available_equipment "
        "out when they did not say"
    )


def test_saying_no_equipment_is_always_allowed(tools_for, user, ids):
    tools = tools_for("I have dumbbells")

    result = propose(tools, user, **bodyweight(ids), available_equipment=["Resistance Band"])

    assert problem(result).startswith(
        "available_equipment is only what the user said they have, and the user did not say "
        "they have Resistance Band"
    )
    pushup = main_of(ids, "Push-Up", "Walking Lunge", "Bird Dog", "Bodyweight Squat")
    # fewer pieces than they have is never more than they said
    for none in ([], ["bodyweight"]):
        result = propose(tools, user, **workout(ids, *pushup, available_equipment=none))
        assert "the user did not say" not in str(result)


def test_without_the_users_words_nothing_is_assumed(tools_for, user, ids):
    tools = tools_for()

    result = propose(tools, user, **dumbbell_workout(ids, available_equipment=["Dumbbell"]))

    assert "output" in result, result
    assert "excluded_equipment" not in search(tools, user, use="MAIN_WORKOUT")


# --- through the coach ---


def test_the_coach_holds_what_the_user_said_whatever_the_model_proposes(
    service_session, profile_fields, ids, terms
):
    user_id = create_user(service_session, "coach-equipment@example.com", profile_fields)
    provider = fake_provider(
        daily_reads(),
        # a catalog search, which is not for a workout, finds a dumbbell exercise
        tool_turn(
            call("search_exercises", muscle="Quadriceps", available_equipment=["Dumbbell"]),
            call("search_exercises", use="MAIN_WORKOUT"),
        ),
        # and the model forgets what the user said about their equipment
        tool_turn(proposal(**workout(ids, *main_of(ids, "Goblet Squat", "Push-Up")))),
        respond_turn("I could not build that workout.", "DAILY_WORKOUT", "CANNOT_ANSWER"),
    )
    history = [
        ConversationTurn("user", "I don't have any equipment."),
        ConversationTurn("coach", "Got it: bodyweight only."),
    ]

    answer = CoachService(service_session, provider, proposal_terms=terms).answer(
        user_id, "Create a full-body workout I can do at home.", history
    )

    # the user's earlier words reached the tools: the proposal needing dumbbells
    # was refused, and none reaches the user
    refusal = received(provider, 3)["propose_workout_plan"]["error"]
    assert refusal["message"].startswith(
        f"exercise {ids['Goblet Squat']} needs Dumbbell, which the user cannot use"
    )
    assert answer.proposal is None


# --- a search for the exercises that use one piece, named: never by an id ---
#
# The live regression pass found `equipment_id` unusable: no tool gives the model
# an equipment id, so each use was refused as not grounded and cost a round.
# search_exercises takes the piece's name, as available_equipment does, and
# Formiq resolves it.


@pytest.mark.parametrize(
    ("said", "piece"),
    [
        ("Dumbbell", "Dumbbell"),
        ("dumbbells", "Dumbbell"),
        ("a dumbbell", "Dumbbell"),
        ("resistance bands", "Resistance Band"),
        ("band", "Resistance Band"),
        ("kettlebells", "Kettlebell"),
        ("kettle bell", "Kettlebell"),
        ("cable", "Cable Machine"),
        ("cable machine", "Cable Machine"),
        ("pullup bar", "Pull-up Bar"),
        ("chin up bar", "Pull-up Bar"),
        ("doorway bar", "Pull-up Bar"),
    ],
)
def test_a_search_names_the_piece_an_exercise_must_use(tools_for, user, said, piece):
    found = search(tools_for(), user, equipment=said)

    assert found["exercises"], f"the catalog has exercises that use {piece}"
    assert all(piece in item["equipment"] for item in found["exercises"])


def test_a_named_piece_combines_with_the_other_filters(tools_for, user):
    found = search(tools_for(), user, equipment="dumbbells", use="MAIN_WORKOUT", muscle="Chest")

    assert found["exercises"]
    assert all("Dumbbell" in item["equipment"] for item in found["exercises"])
    assert all("MAIN_WORKOUT" in item["uses"] for item in found["exercises"])


def test_an_unknown_piece_is_an_error_that_lists_the_catalogs_equipment(tools_for, user):
    result = run(tools_for(), user, "search_exercises", equipment="flux capacitor")

    assert result["error"]["code"] == "INVALID_INPUT"
    assert "the catalog has no equipment 'flux capacitor'" in result["error"]["message"]
    assert "Dumbbell" in result["error"]["message"]


@pytest.mark.parametrize("said", ["bodyweight", "no equipment", "nothing"])
def test_no_equipment_is_not_a_piece_and_points_to_the_empty_list(tools_for, user, said):
    result = run(tools_for(), user, "search_exercises", equipment=said)

    assert result["error"]["code"] == "INVALID_INPUT"
    assert "available_equipment as an empty list" in result["error"]["message"]


@pytest.mark.parametrize("said", ["no dumbbells", "maybe a kettlebell"])
def test_a_name_that_negates_or_doubts_the_piece_is_refused(tools_for, user, said):
    result = run(tools_for(), user, "search_exercises", equipment=said)

    assert result["error"]["code"] == "INVALID_INPUT"
    assert "does not name a piece of equipment an exercise must use" in result["error"]["message"]


def test_an_id_is_not_an_argument_of_the_search(tools_for, user):
    result = run(tools_for(), user, "search_exercises", equipment_id=3, use="MAIN_WORKOUT")

    assert result["error"]["code"] == "INVALID_INPUT"


def test_the_empty_list_still_finds_what_needs_no_equipment(tools_for, user):
    found = search(tools_for(), user, available_equipment=[], use="MAIN_WORKOUT")

    assert found["exercises"]
    assert all(item["equipment"] == [] for item in found["exercises"])


def test_equipment_the_user_lacks_stays_out_of_a_workout_search_named_or_not(tools_for, user):
    tools = tools_for("I don't have any dumbbells.")

    found = search(tools, user, use="MAIN_WORKOUT", equipment="dumbbells")

    # a piece the user lacks is found by no workout search, and Formiq says so
    assert found["exercises"] == []
    assert found["excluded_equipment"] == ["Dumbbell"]


def test_a_piece_that_no_exercise_needs_is_no_error_just_nothing_found(tools_for, user, db_session):
    from tests.integration.catalog import add_equipment

    add_equipment(db_session, "Test Unused Sled")

    found = search(tools_for(), user, equipment="test unused sled")

    assert found == {"exercises": [], "count": 0, "total_matches": 0}


def test_the_coach_searches_by_a_named_piece_without_a_wasted_round(
    service_session, profile_fields, terms
):
    user_id = create_user(service_session, "named-piece@example.com", profile_fields)
    provider = fake_provider(
        tool_turn(call("search_exercises", equipment="kettlebells", use="MAIN_WORKOUT")),
        respond_turn("Kettlebell exercises exist.", "EXERCISE", "RETRIEVE_THEN_ANSWER"),
    )

    CoachService(service_session, provider, proposal_terms=terms).answer(
        user_id, "Which exercises use kettlebells?"
    )

    searched = received(provider, 1)["search_exercises"]
    assert "output" in searched and searched["output"]["count"] > 0
    assert provider.generate_turn.call_count == 2  # the search, then the answer: nothing refused
