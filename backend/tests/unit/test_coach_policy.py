"""Tests for the coach's decision policy (app.agent.policy): the intents and
decisions, which decisions each intent allows, how tool results are judged, and
which ids a turn may use. The policy is pure, so these tests need no model."""

import dataclasses
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.agent import COACH_INSTRUCTIONS, POLICY, RESPOND, CoachDecision, Decision, Intent
from app.agent.policy import (
    MAX_REPLY_LENGTH,
    MISSING_ERROR_CODES,
    DataStatus,
    Respond,
    check_decision,
    data_status,
    known_ids,
    tools_used,
    ungrounded_ids,
)
from app.ai import ToolCall, ToolResult
from app.tools import TOOL_DECLARATIONS, ToolErrorCode

DATA = {"output": {"value": 1}}


def result(name, value=DATA, **arguments):
    return ToolResult(call=ToolCall(name=name, arguments=arguments), result=value)


def error(code):
    return {"error": {"code": code, "message": "..."}}


# vocabulary


def test_the_intents_and_decisions():
    assert [intent.value for intent in Intent] == [
        "GENERAL_FITNESS",
        "PROFILE",
        "WORKOUT_PLAN",
        "WORKOUT_HISTORY",
        "EXERCISE",
        "ADAPTATION",
        "SAFETY_SENSITIVE",
        "AMBIGUOUS",
    ]
    assert [decision.value for decision in Decision] == [
        "ANSWER",
        "RETRIEVE_THEN_ANSWER",
        "ASK_CLARIFICATION",
        "SAFE_REDIRECT",
        "CANNOT_ANSWER",
    ]


def test_every_intent_has_a_policy_with_real_tools():
    tool_names = {tool.name for tool in TOOL_DECLARATIONS}

    assert set(POLICY) == set(Intent)
    for policy in POLICY.values():
        assert policy.description and policy.decisions
        assert policy.data_tools <= tool_names


def test_only_general_and_exercise_questions_may_be_answered_without_data():
    assert {intent for intent, policy in POLICY.items() if Decision.ANSWER in policy.decisions} == {
        Intent.GENERAL_FITNESS,
        Intent.EXERCISE,
    }


def test_questions_about_the_users_data_name_the_tools_that_hold_it():
    assert POLICY[Intent.PROFILE].data_tools == {"get_user_profile"}
    assert POLICY[Intent.WORKOUT_PLAN].data_tools == {"get_workout_plan"}
    assert POLICY[Intent.WORKOUT_HISTORY].data_tools == {"get_workout_session"}
    assert POLICY[Intent.EXERCISE].data_tools == {"get_exercise", "search_exercises"}
    assert POLICY[Intent.ADAPTATION].data_tools == {
        "get_user_profile",
        "get_workout_plan",
        "get_workout_session",
    }
    # a decision answered from data needs a tool to get it from
    for policy in POLICY.values():
        if Decision.RETRIEVE_THEN_ANSWER in policy.decisions:
            assert policy.data_tools


def test_safety_sensitive_and_ambiguous_requests_have_one_way_out():
    assert POLICY[Intent.SAFETY_SENSITIVE].decisions == {Decision.SAFE_REDIRECT}
    assert POLICY[Intent.AMBIGUOUS].decisions == {Decision.ASK_CLARIFICATION}


# check_decision


@pytest.mark.parametrize(
    ("intent", "decision", "results"),
    [
        (Intent.GENERAL_FITNESS, Decision.ANSWER, []),
        (Intent.PROFILE, Decision.RETRIEVE_THEN_ANSWER, [result("get_user_profile")]),
        (Intent.PROFILE, Decision.CANNOT_ANSWER, []),
        (Intent.PROFILE, Decision.ASK_CLARIFICATION, []),
        (Intent.WORKOUT_PLAN, Decision.RETRIEVE_THEN_ANSWER, [result("get_workout_plan")]),
        (Intent.WORKOUT_HISTORY, Decision.RETRIEVE_THEN_ANSWER, [result("get_workout_session")]),
        (Intent.EXERCISE, Decision.ANSWER, []),
        (Intent.EXERCISE, Decision.RETRIEVE_THEN_ANSWER, [result("search_exercises")]),
        (Intent.ADAPTATION, Decision.RETRIEVE_THEN_ANSWER, [result("get_workout_plan")]),
        (Intent.SAFETY_SENSITIVE, Decision.SAFE_REDIRECT, []),
        (Intent.AMBIGUOUS, Decision.ASK_CLARIFICATION, []),
        (Intent.GENERAL_FITNESS, Decision.SAFE_REDIRECT, []),
        # data that was cut by a tool's limits still counts as data
        (
            Intent.WORKOUT_HISTORY,
            Decision.RETRIEVE_THEN_ANSWER,
            [result("get_workout_session", {"output": {"truncated": True}})],
        ),
        # one tool's data is enough, whatever else failed
        (
            Intent.WORKOUT_HISTORY,
            Decision.RETRIEVE_THEN_ANSWER,
            [result("get_workout_plan", error("TOOL_ERROR")), result("get_workout_session")],
        ),
    ],
)
def test_acceptable_decisions(intent, decision, results):
    assert check_decision(intent, decision, results) is None


