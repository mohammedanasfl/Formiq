"""A search that finds nothing for its section does not say the catalog has
nothing (live Gemini pass of 2026-10-16, B5).

The user asked to replace every main exercise with a rowing machine exercise.
The coach searched the main workout for the Rowing Machine, found nothing, and
said the catalog has no rowing machine exercises. It has one: Easy Rowing,
which Formiq uses for the warm-up and the cool-down (cardio is never a main
exercise: a proposal's main exercises are prescribed in reps). The search said
only "0 found", so a model could not tell "none anywhere" from "none for the
main workout".

A search by use that finds nothing now also names, apart from its results, a few
exercises that match every other filter and that Formiq uses for another
section: no id (they are not a choice for the section searched), at most
MAX_OTHER_USE_MATCHES of them, and nothing for a search that found something.
These tests run the real search tool on the seeded catalog (the test database,
never the dev one). They prove what the tool returns, not what Gemini says of it.
They require the local PostgreSQL container to be running.
"""

import json

import pytest

from app.agent import ConversationTurn
from app.agent.policy import known_ids
from app.ai import ToolCall, ToolResult
from app.services import CoachService
from app.tools.limits import MAX_OTHER_USE_MATCHES, MAX_SEARCH_RESULTS
from tests.coach import call, fake_provider, respond_turn, tool_turn
from tests.integration.test_coach_daily import create_user, received
from tests.integration.test_equipment_constraints import (  # noqa: F401 (fixtures)
    ids,
    run,
    search,
    terms,
    today,
    tools_for,
    user,
)

EASY_ROWING = {
    "name": "Easy Rowing",
    "uses": ["WARM_UP", "COOL_DOWN"],
    "equipment": ["Rowing Machine"],
}


def test_a_main_workout_search_for_the_rowing_machine_names_easy_rowing_for_its_own_uses(
    tools_for, user
):
    found = search(tools_for(), user, use="MAIN_WORKOUT", equipment="Rowing Machine")

    # nothing for the main workout, and said so apart from what the catalog does have
    assert (found["count"], found["total_matches"], found["exercises"]) == (0, 0, [])
    assert found["matches_for_other_uses"] == {"total": 1, "exercises": [EASY_ROWING]}


@pytest.mark.parametrize("section", ["WARM_UP", "COOL_DOWN"])
def test_the_sections_it_is_used_for_find_it_as_a_result_and_say_nothing_more(
    tools_for, user, section
):
    found = search(tools_for(), user, use=section, equipment="Rowing Machine")

    assert [item["name"] for item in found["exercises"]] == ["Easy Rowing"]
    assert "matches_for_other_uses" not in found


def test_a_search_without_a_use_is_not_a_search_for_a_section(tools_for, user):
    found = search(tools_for(), user, equipment="Rowing Machine")

    assert [item["name"] for item in found["exercises"]] == ["Easy Rowing"]
    assert "matches_for_other_uses" not in found


@pytest.mark.parametrize(
    "filters",
    [
        {"use": "MAIN_WORKOUT"},
        {"use": "MAIN_WORKOUT", "muscle": "Chest"},
        {"use": "MAIN_WORKOUT", "available_equipment": []},
        {"use": "WARM_UP", "available_equipment": ["Dumbbell"]},
        {"muscle": "Quadriceps", "available_equipment": ["Dumbbell"]},
        {"movement_pattern": "HORIZONTAL_PUSH"},
    ],
)
def test_a_search_that_finds_something_is_as_it_was(tools_for, user, filters):
    found = search(tools_for(), user, **filters)

    assert found["count"] > 0
    assert "matches_for_other_uses" not in found
    assert set(found) <= {"exercises", "count", "total_matches", "excluded_equipment"}


def test_a_search_that_matches_nothing_even_without_its_use_says_so_by_saying_nothing_more(
    tools_for, user
):
    # no pull exercise uses the rowing machine in the catalog: nothing is hidden by the use
    found = search(
        tools_for(), user, use="MAIN_WORKOUT", equipment="Rowing Machine", movement_pattern="LUNGE"
    )

    assert found["count"] == 0
    assert "matches_for_other_uses" not in found


def test_what_the_user_lacks_still_leaves_the_results_and_the_disclosure_alike(tools_for, user):
    # They said they have no rowing machine: a workout search leaves it out whatever the model
    # asks for, and nothing that needs one is offered for another section either.
    found = search(
        tools_for("I don't have a rowing machine."), user, use="MAIN_WORKOUT", equipment="Rowing Machine"
    )

    assert found["count"] == 0
    assert "Rowing Machine" in found["excluded_equipment"]
    assert "matches_for_other_uses" not in found


def test_the_disclosure_is_bounded(tools_for, user):
    # dumbbell exercises are main exercises: for a cool-down there are many, and only a few are named
    found = search(tools_for(), user, use="COOL_DOWN", equipment="Dumbbell")

    other = found["matches_for_other_uses"]
    assert found["count"] == 0
    assert other["total"] > MAX_OTHER_USE_MATCHES
    assert len(other["exercises"]) == MAX_OTHER_USE_MATCHES == 3
    assert all("MAIN_WORKOUT" in item["uses"] and "COOL_DOWN" not in item["uses"] for item in other["exercises"])
    # and the whole result is small
    assert len(json.dumps(found)) < 1_500
    assert MAX_OTHER_USE_MATCHES < MAX_SEARCH_RESULTS


def test_an_exercise_the_disclosure_names_is_not_a_choice_for_the_section_searched(
    tools_for, user, ids
):
    tools = tools_for()
    output = run(tools, user, "search_exercises", use="MAIN_WORKOUT", equipment="Rowing Machine")

    # no id: no proposal can be built from it, and the graph's id grounding does not know it
    assert all("exercise_id" not in item for item in output["output"]["matches_for_other_uses"]["exercises"])
    searched = ToolCall(
        name="search_exercises", arguments={"use": "MAIN_WORKOUT", "equipment": "Rowing Machine"}
    )
    grounded = known_ids("", [ToolResult(call=searched, result=output)])
    assert ids["Easy Rowing"] not in grounded


def test_the_model_is_sent_the_disclosure_with_the_empty_result(service_session, profile_fields, terms):
    """The turn of the live pass (T3b): after "I don't have my dumbbells today", the
    user asks for a rowing machine exercise for every main exercise, and the model
    searches the main workout by that equipment."""
    user_id = create_user(service_session, "rowing@example.com", profile_fields)
    provider = fake_provider(
        tool_turn(call("search_exercises", use="MAIN_WORKOUT", equipment="Rowing Machine")),
        respond_turn(
            "Formiq has no rowing machine exercise for the main workout.",
            "EXERCISE",
            "RETRIEVE_THEN_ANSWER",
        ),
    )
    history = [
        ConversationTurn("user", "Actually, I don't have my dumbbells today."),
        ConversationTurn("coach", "Since you don't have dumbbells today, here is a bodyweight version."),
    ]

    CoachService(service_session, provider, proposal_terms=terms).answer(
        user_id, "Replace every main exercise with a rowing machine exercise.", history
    )

    found = received(provider, 1)["search_exercises"]["output"]
    assert found["excluded_equipment"] == ["Dumbbell"]  # as in the live trace
    assert found["count"] == 0 and found["matches_for_other_uses"]["exercises"] == [EASY_ROWING]
