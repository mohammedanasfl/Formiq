"""The tools as the model sees them: names, descriptions and argument schemas.

No tool takes a user_id: Formiq gives every user-scoped tool the user of the
coach request, so the model cannot choose whose data it reads.
"""

from app.ai import ToolDeclaration
from app.schemas.coach import RevisionKind, SessionFocus
from app.schemas.exercise import Difficulty, MovementPattern, WorkoutSection
from app.schemas.workout_plan import WorkoutPlanStatus
from app.tools.limits import (
    MAX_ACTIVITY_REPS,
    MAX_ACTIVITY_SECONDS,
    MAX_ACTIVITY_SETS,
    MAX_PROPOSAL_DAYS_AHEAD,
    MAX_PROPOSED_EXERCISES,
    MAX_PROPOSED_REPS,
    MAX_PROPOSED_REST_SECONDS,
    MAX_PROPOSED_SETS,
    MAX_SEARCH_EQUIPMENT,
    MAX_SEARCH_RESULTS,
    MAX_SECTION_ACTIVITIES,
    MAX_SECTION_MINUTES,
    MAX_UNAVAILABLE_EQUIPMENT,
    MIN_ACTIVITY_SECONDS,
    MIN_COUNTED_SETS,
    MIN_FOCUSED_EXERCISES,
    MIN_FULL_BODY_EXERCISES,
    MIN_SHORT_SESSION_EXERCISES,
    MIN_WARM_UP_MINUTES,
    SHORT_SESSION_MINUTES,
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
        "the prescribed exercises (section, sets, reps or duration, weight, rest). A plan is "
        "what was prescribed, not what the user did: use get_workout_session for that. With "
        "compare_with_plan_id, also what differs between the two plans (changes), worked out "
        "by Formiq: describe only those differences."
    ),
    parameters={
        "type": "object",
        "properties": {
            "plan_id": {**ID, "description": "The workout plan's id."},
            "compare_with_plan_id": {
                **ID,
                "description": "Another of the user's plans to compare it with, such as the "
                "plan it replaced.",
            },
        },
        "required": ["plan_id"],
    },
)

LIST_WORKOUT_PLANS = ToolDeclaration(
    name="list_workout_plans",
    description=(
        "List the user's saved workout plans, in short: each one's id, name, status, "
        "scheduled date, main exercises and whether it is their current plan. PLANNED plans "
        "come first, the next one first. Returns how many there are and how many are PLANNED: "
        "none is an empty list, not an error. Use it when the user asks about their plans, or "
        "to tell which plan they mean when they have several; read one in full with "
        "get_workout_plan. A plan is saved; a proposal awaiting approval is not a plan "
        "(get_pending_proposal)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": [status.value for status in WorkoutPlanStatus],
                "description": "Only the plans in this status.",
            }
        },
    },
)

GET_PENDING_PROPOSAL = ToolDeclaration(
    name="get_pending_proposal",
    description=(
        "Get the workout Formiq proposed to the user earlier that still awaits their approval, "
        "from Formiq's records: not saved, and exactly as it was shown. Returns its name, "
        "date, every exercise with its sets, reps or time and rest, the minutes each section "
        "takes, its coverage, how long it still waits, the saved plan it would replace (if "
        "any) and what differs from that plan, or else from the current plan (changes). Use "
        "it when the user asks about the proposal: what it holds, why an exercise is there, "
        "what changed, or to see it again. When none awaits approval, it says so. Takes no "
        "arguments."
    ),
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

def _activities(section: str, use: WorkoutSection) -> dict:
    """A warm-up or cool-down section: light catalog activities, each for reps
    or for a time."""
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": MAX_SECTION_ACTIVITIES,
        "description": (
            f"The {section}, in order: BEGINNER catalog activities whose uses include {use}. "
            "Each must be CARDIO (movement_pattern), which suits any workout, or list among "
            "its muscles one that a main exercise lists (its suits_main in the search "
            "results lists the main exercises it fits): Formiq rejects any other, such as a "
            "shoulder drill or a back stretch with a legs-only main workout. About 5 minutes "
            f"in all, such as 120 to 180 seconds of easy cardio and a drill or stretch; at "
            f"most {MAX_SECTION_MINUTES}, and a warm-up at least {MIN_WARM_UP_MINUTES} unless "
            f"max_minutes is under {SHORT_SESSION_MINUTES}."
        ),
        "items": {
            "type": "object",
            "properties": {
                "exercise_id": {**ID, "description": "The catalog activity's id."},
                "sets": {"type": "integer", "minimum": 1, "maximum": MAX_ACTIVITY_SETS},
                "reps": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_ACTIVITY_REPS,
                    "description": "Reps of each set; give reps or duration_seconds, not both.",
                },
                "duration_seconds": {
                    "type": "integer",
                    "minimum": MIN_ACTIVITY_SECONDS,
                    "maximum": MAX_ACTIVITY_SECONDS,
                    "description": (
                        "How long each set lasts, such as a 30-second stretch or a "
                        "5-minute walk; give reps or duration_seconds, not both."
                    ),
                },
                "notes": {
                    "type": "string",
                    "description": "Short guidance, such as 'each side' or 'skip if it pinches'.",
                },
            },
            "required": ["exercise_id", "sets"],
        },
    }


