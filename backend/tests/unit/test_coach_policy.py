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
    check_proposal,
    data_status,
    is_canonical_id,
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
        "DAILY_WORKOUT",
        "SAFETY_SENSITIVE",
        "AMBIGUOUS",
        "OUT_OF_SCOPE",
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
    # by id, or the current plan / last workout without one; the list of plans,
    # the proposal awaiting approval, and the one the turn made (live QA
    # 2026-10-16, B2: a first workout for a user with no plan has no other
    # evidence, since a proposal is kept only once the turn ends)
    assert POLICY[Intent.WORKOUT_PLAN].data_tools == {
        "get_workout_plan",
        "get_current_workout_plan",
        "list_workout_plans",
        "get_pending_proposal",
        "propose_workout_plan",
    }
    assert POLICY[Intent.WORKOUT_HISTORY].data_tools == {
        "get_workout_session",
        "get_latest_workout_session",
    }
    assert POLICY[Intent.EXERCISE].data_tools == {"get_exercise", "search_exercises"}
    assert POLICY[Intent.ADAPTATION].data_tools == {
        "get_user_profile",
        "get_workout_plan",
        "list_workout_plans",
        "get_workout_session",
        "get_current_workout_plan",
        "get_latest_workout_session",
        "get_pending_proposal",
    }
    assert POLICY[Intent.DAILY_WORKOUT].data_tools == POLICY[Intent.ADAPTATION].data_tools
    # a decision answered from data needs a tool to get it from
    for policy in POLICY.values():
        if Decision.RETRIEVE_THEN_ANSWER in policy.decisions:
            assert policy.data_tools
        assert policy.checked_tools <= policy.data_tools


def test_only_the_plan_intent_counts_a_proposal_as_evidence():
    """The proposal the turn made is evidence for talking about the user's
    workout plans and for nothing else: a session history or a catalog question
    is not answered from it."""
    counting = {
        intent
        for intent, policy in POLICY.items()
        if "propose_workout_plan" in policy.data_tools
    }
    assert counting == {Intent.WORKOUT_PLAN}
    assert POLICY[Intent.WORKOUT_HISTORY].data_tools == {
        "get_workout_session",
        "get_latest_workout_session",
    }
    assert POLICY[Intent.EXERCISE].data_tools == {"get_exercise", "search_exercises"}


# a proposal Formiq accepted has an output; one it refused has an error
ACCEPTED = {"output": {"status": "awaiting_user_approval", "estimated_minutes": 26}}
REFUSED = {"error": {"code": "INVALID_INPUT", "message": "the main workout trains no core"}}
NO_PLAN = error("RESOURCE_NOT_FOUND")


def test_a_first_workout_for_a_user_with_no_plan_is_evidence_for_the_plan_intent():
    results = [
        result("get_user_profile"),
        result("get_current_workout_plan", NO_PLAN),
        result("get_latest_workout_session", NO_PLAN),
        result("propose_workout_plan", ACCEPTED),
    ]

    assert check_decision(Intent.WORKOUT_PLAN, Decision.RETRIEVE_THEN_ANSWER, results) is None


@pytest.mark.parametrize(
    "refused",
    [
        REFUSED,
        error("PROPOSAL_REFUSED"),
        error("PROPOSAL_LIMIT"),
        error("CONTEXT_MISSING"),
        error("ID_NOT_GROUNDED"),
        {"output": "the proposal is ready"},  # not data: an output is an object
    ],
)
def test_a_refused_proposal_is_no_evidence(refused):
    results = [
        result("get_user_profile"),
        result("get_current_workout_plan", NO_PLAN),
        result("propose_workout_plan", refused),
    ]

    rejection = check_decision(Intent.WORKOUT_PLAN, Decision.RETRIEVE_THEN_ANSWER, results)

    assert rejection is not None and "none was returned" in rejection


def test_an_accepted_proposal_does_not_loosen_the_other_intents_that_need_data():
    results = [result("propose_workout_plan", ACCEPTED)]

    for intent in (Intent.WORKOUT_HISTORY, Intent.EXERCISE, Intent.PROFILE):
        rejection = check_decision(intent, Decision.RETRIEVE_THEN_ANSWER, results)
        assert rejection is not None and "none was returned" in rejection


def test_the_plan_intent_still_needs_evidence_when_nothing_was_proposed_or_read():
    results = [result("get_current_workout_plan", NO_PLAN), result("get_pending_proposal", NO_PLAN)]

    rejection = check_decision(Intent.WORKOUT_PLAN, Decision.RETRIEVE_THEN_ANSWER, results)

    assert rejection is not None and "propose_workout_plan" in rejection


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


# the daily recommendation

DAILY_CHECKS = ("get_user_profile", "get_current_workout_plan", "get_latest_workout_session")


def daily(*statuses):
    """The three checks' results, in DAILY_CHECKS order."""
    return [result(name, value) for name, value in zip(DAILY_CHECKS, statuses, strict=True)]


def test_only_the_daily_recommendation_requires_its_reads_checked():
    checked = {intent: policy.checked_tools for intent, policy in POLICY.items()}

    assert {intent: tools for intent, tools in checked.items() if tools} == {
        Intent.DAILY_WORKOUT: set(DAILY_CHECKS)
    }


@pytest.mark.parametrize(
    "results",
    [
        daily(DATA, DATA, DATA),
        # no plan and no workout yet, confirmed: answered honestly from the profile
        daily(DATA, error("RESOURCE_NOT_FOUND"), error("RESOURCE_NOT_FOUND")),
        # no profile, but a plan
        daily(error("PROFILE_NOT_FOUND"), DATA, error("RESOURCE_NOT_FOUND")),
    ],
    ids=["all_data", "no_plan_no_history", "no_profile"],
)
def test_a_daily_recommendation_is_accepted_once_its_reads_are_checked(results):
    assert check_decision(Intent.DAILY_WORKOUT, Decision.RETRIEVE_THEN_ANSWER, results) is None


