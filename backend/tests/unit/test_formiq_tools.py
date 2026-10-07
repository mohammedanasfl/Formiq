"""Unit tests for the coach's tools: dispatch, validation, error handling and
output bounds. The services are mocks; tests/integration/test_formiq_tools.py
reads through the real ones."""

import ast
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.ai import ToolCall
from app.services import (
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.tools import TOOL_DECLARATIONS, FormiqTools, ToolErrorCode
from app.tools.formiq_tools import clip
from app.tools.limits import (
    MAX_EXECUTED_TOOL_CALLS_PER_TURN,
    MAX_EXERCISES,
    MAX_SETS,
    MAX_TEXT_LENGTH,
)
from app.tools.schemas import (
    GetExerciseInput,
    GetUserProfileInput,
    GetWorkoutPlanInput,
    GetWorkoutSessionInput,
    SearchExercisesInput,
    UserScopedInput,
)

TOOLS = Path(__file__).resolve().parents[2] / "app" / "tools"

INPUTS = {
    "get_user_profile": GetUserProfileInput,
    "get_workout_plan": GetWorkoutPlanInput,
    "get_workout_session": GetWorkoutSessionInput,
    "get_exercise": GetExerciseInput,
    "search_exercises": SearchExercisesInput,
}


@pytest.fixture
def services():
    return SimpleNamespace(
        users=Mock(spec=UserService),
        profiles=Mock(spec=UserProfileService),
        plans=Mock(spec=WorkoutPlanService),
        sessions=Mock(spec=WorkoutSessionService),
        catalog=Mock(spec=ExerciseCatalogService),
        end_read=Mock(),
    )


@pytest.fixture
def tools(services):
    return FormiqTools(**vars(services))


def run_one(tools, name, user_id=7, **arguments):
    (result,) = tools.run([ToolCall(name=name, arguments=arguments)], user_id=user_id)
    return result


def error_code(result):
    return result["error"]["code"]


def exercise(exercise_id, name="Push-Up", **fields):
    return SimpleNamespace(
        id=exercise_id,
        name=name,
        description=None,
        difficulty="BEGINNER",
        movement_pattern="HORIZONTAL_PUSH",
        is_active=True,
        muscles=[SimpleNamespace(muscle_group=SimpleNamespace(name="Chest"), role="PRIMARY")],
        equipment=[],
        **fields,
    )


# declarations


def test_there_are_five_read_only_tools():
    assert [tool.name for tool in TOOL_DECLARATIONS] == list(INPUTS)


@pytest.mark.parametrize("declaration", TOOL_DECLARATIONS, ids=lambda tool: tool.name)
def test_declarations_match_the_inputs_without_user_id(declaration):
    model = INPUTS[declaration.name]
    parameters = declaration.parameters or {"properties": {}, "required": []}
    fields = set(model.model_fields) - {"user_id"}

    assert declaration.description
    assert set(parameters["properties"]) == fields
    assert set(parameters.get("required", [])) == {
        name for name in fields if model.model_fields[name].is_required()
    }
    assert "user_id" not in str(parameters)


def test_declared_enums_are_the_catalog_values():
    search = TOOL_DECLARATIONS[-1].parameters["properties"]

    assert search["movement_pattern"]["enum"][:2] == ["HORIZONTAL_PUSH", "HORIZONTAL_PULL"]
    assert search["difficulty"]["enum"] == ["BEGINNER", "INTERMEDIATE", "ADVANCED"]


# inputs


@pytest.mark.parametrize(
    "arguments",
    [{}, {"equipment_id": None, "movement_pattern": None, "difficulty": None}],
    ids=["no filters", "only nulls"],
)
def test_search_needs_a_filter(arguments):
    with pytest.raises(ValidationError, match="at least one of"):
        SearchExercisesInput(**arguments)


@pytest.mark.parametrize(
    ("model", "arguments"),
    [
        (GetUserProfileInput, {"user_id": 0}),
        (GetWorkoutPlanInput, {"user_id": 1, "plan_id": 0}),
        (GetWorkoutPlanInput, {"user_id": 1, "plan_id": 2_147_483_648}),
        (GetWorkoutSessionInput, {"user_id": 1, "session_id": "latest"}),
        (GetExerciseInput, {"exercise_id": -3}),
        (SearchExercisesInput, {"difficulty": "EXPERT"}),
        (SearchExercisesInput, {"movement_pattern": "PUSH"}),
        (GetExerciseInput, {"exercise_id": 3, "name": "Push-Up"}),
    ],
    ids=[
        "user_id 0",
        "plan_id 0",
        "plan_id beyond the column",
        "session_id not a number",
        "negative exercise_id",
        "unknown difficulty",
        "unknown movement pattern",
        "undeclared argument",
    ],
)
def test_invalid_inputs_are_rejected(model, arguments):
    with pytest.raises(ValidationError):
        model(**arguments)


def test_user_scoped_inputs_need_a_user():
    assert issubclass(GetWorkoutPlanInput, UserScopedInput)
    with pytest.raises(ValidationError, match="user_id"):
        GetWorkoutPlanInput(plan_id=3)


# run


def test_user_scoped_tools_read_the_user_given_to_run(tools, services):
    services.plans.get_plan.return_value = None

    run_one(tools, "get_workout_plan", user_id=7, plan_id=12)

    services.plans.get_plan.assert_called_once_with(7, 12)


@pytest.mark.parametrize("name", list(INPUTS))
def test_a_user_id_from_the_model_is_rejected_and_nothing_is_read(tools, services, name):
    (result,) = tools.run([ToolCall(name=name, arguments={"user_id": 5, "plan_id": 1})], user_id=7)

    assert result == {
        "error": {
            "code": "INVALID_INPUT",
            "message": "user_id is not an argument: Formiq always uses the current user",
        }
    }
    for service in (services.users, services.profiles, services.plans, services.sessions):
        assert service.mock_calls == []
    assert services.catalog.mock_calls == []


def test_an_unknown_tool_is_an_error(tools):
    assert run_one(tools, "delete_workout_plan", plan_id=3) == {
        "error": {"code": "UNKNOWN_TOOL", "message": "there is no tool with this name"}
    }


def test_invalid_arguments_are_described_without_their_values(tools, services):
    result = run_one(tools, "get_workout_plan", plan_id="drop table")

    assert error_code(result) == "INVALID_INPUT"
    assert result["error"]["message"].startswith("plan_id: ")
    assert "drop table" not in result["error"]["message"]
    services.plans.get_plan.assert_not_called()


def test_an_invalid_user_from_the_request_is_invalid_input(tools, services):
    assert error_code(run_one(tools, "get_user_profile", user_id=0)) == "INVALID_INPUT"
    services.users.get_user_by_id.assert_not_called()


def test_an_unexpected_failure_is_logged_and_hidden_from_the_model(
    tools, services, caplog, monkeypatch
):
    # Alembic's fileConfig, run in this process by the migration tests, disables
    # the loggers that exist by then.
    monkeypatch.setattr(logging.getLogger("app.tools.formiq_tools"), "disabled", False)
    failure = OperationalError(
        "SELECT * FROM workout_plans", {}, Exception("password=secret host=db.internal")
    )
    services.plans.get_plan.side_effect = failure

    with caplog.at_level(logging.ERROR, logger="app.tools.formiq_tools"):
        result = run_one(tools, "get_workout_plan", plan_id=3)

    assert result == {"error": {"code": "TOOL_ERROR", "message": "the data could not be read"}}
    assert "Coach tool get_workout_plan failed" in caplog.text
    assert "password=secret" in caplog.text  # the cause is in the server log only
    services.end_read.assert_called_once()


def test_the_read_is_ended_after_every_batch(tools, services):
    services.catalog.get_exercise_by_id.return_value = None
    calls = [ToolCall(name="get_exercise", arguments={"exercise_id": n}) for n in (1, 2)]

    tools.run(calls, user_id=7)
    tools.run(calls[:1], user_id=7)

    assert services.end_read.call_count == 2


def test_only_the_first_calls_of_a_turn_run(tools, services):
    services.catalog.get_exercise_by_id.side_effect = lambda exercise_id: exercise(exercise_id)
    calls = [
        ToolCall(name="get_exercise", arguments={"exercise_id": n})
        for n in range(1, MAX_EXECUTED_TOOL_CALLS_PER_TURN + 3)
    ]

    results = tools.run(calls, user_id=7)

    assert len(results) == len(calls)
    executed = results[:MAX_EXECUTED_TOOL_CALLS_PER_TURN]
    assert [result["output"]["exercise_id"] for result in executed] == list(
        range(1, MAX_EXECUTED_TOOL_CALLS_PER_TURN + 1)
    )
    assert {error_code(result) for result in results[MAX_EXECUTED_TOOL_CALLS_PER_TURN:]} == {
        "TOOL_LIMIT_REACHED"
    }
    assert services.catalog.get_exercise_by_id.call_count == MAX_EXECUTED_TOOL_CALLS_PER_TURN


def test_tool_errors_carry_their_code(tools, services):
    services.sessions.get_session.return_value = None

    assert run_one(tools, "get_workout_session", session_id=45) == {
        "error": {"code": "RESOURCE_NOT_FOUND", "message": "the user has no workout session 45"}
    }


def test_error_codes():
    assert {code.value for code in ToolErrorCode} == {
        "USER_NOT_FOUND",
        "PROFILE_NOT_FOUND",
        "RESOURCE_NOT_FOUND",
        "INVALID_INPUT",
        "UNKNOWN_TOOL",
        "TOOL_LIMIT_REACHED",
        "TOOL_ERROR",
    }


# output bounds


def test_long_text_is_cut():
    assert clip(None) is None
    assert clip("x" * MAX_TEXT_LENGTH) == "x" * MAX_TEXT_LENGTH
    cut = clip("x" * (MAX_TEXT_LENGTH + 1))
    assert len(cut) == MAX_TEXT_LENGTH
    assert cut.endswith("…")


def test_a_large_plan_is_truncated(tools, services):
    services.catalog.get_exercise_by_id.side_effect = lambda exercise_id: exercise(exercise_id)
    services.plans.get_plan.return_value = SimpleNamespace(
        id=12,
        name="Everything",
        status="DRAFT",
        scheduled_date=date(2026, 10, 7),
        exercises=[
            SimpleNamespace(
                exercise_id=1,
                exercise_order=order,
                sets=3,
                reps=8,
                weight_kg=None,
                rest_seconds=None,
                notes="n" * 2000,
            )
            for order in range(1, MAX_EXERCISES + 6)
        ],
    )

    output = run_one(tools, "get_workout_plan", plan_id=12)["output"]

    assert len(output["exercises"]) == MAX_EXERCISES
    assert output["truncated"] is True
    assert len(output["exercises"][0]["notes"]) == MAX_TEXT_LENGTH
    # the name of an exercise used many times is looked up once
    services.catalog.get_exercise_by_id.assert_called_once_with(1)


@pytest.mark.parametrize(
    ("exercise_count", "set_count", "truncated"),
    [(2, MAX_SETS, False), (2, MAX_SETS + 1, True), (MAX_EXERCISES + 1, 1, True)],
    ids=["within the limits", "too many sets", "too many exercises"],
)
def test_a_large_session_is_truncated(tools, services, exercise_count, set_count, truncated):
    services.catalog.get_exercise_by_id.side_effect = lambda exercise_id: exercise(exercise_id)
    services.sessions.get_session.return_value = SimpleNamespace(
        id=45,
        workout_plan_id=None,
        status="COMPLETED",
        started_at=datetime(2026, 10, 6, 7, tzinfo=UTC),
        completed_at=datetime(2026, 10, 6, 8, tzinfo=UTC),
        notes=None,
        exercises=[
            SimpleNamespace(
                exercise_id=order,
                exercise_order=order,
                sets=[
                    SimpleNamespace(
                        set_number=number, reps=8, weight_kg=20.0, rpe=7.0, completed=True
                    )
                    for number in range(1, set_count + 1)
                ],
            )
            for order in range(1, exercise_count + 1)
        ],
    )

    output = run_one(tools, "get_workout_session", session_id=45)["output"]

    assert output["truncated"] is truncated
    assert len(output["exercises"]) == min(exercise_count, MAX_EXERCISES)
    assert len(output["exercises"][0]["sets"]) == min(set_count, MAX_SETS)


# architecture


def module_imports(path, *, skip_type_checking):
    """The modules the file imports; with skip_type_checking, not those imported
    only for type hints."""
    tree = ast.parse(path.read_text())
    skipped = set()
    if skip_type_checking:
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
                skipped.update(id(child) for child in ast.walk(node))
    imported = set()
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    return imported


def test_tools_reach_data_only_through_the_services():
    # never the database, the models or the repositories, and the services only
    # as instances given by CoachService
    forbidden = ("sqlalchemy", "app.db", "app.models", "app.repositories", "app.services")
    for path in TOOLS.glob("*.py"):
        runtime = module_imports(path, skip_type_checking=True)
        assert not {name for name in runtime if name.startswith(forbidden)}, path.name
        everything = module_imports(path, skip_type_checking=False)
        assert not {name for name in everything if name.startswith(forbidden[:-1])}, path.name


def test_tools_call_only_read_methods_of_the_services():
    source = (TOOLS / "formiq_tools.py").read_text()
    called = {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr in {"users", "profiles", "plans", "sessions", "catalog"}
    }

    assert called == {
        "get_user_by_id",
        "get_profile_by_user_id",
        "get_plan",
        "get_session",
        "get_exercise_by_id",
        "list_exercises",
    }