@pytest.mark.parametrize(
    ("intent", "decision", "results", "reason"),
    [
        # stored data answered from memory
        (Intent.PROFILE, Decision.ANSWER, [], "ANSWER is not a decision for a PROFILE"),
        (Intent.WORKOUT_HISTORY, Decision.ANSWER, [], "not a decision"),
        (Intent.ADAPTATION, Decision.ANSWER, [], "not a decision"),
        # claimed retrieval without the data
        (Intent.PROFILE, Decision.RETRIEVE_THEN_ANSWER, [], "none was returned"),
        # data from the wrong tool
        (
            Intent.WORKOUT_HISTORY,
            Decision.RETRIEVE_THEN_ANSWER,
            [result("get_workout_plan"), result("get_user_profile")],
            "get_workout_session returned",
        ),
        # missing, failed and malformed results are not data
        (
            Intent.WORKOUT_HISTORY,
            Decision.RETRIEVE_THEN_ANSWER,
            [result("get_workout_session", error("RESOURCE_NOT_FOUND"))],
            "none was returned",
        ),
        (
            Intent.PROFILE,
            Decision.RETRIEVE_THEN_ANSWER,
            [result("get_user_profile", error("TOOL_ERROR"))],
            "none was returned",
        ),
        (
            Intent.PROFILE,
            Decision.RETRIEVE_THEN_ANSWER,
            [result("get_user_profile", {"output": "Your goal is fat loss"})],
            "none was returned",
        ),
        (
            Intent.PROFILE,
            Decision.RETRIEVE_THEN_ANSWER,
            [result("get_user_profile", {})],
            "none was returned",
        ),
        # general knowledge does not come from data
        (Intent.GENERAL_FITNESS, Decision.RETRIEVE_THEN_ANSWER, [], "not a decision"),
        # safety-sensitive requests are redirected, whatever data there is
        (Intent.SAFETY_SENSITIVE, Decision.ANSWER, [], "not a decision"),
        (
            Intent.SAFETY_SENSITIVE,
            Decision.RETRIEVE_THEN_ANSWER,
            [result("get_user_profile")],
            "not a decision",
        ),
        (Intent.SAFETY_SENSITIVE, Decision.ASK_CLARIFICATION, [], "not a decision"),
        # ambiguous requests are not guessed at
        (Intent.AMBIGUOUS, Decision.ANSWER, [], "not a decision"),
        (Intent.AMBIGUOUS, Decision.CANNOT_ANSWER, [], "not a decision"),
    ],
)
def test_rejected_decisions(intent, decision, results, reason):
    assert reason in check_decision(intent, decision, results)


def test_check_decision_is_deterministic_and_changes_nothing():
    results = [result("get_user_profile", error("PROFILE_NOT_FOUND"))]
    before = deepcopy(results)

    outcomes = {
        check_decision(Intent.PROFILE, Decision.RETRIEVE_THEN_ANSWER, results) for _ in range(5)
    }

    assert len(outcomes) == 1
    assert results == before


# data status


@pytest.mark.parametrize(
    ("value", "status"),
    [
        ({"output": {"goal": "muscle_gain"}}, DataStatus.AVAILABLE),
        ({"output": {"exercises": [], "count": 0}}, DataStatus.AVAILABLE),
        ({"output": {"truncated": False}}, DataStatus.AVAILABLE),
        ({"output": {"truncated": True}}, DataStatus.INCOMPLETE),
        (error("USER_NOT_FOUND"), DataStatus.MISSING),
        (error("PROFILE_NOT_FOUND"), DataStatus.MISSING),
        (error("RESOURCE_NOT_FOUND"), DataStatus.MISSING),
        (error("INVALID_INPUT"), DataStatus.FAILED),
        (error("UNKNOWN_TOOL"), DataStatus.FAILED),
        (error("TOOL_LIMIT_REACHED"), DataStatus.FAILED),
        (error("TOOL_ERROR"), DataStatus.FAILED),
        (error("ID_NOT_GROUNDED"), DataStatus.FAILED),
        ({}, DataStatus.UNEXPECTED),
        ({"output": None}, DataStatus.UNEXPECTED),
        ({"output": "text"}, DataStatus.UNEXPECTED),
        ({"error": "failed"}, DataStatus.UNEXPECTED),
    ],
)
def test_data_status(value, status):
    assert data_status(value) is status