@pytest.mark.parametrize(
    ("results", "reason"),
    [
        # recommending from the profile alone, without looking at the plan or history
        ([result("get_user_profile")], "get_current_workout_plan, get_latest_workout_session"),
        (daily(DATA, DATA, DATA)[:2], "get_latest_workout_session checked"),
        # a failed read is not a check: nothing is assumed about what it would hold
        (daily(DATA, error("TOOL_ERROR"), DATA), "get_current_workout_plan checked"),
        (daily(DATA, DATA, error("TOOL_LIMIT_REACHED")), "get_latest_workout_session checked"),
        # every read checked, nothing found: not an answer from data
        (
            daily(
                error("PROFILE_NOT_FOUND"),
                error("RESOURCE_NOT_FOUND"),
                error("RESOURCE_NOT_FOUND"),
            ),
            "none was returned",
        ),
    ],
    ids=["profile_only", "history_not_read", "plan_failed", "history_refused", "nothing_found"],
)
def test_a_daily_recommendation_is_rejected_until_its_reads_are_checked(results, reason):
    assert reason in check_decision(Intent.DAILY_WORKOUT, Decision.RETRIEVE_THEN_ANSWER, results)


def test_the_daily_checks_do_not_hold_back_a_question_or_cannot_answer():
    for decision in (Decision.ASK_CLARIFICATION, Decision.CANNOT_ANSWER):
        assert check_decision(Intent.DAILY_WORKOUT, decision, []) is None
    assert "not a decision" in check_decision(Intent.DAILY_WORKOUT, Decision.ANSWER, [])


# a proposed plan


def test_a_plan_is_proposed_only_after_the_daily_reads_and_with_a_profile():
    missing = error("RESOURCE_NOT_FOUND")

    assert "check get_current_workout_plan, get_latest_workout_session" in check_proposal(
        [result("get_user_profile")]
    )
    # a failed read is not a check
    assert "check get_latest_workout_session" in check_proposal(
        daily(DATA, DATA, error("TOOL_ERROR"))
    )
    assert "no fitness profile" in check_proposal(
        daily(error("PROFILE_NOT_FOUND"), missing, missing)
    )
    # no plan and no workout yet: a plan is proposed from the profile
    assert check_proposal(daily(DATA, missing, missing)) is None
    assert check_proposal(daily(DATA, DATA, DATA)) is None


def test_the_exercise_ids_of_a_proposed_plan_must_be_grounded():
    proposal = ToolCall(
        name="propose_workout_plan",
        arguments={
            "name": "Upper Body",
            "exercises": [
                {"exercise_id": 3, "sets": 3, "reps": 8},
                {"exercise_id": 9, "sets": 3, "reps": 8},
                {"exercise_id": "3", "sets": 3, "reps": 8},
            ],
        },
    )

    assert ungrounded_ids(proposal, {3}) == ["exercise_id=9", "exercise_id='3'"]
    assert ungrounded_ids(proposal, {3, 9}) == ["exercise_id='3'"]


def test_the_warm_up_and_cool_down_ids_of_a_proposed_plan_must_be_grounded():
    proposal = ToolCall(
        name="propose_workout_plan",
        arguments={
            "name": "Upper Body",
            "warm_up": [{"exercise_id": 40, "sets": 1, "duration_seconds": 120}],
            "exercises": [{"exercise_id": 3, "sets": 3, "reps": 8}],
            "cool_down": [{"exercise_id": 41, "sets": 1, "duration_seconds": 30}],
        },
    )

    assert ungrounded_ids(proposal, {3}) == ["exercise_id=40", "exercise_id=41"]
    assert ungrounded_ids(proposal, {3, 40, 41}) == []


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
        ({"plan_id": 13}, ["plan_id=13"]),
        ({"equipment_id": 3, "movement_pattern": "HORIZONTAL_PUSH"}, ["equipment_id=3"]),
        ({"movement_pattern": "HORIZONTAL_PUSH"}, []),
        # an id left out is not one
        ({"equipment_id": None, "difficulty": "BEGINNER"}, []),
        # the tools reject a user_id outright
        ({"user_id": 42}, []),
        # only the canonical form of a known id is grounded: no other form of 12
        ({"plan_id": 12.0}, ["plan_id=12.0"]),
        ({"plan_id": "12"}, ["plan_id='12'"]),
        ({"plan_id": "latest"}, ["plan_id='latest'"]),
        ({"plan_id": True}, ["plan_id=True"]),
    ],
)
def test_ungrounded_ids(arguments, ungrounded):
    call = ToolCall(name="any", arguments=arguments)

    assert ungrounded_ids(call, {12}) == ungrounded


@pytest.mark.parametrize("value", [7, 42, 1_000_127])
def test_a_canonical_id_is_a_positive_json_integer(value):
    assert is_canonical_id(value)


@pytest.mark.parametrize(
    "value",
    [True, False, 0, -7, 7.0, "7", "+7", "-7", "7.0", "01", "07", "1_0", " 7 ", "7 ", " 7", "7e0",
     "1e1", None, [7], {"id": 7}],
)
def test_no_other_form_is_a_canonical_id(value):
    assert not is_canonical_id(value)


def test_a_tool_result_grounds_only_canonical_ids():
    results = [result("search_exercises", {"output": {"exercise_id": 7, "equipment_id": True, "plan_id": "9"}})]

    # true would otherwise ground 1
    assert known_ids("Find an exercise.", results) == {7}


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