PROPOSE_WORKOUT_PLAN = ToolDeclaration(
    name="propose_workout_plan",
    description=(
        "Propose a new workout for the user to review: a warm-up, the main exercises and a "
        "cool-down. It saves nothing: Formiq shows the proposal to the user, and only their "
        "own approval in Formiq saves it. Use it when no planned workout suits the day, "
        "after get_user_profile, get_current_workout_plan and get_latest_workout_session "
        "have returned. Every exercise and activity must be an active Formiq catalog "
        "exercise whose id a tool returned, used for a section its uses include: main "
        "exercises MAIN_WORKOUT, warm-up activities WARM_UP, cool-down activities COOL_DOWN "
        "(search_exercises by use finds them). Choose the main exercises first, then each "
        "warm-up and cool-down activity to match them: one whose suits_main is any or "
        "lists one of the main exercises you chose. Give max_minutes when "
        "the user said how much time they have, and available_equipment (what they have; [] "
        "for none at all) or unavailable_equipment (what they lack or cannot use) when they "
        "said: Formiq rejects a proposal that does not fit them, warm-up and cool-down "
        "included, and judges what the catalog offers the user by them. Formiq also rejects "
        "a main workout that does not fulfil its focus, naming what is missing: give each "
        "main exercise once. Returns the proposal, with each exercise's equipment, an "
        "estimate of each section's duration, and its coverage: when Formiq's catalog has "
        "nothing the user can do for part of the focus, the proposal is made incomplete "
        "(coverage.complete false) and its limitations say what is missing, which you must "
        "tell the user. When the user asks to change, rewrite or replace one of their saved "
        "plans, give revises_plan_id and revision: approving the proposal then saves it and "
        "cancels that plan, and its revision says which main exercises it keeps."
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
            "focus": {
                "type": "string",
                "enum": [focus.value for focus in SessionFocus],
                "description": (
                    "What the main workout trains, by each exercise's primary muscles: "
                    "FULL_BODY (the default) needs the lower body (Quadriceps, Glutes or "
                    "Hamstrings), an upper-body push (Chest, Shoulders or Front Deltoid) and an "
                    "upper-body pull (Upper Back, Lats or Rear Deltoid); UPPER_BODY a push and a "
                    "pull; LOWER_BODY, PUSH, PULL and CORE their own. An arm, calf or grip "
                    "exercise (Triceps, Biceps, Forearms, Calves) belongs to its region but "
                    "never covers it. A core exercise may go with any focus. Only different "
                    f"exercises of at least {MIN_COUNTED_SETS} sets for the focus count: at "
                    f"least {MIN_FULL_BODY_EXERCISES} for FULL_BODY and "
                    f"{MIN_FOCUSED_EXERCISES} for another focus, or "
                    f"{MIN_SHORT_SESSION_EXERCISES} when max_minutes is under "
                    f"{SHORT_SESSION_MINUTES}, which never drops a region the focus needs."
                ),
            },
            "warm_up": _activities("warm-up", WorkoutSection.WARM_UP),
            "exercises": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_PROPOSED_EXERCISES,
                "description": (
                    "The main workout's exercises, in the order to do them: catalog exercises "
                    "whose uses include MAIN_WORKOUT."
                ),
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
            "cool_down": _activities("cool-down", WorkoutSection.COOL_DOWN),
            "max_minutes": {
                "type": "integer",
                "minimum": 10,
                "maximum": 180,
                "description": (
                    "The minutes the user has, when they said: the whole workout, warm-up "
                    "and cool-down included, must fit, and use at least half of them."
                ),
            },
            "available_equipment": {
                "type": "array",
                "maxItems": MAX_SEARCH_EQUIPMENT,
                "items": {"type": "string"},
                "description": (
                    "The equipment the user has, as the catalog names it, when they said: "
                    "every exercise must need nothing else. Give [] for a user with no "
                    "equipment at all, as for search_exercises."
                ),
            },
            "unavailable_equipment": {
                "type": "array",
                "maxItems": MAX_UNAVAILABLE_EQUIPMENT,
                "items": {"type": "string"},
                "description": "Equipment, as the catalog names it, that the user cannot use.",
            },
            "revises_plan_id": {
                **ID,
                "description": (
                    "The id of the user's PLANNED plan this workout revises, as "
                    "get_current_workout_plan or get_workout_plan returned it, when the user "
                    "asked to change, rewrite or replace that plan. Leave it out for a new "
                    "workout. With revision."
                ),
            },
            "revision": {
                "type": "string",
                "enum": [kind.value for kind in RevisionKind],
                "description": (
                    "How it revises that plan: ADJUST for the changes the user asked for "
                    "(shorter, easier, a swapped exercise), keeping the rest; ALTERNATIVE for "
                    "a different workout for the same focus (rewrite it, another version, "
                    "something different). An ALTERNATIVE may keep a main exercise of the plan "
                    "only when the catalog has no other suitable exercise for its part of the "
                    "body: Formiq rejects one that keeps more, naming them. An ADJUST must "
                    "change something. With revises_plan_id."
                ),
            },
        },
        "required": ["name", "warm_up", "exercises", "cool_down"],
    },
)

