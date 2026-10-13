"""The tools as the model sees them: names, descriptions and argument schemas.

No tool takes a user_id: Formiq gives every user-scoped tool the user of the
coach request, so the model cannot choose whose data it reads.
"""

from app.ai import ToolDeclaration
from app.schemas.exercise import Difficulty, MovementPattern
from app.tools.limits import (
    MAX_PROPOSAL_DAYS_AHEAD,
    MAX_PROPOSED_EXERCISES,
    MAX_PROPOSED_REPS,
    MAX_PROPOSED_REST_SECONDS,
    MAX_PROPOSED_SETS,
    MAX_SEARCH_RESULTS,
)

ID = {"type": "integer", "minimum": 1}

GET_USER_PROFILE = ToolDeclaration(
    name="get_user_profile",
    description=(
        "Get the user's Formiq fitness profile: first and last name, age, height, weight, "
        "gender, training experience, goal, target weight and goal period, training frequency "
        "and location, activity level, sleep and dietary preference. Never their email or "
        "phone number, which Formiq does not give you. Use it when your answer depends on "
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

GET_CURRENT_WORKOUT_PLAN = ToolDeclaration(
    name="get_current_workout_plan",
    description=(
        "Get the user's current workout plan, without an id: their PLANNED plan scheduled "
        "for today, or else the next one scheduled after today, or else the one scheduled "
        "most recently before today. Returns the same as get_workout_plan, plus today's "
        "date and days_from_today (0 today, 1 tomorrow, -1 yesterday). Use it when the "
        "user asks about their current, active, planned or next workout, or what to do "
        "today. When the user names a plan id, use get_workout_plan instead. Takes no "
        "arguments."
    ),
)

GET_LATEST_WORKOUT_SESSION = ToolDeclaration(
    name="get_latest_workout_session",
    description=(
        "Get the user's last workout, without an id: their most recently started "
        "COMPLETED workout session. Returns the same as get_workout_session, plus today's "
        "date and days_ago (0 today, 1 yesterday). Use it when the user asks about their "
        "last, latest or most recent workout, what they did recently, or what to do "
        "today. When the user names a session id, use get_workout_session instead. "
        "Takes no arguments."
    ),
)

PROPOSE_WORKOUT_PLAN = ToolDeclaration(
    name="propose_workout_plan",
    description=(
        "Propose a new workout plan for the user to review. It saves nothing: Formiq "
        "shows the proposal to the user, and only their own approval in Formiq saves it. "
        "Use it when no planned workout suits the day, after get_user_profile, "
        "get_current_workout_plan and get_latest_workout_session have returned. Each "
        "exercise must be an active Formiq catalog exercise whose id a tool returned. "
        "Give max_minutes when the user said how much time they have, and "
        "unavailable_equipment for equipment they do not have or cannot use: Formiq "
        "rejects a proposal that does not fit them. Returns the proposal, with each "
        "exercise's equipment and an estimate of its duration."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "A short name for the workout, such as 'Upper Body, No Dumbbells'.",
            },
            "scheduled_date": {
                "type": "string",
                "description": (
                    "The day it is for, as YYYY-MM-DD: today (the default) or up to "
                    f"{MAX_PROPOSAL_DAYS_AHEAD} days later."
                ),
            },
            "exercises": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_PROPOSED_EXERCISES,
                "description": "The exercises, in the order to do them.",
                "items": {
                    "type": "object",
                    "properties": {
                        "exercise_id": {**ID, "description": "The catalog exercise's id."},
                        "sets": {"type": "integer", "minimum": 1, "maximum": MAX_PROPOSED_SETS},
                        "reps": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_PROPOSED_REPS,
                            "description": "The target reps of each set.",
                        },
                        "rest_seconds": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": MAX_PROPOSED_REST_SECONDS,
                        },
                        "notes": {
                            "type": "string",
                            "description": "Short guidance, such as a rep range; never a weight.",
                        },
                    },
                    "required": ["exercise_id", "sets", "reps"],
                },
            },
            "max_minutes": {
                "type": "integer",
                "minimum": 10,
                "maximum": 180,
                "description": "The minutes the user has, when they said.",
            },
            "unavailable_equipment": {
                "type": "array",
                "maxItems": 10,
                "items": {"type": "string"},
                "description": "Equipment, as the catalog names it, that the user cannot use.",
            },
        },
        "required": ["name", "exercises"],
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
    GET_CURRENT_WORKOUT_PLAN,
    GET_LATEST_WORKOUT_SESSION,
    PROPOSE_WORKOUT_PLAN,
    GET_EXERCISE,
    SEARCH_EXERCISES,
)