def test_missing_codes_are_the_tools_not_found_codes():
    assert MISSING_ERROR_CODES == {
        ToolErrorCode.USER_NOT_FOUND,
        ToolErrorCode.PROFILE_NOT_FOUND,
        ToolErrorCode.RESOURCE_NOT_FOUND,
    }


def test_tools_used_lists_the_tools_that_returned_data_once_each():
    results = [
        result("get_workout_session"),
        result("get_user_profile", error("PROFILE_NOT_FOUND")),
        result("get_workout_plan"),
        result("get_workout_session"),
    ]

    assert tools_used(results) == ("get_workout_session", "get_workout_plan")


# ids


def test_known_ids_come_from_the_message_and_returned_data_only():
    results = [
        result(
            "get_workout_session",
            {
                "output": {
                    "session_id": 45,
                    "workout_plan_id": 12,
                    "exercises": [{"exercise_id": 3, "sets": [{"set_number": 1, "reps": 10}]}],
                }
            },
        ),
        result("get_workout_plan", {"error": {"code": "RESOURCE_NOT_FOUND", "plan_id": 99}}),
    ]

    known = known_ids("Compare session 45 with last week's 2 sessions", results)

    # numbers the user wrote, and ids in data; not reps, set numbers or error details
    assert known == {45, 2, 12, 3}


@pytest.mark.parametrize(
    ("arguments", "ungrounded"),
    [
        ({"plan_id": 12}, []),
        ({"plan_id": 12.0}, []),
        ({"plan_id": "12"}, []),
        ({"plan_id": 13}, ["plan_id=13"]),
        ({"equipment_id": 3, "movement_pattern": "HORIZONTAL_PUSH"}, ["equipment_id=3"]),
        ({"movement_pattern": "HORIZONTAL_PUSH"}, []),
        # the tools reject a user_id outright, and a non-number fails their validation
        ({"user_id": 42}, []),
        ({"plan_id": "latest"}, []),
        ({"plan_id": True}, []),
    ],
)
def test_ungrounded_ids(arguments, ungrounded):
    call = ToolCall(name="any", arguments=arguments)

    assert ungrounded_ids(call, {12}) == ungrounded


# respond and the decision record


def test_respond_takes_the_intent_the_decision_and_the_reply_and_nothing_else():
    parameters = RESPOND.parameters

    assert set(parameters["properties"]) == {"intent", "decision", "reply"}
    assert parameters["required"] == ["intent", "decision", "reply"]
    assert parameters["properties"]["intent"]["enum"] == [intent.value for intent in Intent]
    assert parameters["properties"]["decision"]["enum"] == [d.value for d in Decision]
    assert RESPOND.name not in {tool.name for tool in TOOL_DECLARATIONS}


@pytest.mark.parametrize(
    "arguments",
    [
        {"intent": "PROFILE", "decision": "ANSWER", "reply": "Hi", "reasoning": "because"},
        {"intent": "MOOD", "decision": "ANSWER", "reply": "Hi"},
        {"intent": "PROFILE", "decision": "GUESS", "reply": "Hi"},
        {"intent": "PROFILE", "decision": "ANSWER", "reply": "   "},
        {"intent": "PROFILE", "decision": "ANSWER", "reply": "x" * (MAX_REPLY_LENGTH + 1)},
        {"intent": "PROFILE", "decision": "ANSWER"},
    ],
    ids=["reasoning", "unknown intent", "unknown decision", "blank", "too long", "no reply"],
)
def test_invalid_respond_arguments(arguments):
    with pytest.raises(ValidationError):
        Respond.model_validate(arguments)


def test_the_decision_record_holds_no_reasoning():
    assert [field.name for field in dataclasses.fields(CoachDecision)] == [
        "intent",
        "decision",
        "tools_used",
        "safety",
    ]


def test_the_instructions_describe_every_intent_and_decision():
    for intent, policy in POLICY.items():
        assert f"- {intent}: {policy.description}" in COACH_INSTRUCTIONS
    for decision in Decision:
        assert f"- {decision}:" in COACH_INSTRUCTIONS
    assert "do not put your reasoning in it" in COACH_INSTRUCTIONS
    assert "never guess one" in COACH_INSTRUCTIONS