GET_EXERCISE = ToolDeclaration(
    name="get_exercise",
    description=(
        "Get an exercise from the Formiq exercise catalog by its id: description and "
        "instructions, difficulty, movement pattern, its source's category, the workout "
        "sections Formiq uses it for, the muscles it trains and the equipment it needs."
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
        f"{MAX_SEARCH_RESULTS} exercises, the most relevant first (easy CARDIO first for a "
        "warm-up or cool-down, Formiq's classified exercises first, a mix of muscles), and "
        "how many match. Use it to suggest exercises or alternatives from the catalog: use "
        "finds main exercises (MAIN_WORKOUT) and warm-up (WARM_UP) and cool-down (COOL_DOWN) "
        "activities. Narrow it with muscle and available_equipment, so the few results "
        "returned fit the user; one search per section usually gives enough to choose from. "
        "Once main exercises were found, each warm-up and cool-down activity says which of "
        "them it suits (suits_main: their ids, or any)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "use": {
                "type": "string",
                "enum": [section.value for section in WorkoutSection],
                "description": "A workout section Formiq uses the exercise for.",
            },
            "muscle": {
                "type": "string",
                "description": (
                    "A muscle group the exercise trains, as Formiq names it, such as Chest, "
                    "Upper Back, Lats, Shoulders, Biceps, Triceps, Core, Glutes, Quadriceps, "
                    "Hamstrings or Calves."
                ),
            },
            "available_equipment": {
                "type": "array",
                "maxItems": MAX_SEARCH_EQUIPMENT,
                "items": {"type": "string"},
                "description": (
                    "The equipment the user has, as the catalog names it: only exercises that "
                    "need nothing else are returned. An empty list returns only exercises that "
                    "need no equipment, such as bodyweight exercises: give [] for a user with "
                    "none."
                ),
            },
            "equipment": {
                "type": "string",
                "description": (
                    "One piece of equipment the exercise must use, by the catalog's name or a "
                    "common name for it, such as Kettlebell, Cable Machine or Pull Up Bar. "
                    "Never an id. For exercises that need no equipment, use available_equipment "
                    "with [] instead."
                ),
            },
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
    LIST_WORKOUT_PLANS,
    GET_WORKOUT_SESSION,
    GET_CURRENT_WORKOUT_PLAN,
    GET_LATEST_WORKOUT_SESSION,
    GET_PENDING_PROPOSAL,
    PROPOSE_WORKOUT_PLAN,
    GET_EXERCISE,
    SEARCH_EXERCISES,
)
