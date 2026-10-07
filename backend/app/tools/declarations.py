"""The tools as the model sees them: names, descriptions and argument schemas.

No tool takes a user_id: Formiq gives every user-scoped tool the user of the
coach request, so the model cannot choose whose data it reads.
"""

from app.ai import ToolDeclaration
from app.schemas.exercise import Difficulty, MovementPattern
from app.tools.limits import MAX_SEARCH_RESULTS

ID = {"type": "integer", "minimum": 1}

GET_USER_PROFILE = ToolDeclaration(
    name="get_user_profile",
    description=(
        "Get the user's Formiq fitness profile: age, height, weight, gender, training "
        "experience, goal, target weight and goal period, training frequency and location, "
        "activity level, sleep and dietary preference. Use it when your answer depends on "
        "who the user is or what they are training for. Takes no arguments."
    ),
)

GET_WORKOUT_PLAN = ToolDeclaration(
    name="get_workout_plan",
    description=(
        "Get one of the user's workout plans by its id: name, status, scheduled date and "
        "the prescribed exercises (sets, reps, weight, rest). A plan is what was prescribed, "
        "not what the user did: use get_workout_session for that."
    ),
    parameters={
        "type": "object",
        "properties": {"plan_id": {**ID, "description": "The workout plan's id."}},
        "required": ["plan_id"],
    },
)

GET_WORKOUT_SESSION = ToolDeclaration(
    name="get_workout_session",
    description=(
        "Get one of the user's workout sessions by its id: what the user actually did. "
        "Returns its status, start and completion times, notes, and each exercise's "
        "performed sets (reps, weight, RPE, whether completed). Use it for questions about "
        "past performance."
    ),
    parameters={
        "type": "object",
        "properties": {"session_id": {**ID, "description": "The workout session's id."}},
        "required": ["session_id"],
    },
)

GET_EXERCISE = ToolDeclaration(
    name="get_exercise",
    description=(
        "Get an exercise from the Formiq exercise catalog by its id: description, "
        "difficulty, movement pattern, the muscles it trains and the equipment it needs."
    ),
    parameters={
        "type": "object",
        "properties": {"exercise_id": {**ID, "description": "The catalog exercise's id."}},
        "required": ["exercise_id"],
    },
)

SEARCH_EXERCISES = ToolDeclaration(
    name="search_exercises",
    description=(
        "Find active exercises in the Formiq exercise catalog that match every filter "
        "given. At least one filter is required. Returns at most "
        f"{MAX_SEARCH_RESULTS} exercises, ordered by name. Use it to suggest exercises or "
        "alternatives from the catalog."
    ),
    parameters={
        "type": "object",
        "properties": {
            "equipment_id": {**ID, "description": "The id of equipment the exercise needs."},
            "movement_pattern": {
                "type": "string",
                "enum": [pattern.value for pattern in MovementPattern],
                "description": "The exercise's movement pattern.",
            },
            "difficulty": {
                "type": "string",
                "enum": [difficulty.value for difficulty in Difficulty],
                "description": "The exercise's difficulty.",
            },
        },
    },
)

TOOL_DECLARATIONS = (
    GET_USER_PROFILE,
    GET_WORKOUT_PLAN,
    GET_WORKOUT_SESSION,
    GET_EXERCISE,
    SEARCH_EXERCISES,
)
