"""The quality and quantity of a proposed workout (Bug 2, 2026-10-27).

A beginner's "abs workout" came back as three exercises, the first three a search returned
(Bird Dog, Band Pallof Press, Alternate Heel Touches). The diagnosis: a request for a workout
was not tied to a proposal; the only quantity rule was a floor of three that the model took;
a search of 45 core matches returned the first 15 by name, eight of them crunches; and three
variations of one crunch counted as three exercises. These tests pin what Formiq now enforces
in code: the real tools run on a small in-memory catalog (the services are mocks, no database
is read), and the model is scripted. They prove what Formiq checks, never how Gemini behaves:
the prompt's wording is only checked to say what it must, and its effect is for a live pass.
"""

from datetime import UTC, date, datetime, timedelta
from itertools import count
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.agent import MAX_TOOL_ITERATIONS, CoachContext, coach_graph
from app.agent.graph import (
    COACH_INSTRUCTIONS,
    PROPOSAL_NOT_MADE_REPLY,
    PROPOSAL_RETRY_ROUNDS,
)
from app.agent.policy import POLICY, Intent
from app.agent.state import initial_state
from app.ai import ToolCall
from app.approvals import ProposalTerms
from app.catalog import free_exercise_db
from app.schemas.coach import SessionFocus
from app.services import (
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.services.coach_service import read_equipment
from app.tools import TOOL_DECLARATIONS, FormiqTools, completeness
from app.tools.equipment import saved_equipment
from app.tools.limits import MAX_SEARCH_RESULTS, MAX_SUGGESTIONS
from tests.coach import call, fake_provider, respond_turn, sent_contents, tool_turn

USER = 7
TODAY = date(2026, 10, 27)
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
MESSAGE = "Give me a beginner abs workout."

MUSCLES = {
    name: number
    for number, name in enumerate(
        ["Core", "Obliques", "Lower Back", "Chest", "Quadriceps", "Glutes", "Upper Back",
         "Shoulders", "Calves", "Biceps", "Hamstrings"],
        start=1,
    )
}  # fmt: skip
EQUIPMENT = {
    name: SimpleNamespace(id=number, name=name, is_active=True)
    for number, name in enumerate(["Resistance Band", "Dumbbell", "Bench", "Cable Machine"], 1)
}
_ids = count(100)


def exercise(
    name, primary, *, secondary=(), difficulty="BEGINNER", pattern="ISOLATION",
    uses=("MAIN_WORKOUT",), equipment=(), source="FREE_EXERCISE_DB", active=True,
):  # fmt: skip
    """A catalog exercise, as the tools read it."""
    muscles = [(name, "PRIMARY") for name in primary] + [(name, "SECONDARY") for name in secondary]
    return SimpleNamespace(
        id=next(_ids), name=name, description=None, instructions=[], difficulty=difficulty,
        movement_pattern=pattern, category=None, uses=list(uses), is_active=active,
        muscles=[
            SimpleNamespace(
                muscle_group=SimpleNamespace(id=MUSCLES[muscle], name=muscle), role=role
            )
            for muscle, role in muscles
        ],
        equipment=[EQUIPMENT[item] for item in equipment], source=source, source_id=None,
    )  # fmt: skip


def core(name, **fields):
    return exercise(name, ["Core"], **fields)


# Twenty-one beginner core exercises: six variations of a crunch, three of a sit-up, and twelve
# that are each their own movement (one of them needing a band): what a core search holds. The
# last names of the alphabet are movements of their own, which a search by name alone cuts.
CRUNCHES = [
    core(name)
    for name in (
        "Crunches", "Crunch - Hands Overhead", "Crunch - Legs On Exercise Ball",
        "Cross-Body Crunch", "Reverse Crunch", "Tuck Crunch",
    )
]  # fmt: skip
SIT_UPS = [core(name) for name in ("Sit-Up", "3/4 Sit-Up", "Jackknife Sit-Up")]
OTHERS = [
    core("Bird Dog", pattern="ROTATION", source="FORMIQ"),
    core("Band Pallof Press", pattern="ROTATION", source="FORMIQ", equipment=["Resistance Band"]),
    core("Dead Bug", pattern="ROTATION"),
    core("Plank"),
    core("Hollow Hold"),
    core("Scissor Kick"),
    core("Lying Leg Raise"),
    core("Russian Twist", pattern="ROTATION"),
    core("Toe Touchers"),
    core("V-Up"),
    core("Windshield Wipers"),
    exercise("Superman", ["Lower Back"], secondary=["Glutes"]),
]
CORE_EXERCISES = CRUNCHES + SIT_UPS + OTHERS

PUSH_UP = exercise("Push-Up", ["Chest"], secondary=["Core"], pattern="HORIZONTAL_PUSH")
SQUAT = exercise("Bodyweight Squat", ["Quadriceps", "Glutes"], pattern="SQUAT")
ROW = exercise(
    "Resistance Band Row", ["Upper Back"], pattern="HORIZONTAL_PULL", equipment=["Resistance Band"]
)
BENCH_LEG_RAISE = core("Flat Bench Lying Leg Raise", equipment=["Bench"])
ADVANCED_CORE = core("Ab Wheel Rollout", difficulty="ADVANCED")
# an exercise of exercises-dataset (UNRATED, uses empty): Formiq does not use it for any section
UNRATED_CORE = core(
    "Weighted Decline Sit-Up", difficulty="UNRATED", uses=(), source="EXERCISES_DATASET"
)
WALK = exercise(
    "Brisk Walk", ["Calves"], pattern="CARDIO", uses=("WARM_UP", "COOL_DOWN")
)
ARM_CIRCLES = exercise("Arm Circles", ["Shoulders"], pattern="MOBILITY", uses=("WARM_UP",))
HARD_WARM_UP = exercise(
    "Mobility Flow", ["Core"], pattern="MOBILITY", uses=("WARM_UP",), difficulty="INTERMEDIATE"
)
COBRA = exercise("Cobra Stretch", ["Core"], pattern="STRETCH", uses=("COOL_DOWN",))

EVERYTHING = [
    *CORE_EXERCISES, PUSH_UP, SQUAT, ROW, BENCH_LEG_RAISE, ADVANCED_CORE, UNRATED_CORE, WALK,
    ARM_CIRCLES, HARD_WARM_UP, COBRA,
]  # fmt: skip


def listing(exercises):
    """ExerciseCatalogService.list_exercises over these exercises, filtered as the
    repository filters them."""

    def list_exercises(filters, available_equipment_ids=None):
        found = []
        for item in sorted(exercises, key=lambda item: item.name):
            if filters.is_active is not None and item.is_active != filters.is_active:
                continue
            if filters.difficulty is not None and item.difficulty != filters.difficulty:
                continue
            pattern = filters.movement_pattern
            if pattern is not None and item.movement_pattern != pattern:
                continue
            if filters.use is not None and filters.use not in item.uses:
                continue
            if filters.muscle_group_id is not None and filters.muscle_group_id not in {
                muscle.muscle_group.id for muscle in item.muscles
            }:
                continue
            if filters.equipment_id is not None and filters.equipment_id not in {
                needed.id for needed in item.equipment
            }:
                continue
            if available_equipment_ids is not None and any(
                needed.id not in available_equipment_ids for needed in item.equipment
            ):
                continue
            found.append(item)
        return found

    return list_exercises


def profile(experience="beginner"):
    return SimpleNamespace(
        first_name="Asha", last_name="Rao", age=30, height_cm=165.0, weight_kg=60.0,
        gender="female", fitness_experience=experience, goal="fat_loss", target_weight_kg=None,
        goal_period_weeks=None, training_frequency_per_week=3, training_location="home",
        activity_level="moderate", sleep_hours=7.0, dietary_preference=None,
        no_equipment=False, equipment=[],
    )  # fmt: skip


def tools_for(exercises=EVERYTHING, *, experience="beginner", saved=None, message=MESSAGE):
    """The real tools over a catalog of these exercises. saved: what the profile says of the
    user's equipment (app.tools.equipment.saved_equipment), None for never said."""
    users, profiles = Mock(spec=UserService), Mock(spec=UserProfileService)
    plans, sessions = Mock(spec=WorkoutPlanService), Mock(spec=WorkoutSessionService)
    catalog = Mock(spec=ExerciseCatalogService)
    users.get_user_by_id.return_value = SimpleNamespace(id=USER)
    profiles.get_profile_by_user_id.return_value = profile(experience)
    plans.get_current_plan.return_value = None
    plans.list_plans.return_value = []
    sessions.get_latest_completed_session.return_value = None
    by_id = {item.id: item for item in exercises}
    catalog.get_exercise_by_id.side_effect = by_id.get
    catalog.list_exercises.side_effect = listing(exercises)
    catalog.list_equipment.return_value = list(EQUIPMENT.values())
    catalog.list_muscle_groups.return_value = [
        SimpleNamespace(id=number, name=name, is_active=True) for name, number in MUSCLES.items()
    ]
    stated, _ = read_equipment([], message, list(EQUIPMENT), saved)
    return FormiqTools(
        users=users, profiles=profiles, plans=plans, sessions=sessions, catalog=catalog,
        end_read=Mock(), today=TODAY, stated=stated, conversation=[("user", message)],
        proposal_terms=ProposalTerms(clock=lambda: NOW, ttl=timedelta(minutes=30)),
    )  # fmt: skip


def run(tools, tool, /, **arguments):
    """One call of a tool (positional, so that a plan's own name argument is not the tool's)."""
    (result,) = tools.run([ToolCall(name=tool, arguments=arguments)], user_id=USER)
    return result


def item(exercise_id, sets=2, reps=12, rest_seconds=60, **fields):
    return {
        "exercise_id": exercise_id, "sets": sets, "reps": reps, "rest_seconds": rest_seconds,
        **fields,
    }  # fmt: skip


def workout(*main, focus="CORE", warm_up=None, cool_down=None, **fields):
    """A workout of these main exercises (items or catalog exercises), between two 3-minute
    walks: easy cardio suits any workout."""
    walk = [{"exercise_id": WALK.id, "sets": 1, "duration_seconds": 180}]
    return {
        "name": "Abs", "focus": focus, "warm_up": warm_up or walk, "cool_down": cool_down or walk,
        "exercises": [
            entry if isinstance(entry, dict) else item(entry.id) for entry in main
        ],
        **fields,
    }  # fmt: skip


def propose(tools, *main, **fields):
    return run(tools, "propose_workout_plan", **workout(*main, **fields))


def problem(result):
    assert result["error"]["code"] == "INVALID_INPUT", result
    return result["error"]["message"]


def by_name(*names):
    found = {entry.name: entry for entry in EVERYTHING}
    return [found[name] for name in names]


# five movements a core search returns (a model may use only the ids a tool gave it)
DIFFERENT_FIVE = by_name("Bird Dog", "Dead Bug", "Plank", "Russian Twist", "Scissor Kick")


# --- 1. a beginner's abs workout is a routine, not a list of suggestions ---


def test_the_three_exercises_the_user_was_given_are_not_a_core_workout():
    tools = tools_for()
    three = by_name("Bird Dog", "Dead Bug", "Plank")

    result = propose(tools, *three)

    message = problem(result)
    assert "has 3 exercises that count for a CORE workout" in message
    assert "fewer than the 4 it needs" in message
    # nothing was proposed, and Formiq suggests what would complete it, which the user can do
    assert tools.proposals == []
    suggested = result["error"]["suggestions"]
    assert 0 < len(suggested) <= MAX_SUGGESTIONS
    assert {entry["name"] for entry in suggested}.isdisjoint({"Bird Dog", "Dead Bug", "Plank"})


@pytest.mark.parametrize("count_of_exercises", [4, 5])
def test_a_varied_core_workout_with_its_prescription_is_proposed(count_of_exercises):
    tools = tools_for()
    main = DIFFERENT_FIVE[:count_of_exercises]

    output = propose(tools, *main)["output"]

    assert output["coverage"]["complete"] is True
    assert output["coverage"]["main_exercises_counted"] == count_of_exercises
    assert output["coverage"]["main_exercises_required"] == 4
    shown = output["exercises"]
    assert [row["section"] for row in shown] == (
        ["WARM_UP"] + ["MAIN_WORKOUT"] * count_of_exercises + ["COOL_DOWN"]
    )
    for row in shown[1:-1]:
        # the proposal carries what the user needs to follow it: sets, reps and rest
        assert (row["sets"], row["reps"], row["rest_seconds"]) == (2, 12, 60)
    assert output["warm_up_minutes"] >= 3
    assert len(tools.proposals) == 1


def test_a_core_search_returns_different_movements_not_the_first_names():
    tools = tools_for()

    output = run(
        tools, "search_exercises", use="MAIN_WORKOUT", muscle="Core", difficulty="BEGINNER",
        available_equipment=[],
    )["output"]  # fmt: skip

    matches = trains_core_without_gear()
    shown = [entry for entry in matches if entry.name in {x["name"] for x in output["exercises"]}]
    movements = {completeness.movement_key(entry) for entry in shown}
    everything = {completeness.movement_key(entry) for entry in matches}
    # 19 matches for which the core is a primary muscle (Superman is not, the Pallof press
    # needs a band) and the Push-Up, whose secondary muscle it is, last: 15 returned, every
    # one of the 12 movements, and then only 3 of the 7 variations
    assert output["total_matches"] == len(matches) + 1 == 20
    assert output["count"] == MAX_SEARCH_RESULTS
    assert movements == everything
    assert len(everything) == 12


def trains_core_without_gear():
    return [
        entry for entry in CORE_EXERCISES
        if not entry.equipment and any(item.muscle_group.name == "Core" for item in entry.muscles)
    ]  # fmt: skip


def test_that_search_used_to_return_the_alphabet():
    """What the ranking replaced: the first 15 by name alone hold fewer movements."""
    matches = sorted(trains_core_without_gear(), key=lambda entry: entry.name)
    by_alphabet = {completeness.movement_key(entry) for entry in matches[:MAX_SEARCH_RESULTS]}

    assert len(by_alphabet) == 9


def real_catalog():
    """free-exercise-db as Formiq classified it: the pinned file, through the real parser."""
    parsed = free_exercise_db.parse_records(free_exercise_db.load_records())
    return [
        SimpleNamespace(
            id=index, name=source.name, difficulty=str(source.difficulty),
            movement_pattern=source.movement_pattern and str(source.movement_pattern),
            uses=[str(use) for use in source.uses], is_active=True, description=None,
            instructions=[], category=source.record.get("category"), source="FREE_EXERCISE_DB",
            source_id=source.source_id,
            muscles=[
                SimpleNamespace(
                    muscle_group=SimpleNamespace(id=MUSCLES.get(muscle, 99), name=muscle),
                    role=str(role),
                )
                for muscle, role in source.muscles.items()
            ],
            equipment=[SimpleNamespace(id=500, name=name) for name in source.equipment],
        )
        for index, source in enumerate(parsed.exercises, start=1)
    ]  # fmt: skip


def test_the_real_catalog_gives_a_beginner_core_search_fifteen_different_movements():
    # the incident: 45 matches, the first 15 by name, five of them crunches
    tools = tools_for(real_catalog())

    output = run(
        tools, "search_exercises", use="MAIN_WORKOUT", muscle="Core", difficulty="BEGINNER",
        available_equipment=[],
    )["output"]  # fmt: skip

    assert output["total_matches"] > 30 and output["count"] == MAX_SEARCH_RESULTS
    catalog = {entry.name: entry for entry in tools.catalog.list_exercises.side_effect(
        SimpleNamespace(is_active=True, difficulty=None, movement_pattern=None, use=None,
                        muscle_group_id=None, equipment_id=None)
    )}  # fmt: skip
    movements = [completeness.movement_key(catalog[entry["name"]]) for entry in output["exercises"]]
    assert len(set(movements)) == MAX_SEARCH_RESULTS
    assert "The most relevant first" not in str(output.get("note", ""))  # a note says it is cut
    assert "not all of them" in output["note"]


# --- 2. the quantity follows the time the user has ---


@pytest.mark.parametrize(
    ("max_minutes", "needed", "sets"),
    [(20, 2, 2), (30, 4, 2), (45, 5, 3), (60, 5, 3)],
)
def test_a_longer_session_holds_more_exercises(max_minutes, needed, sets):
    tools = tools_for()
    everyone = by_name(
        "Bird Dog", "Dead Bug", "Plank", "Reverse Crunch", "Lying Leg Raise", "Superman"
    )

    enough = propose(
        tools, *[item(entry.id, sets=sets) for entry in everyone[:needed]], max_minutes=max_minutes
    )
    too_few = propose(
        tools,
        *[item(entry.id, sets=sets) for entry in everyone[: needed - 1]],
        max_minutes=max_minutes,
    )

    assert enough["output"]["coverage"]["main_exercises_required"] == needed
    assert enough["output"]["coverage"]["complete"] is True
    if needed > 2:
        assert f"fewer than the {needed} it needs" in problem(too_few)
    else:
        # in a short session, one exercise is not enough either
        assert "fewer than the 2 it needs in a short session" in problem(too_few)


def test_the_same_request_asks_for_more_when_the_user_has_more_time():
    needed = {
        minutes: completeness.required_exercises(SessionFocus.CORE, minutes)
        for minutes in (None, 20, 30, 33, 34, 40, 60, 180)
    }

    assert needed == {None: 4, 20: 2, 30: 4, 33: 4, 34: 4, 40: 5, 60: 5, 180: 5}
    full_body = {
        minutes: completeness.required_exercises(SessionFocus.FULL_BODY, minutes)
        for minutes in (None, 20, 33, 34, 39, 40, 180)
    }
    assert full_body == {None: 4, 20: 2, 33: 4, 34: 4, 39: 4, 40: 5, 180: 5}


def test_a_long_session_still_has_to_take_at_least_half_the_time():
    # five exercises of two sets take 24 minutes with the walks: not half of 60
    result = propose(
        tools_for(), *[item(entry.id) for entry in DIFFERENT_FIVE], max_minutes=60
    )

    assert "less than half of the 60 the user has" in problem(result)


def test_the_time_the_user_has_is_still_the_ceiling():
    result = propose(
        tools_for(), *[item(entry.id, sets=6) for entry in DIFFERENT_FIVE], max_minutes=40
    )

    assert "more than the 40 the user has" in problem(result)


# --- 3 and 4. variety and focus relevance; variations cannot inflate completeness ---


def test_three_variations_of_a_crunch_are_one_exercise():
    crunches = by_name("Crunches", "Crunch - Hands Overhead", "Crunch - Legs On Exercise Ball")

    assessment = completeness.assess(SessionFocus.CORE, [(entry, 2) for entry in crunches], None)

    assert (assessment.counted, assessment.required) == (1, 4)
    assert [(a.name, b.name) for a, b in assessment.variations] == [
        ("Crunch - Hands Overhead", "Crunches"),
        ("Crunch - Legs On Exercise Ball", "Crunches"),
    ]


def test_a_workout_of_crunches_is_refused_and_says_they_count_once():
    tools = tools_for()
    main = by_name("Crunches", "Reverse Crunch", "Cross-Body Crunch", "Plank", "Dead Bug")

    result = propose(tools, *main)

    message = problem(result)
    assert "has 3 exercises that count for a CORE workout" in message
    assert "only varies exercise" in message and "so the two count once" in message
    assert "add main exercises that are different movements, not variations of one" in message
    # what it suggests is none of the movements the workout has
    names = {entry["name"] for entry in result["error"]["suggestions"]}
    assert names and not names & {entry.name for entry in CRUNCHES}


def test_a_workout_with_a_variation_among_enough_other_movements_is_proposed():
    # the variation is allowed (more volume of a movement), it only does not count again
    main = by_name("Crunches", "Reverse Crunch", "Plank", "Dead Bug", "Bird Dog")

    output = propose(tools_for(), *main)["output"]

    assert output["coverage"]["main_exercises_counted"] == 4
    assert output["coverage"]["complete"] is True


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        ("Crunches", "Crunch", True),
        ("Crunch - Hands Overhead", "Reverse Crunch", True),
        ("Push-Up", "Pushups", True),
        ("Sit-Up", "3/4 Sit-Up", True),
        ("Squat with Bands", "Squats - With Bands", True),
        ("Dumbbell Biceps Curl", "Dumbbell Bicep Curl", True),
        ("Dumbbell Biceps Curl", "Leg Curl", False),  # a curl for the hamstrings is another
        ("Plank", "Dead Bug", False),
        ("Side Bridge", "Glute Bridge", False),  # a bridge for the core is not one for the glutes
    ],
)
def test_what_counts_as_a_variation_of_one_movement(first, second, same):
    muscles = {"Side Bridge": ["Core"], "Glute Bridge": ["Glutes"], "Push-Up": ["Chest"],
               "Pushups": ["Chest"], "Squat with Bands": ["Glutes"],
               "Squats - With Bands": ["Glutes"],
               "Dumbbell Biceps Curl": ["Biceps"], "Dumbbell Bicep Curl": ["Biceps"],
               "Leg Curl": ["Hamstrings"]}  # fmt: skip

    def named(name):
        return exercise(name, muscles.get(name, ["Core"]))

    keys = completeness.movement_key(named(first)), completeness.movement_key(named(second))
    assert (keys[0] == keys[1]) is same


def test_the_same_name_in_another_order_or_plural_is_still_one_exercise():
    twice = [(core("Barbell Front Squat"), 3), (core("Front Barbell Squats"), 3)]
    pushups = [(exercise("Push-Up", ["Chest"]), 3), (exercise("Pushups", ["Chest"]), 3)]

    assert completeness.assess(SessionFocus.CORE, twice, None).counted == 1
    assert completeness.assess(SessionFocus.PUSH, pushups, None).counted == 1


def test_a_catalog_pool_offers_movements_not_variations():
    # 12 movements of the core and Superman's, for the lower back (a region of the core)
    assert completeness.countable(CORE_EXERCISES, SessionFocus.CORE) == 14
    assert len(CORE_EXERCISES) == 21


def test_an_exercise_that_does_not_train_the_focus_is_refused():
    result = propose(tools_for(), *by_name("Bird Dog", "Dead Bug", "Plank", "Push-Up"))

    assert "trains none of what a CORE workout trains" in problem(result)


def test_a_repeated_exercise_is_refused():
    one = by_name("Bird Dog")[0]

    result = propose(tools_for(), *by_name("Plank", "Dead Bug"), item(one.id), item(one.id))

    assert "is in the main workout twice" in problem(result)


# --- 5. equipment and difficulty stay authoritative ---


def test_a_user_with_no_equipment_is_never_given_a_piece_of_it():
    bodyweight = saved_equipment([], none=True)
    tools = tools_for(saved=bodyweight)
    band = by_name("Band Pallof Press")[0]

    searched = run(tools, "search_exercises", use="MAIN_WORKOUT", muscle="Core")["output"]
    result = propose(tools, band, *by_name("Dead Bug", "Plank", "Bird Dog"))

    assert "Band Pallof Press" not in {entry["name"] for entry in searched["exercises"]}
    assert f"exercise {band.id} needs Resistance Band, which the user cannot use" in problem(result)


def test_the_equipment_the_user_has_decides_what_counts_towards_the_minimum():
    # a user with only a band: the bench exercise is not one the catalog has for them
    tools = tools_for(saved=saved_equipment(["Resistance Band"], none=False))
    bench = by_name("Flat Bench Lying Leg Raise")[0]

    result = propose(tools, bench, *by_name("Plank", "Dead Bug", "Bird Dog"))

    assert f"exercise {bench.id} needs Bench, which the user cannot use" in problem(result)


def test_an_advanced_exercise_is_still_too_hard_for_a_beginner_and_fine_for_others():
    advanced = by_name("Ab Wheel Rollout")[0]
    four = by_name("Plank", "Dead Bug", "Bird Dog")

    refused = propose(tools_for(experience="beginner"), advanced, *four)
    allowed = propose(tools_for(experience="intermediate"), advanced, *four)

    assert f"exercise {advanced.id} (Ab Wheel Rollout) is ADVANCED, too hard for a beginner" in (
        problem(refused)
    )
    assert allowed["output"]["coverage"]["main_exercises_counted"] == 4


def test_the_imported_unrated_exercises_stay_unavailable():
    # Bug 2 does not enable exercises-dataset's records: uses stay empty, the level UNRATED
    unrated = by_name("Weighted Decline Sit-Up")[0]
    tools = tools_for()

    searched = run(tools, "search_exercises", use="MAIN_WORKOUT", muscle="Core")["output"]
    refused = propose(tools, unrated, *by_name("Plank", "Dead Bug", "Bird Dog"))

    assert unrated.name not in {entry["name"] for entry in searched["exercises"]}
    assert f"exercise {unrated.id} (Weighted Decline Sit-Up) is not a main workout" in (
        problem(refused)
    )
    assert "(its uses: none)" in problem(refused)
    # and when a section did use it, a beginner would still not be offered it
    unrated.uses = ["MAIN_WORKOUT"]
    beginner = propose(tools, unrated, *by_name("Plank", "Dead Bug", "Bird Dog"))
    assert "has no difficulty level (UNRATED), so it is not offered to a beginner" in (
        problem(beginner)
    )
    # the pool the minimum is judged by leaves it out too
    assert unrated not in tools._main_pool(set(), True)


# --- 6. warm-up and cool-down keep their own rules ---


def test_a_warm_up_activity_that_is_not_light_is_refused():
    hard = by_name("Mobility Flow")[0]

    result = propose(
        tools_for(), *DIFFERENT_FIVE, warm_up=[{"exercise_id": hard.id, "sets": 1, "reps": 10}]
    )

    assert "is not a light warm-up activity: choose a BEGINNER one" in problem(result)


def test_an_activity_for_muscles_the_workout_does_not_train_is_refused():
    circles = by_name("Arm Circles")[0]

    result = propose(
        tools_for(), *DIFFERENT_FIVE, warm_up=[{"exercise_id": circles.id, "sets": 1, "reps": 10}]
    )

    assert "works none of the muscles the main exercises train" in problem(result)


def test_a_cool_down_activity_must_be_one_the_catalog_uses_for_a_cool_down():
    circles = by_name("Arm Circles")[0]

    result = propose(
        tools_for(), *DIFFERENT_FIVE,
        cool_down=[{"exercise_id": circles.id, "sets": 1, "reps": 10}],
    )  # fmt: skip

    assert "is not a cool-down exercise in Formiq's catalog" in problem(result)


def test_a_stretch_for_the_muscles_trained_is_a_good_cool_down():
    cobra = by_name("Cobra Stretch")[0]

    output = propose(
        tools_for(), *DIFFERENT_FIVE,
        cool_down=[{"exercise_id": cobra.id, "sets": 2, "duration_seconds": 30}],
    )["output"]  # fmt: skip

    rows = output["exercises"]
    cool_down = [row["exercise_name"] for row in rows if row["section"] == "COOL_DOWN"]
    assert cool_down == ["Cobra Stretch"]


# --- 7. a plan that is missing structure, or holds what the catalog does not, is refused ---


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"cool_down": []}, "cool_down"),
        ({"warm_up": []}, "warm_up"),
        ({"exercises": []}, "exercises"),
    ],
)
def test_a_workout_without_a_section_is_refused(change, expected):
    arguments = {**workout(*DIFFERENT_FIVE), **change}

    result = run(tools_for(), "propose_workout_plan", **arguments)

    assert result["error"]["code"] == "INVALID_INPUT" and expected in result["error"]["message"]


def test_an_exercise_with_no_reps_or_sets_is_refused():
    main = [{"exercise_id": entry.id, "sets": 2} for entry in DIFFERENT_FIVE]
    result = run(tools_for(), "propose_workout_plan", **{**workout(), "exercises": main})

    assert result["error"]["code"] == "INVALID_INPUT" and "reps" in result["error"]["message"]


def test_an_exercise_that_is_not_in_the_catalog_is_refused():
    unknown = 2_147_483_000

    result = propose(tools_for(), *DIFFERENT_FIVE[:3], item(unknown))

    assert f"exercise {unknown} is not an active Formiq catalog exercise" in problem(result)


def test_a_retired_exercise_is_refused():
    plank = by_name("Plank")[0]
    plank.is_active = False
    try:
        result = propose(tools_for(), *by_name("Dead Bug", "Bird Dog", "Superman"), plank)
    finally:
        plank.is_active = True

    assert f"exercise {plank.id} is not an active Formiq catalog exercise" in problem(result)


def test_more_than_ten_main_exercises_are_refused():
    result = run(
        tools_for(), "propose_workout_plan",
        **{**workout(), "exercises": [item(entry.id) for entry in CORE_EXERCISES[:11]]},
    )  # fmt: skip

    assert result["error"]["code"] == "INVALID_INPUT"


# --- 8. a catalog that has too few says so, and nothing is made up ---


def test_a_catalog_with_too_few_exercises_gives_an_incomplete_workout_that_says_so():
    # the user has only a band: one core exercise they can do
    only = [*by_name("Bird Dog", "Dead Bug"), WALK, PUSH_UP]
    tools = tools_for(only)

    output = propose(tools, *by_name("Bird Dog", "Dead Bug"))["output"]

    coverage = output["coverage"]
    assert coverage["complete"] is False
    assert (coverage["main_exercises_counted"], coverage["main_exercises_required"]) == (2, 4)
    assert [limit["code"] for limit in coverage["limitations"]] == ["TOO_FEW_SUITABLE_EXERCISES"]
    assert "only 2 different exercises" in coverage["limitations"][0]["message"]
    # nothing was added that the catalog does not have
    catalog_ids = {entry.id for entry in only}
    assert {row["exercise_id"] for row in output["exercises"]} <= catalog_ids


def test_a_catalog_with_no_exercise_for_the_focus_refuses_rather_than_makes_one_up():
    nothing_for_core = [PUSH_UP, SQUAT, ROW, WALK]
    tools = tools_for(nothing_for_core)

    result = propose(tools, PUSH_UP, SQUAT, ROW)

    assert "trains none of what a CORE workout trains" in problem(result)
    assert tools.proposals == []


def test_exercises_the_user_cannot_do_do_not_count_as_available():
    # a core catalog that is all band or bench exercises, for a user with no equipment
    gear = [band for band in CORE_EXERCISES if band.equipment] + [BENCH_LEG_RAISE, WALK]
    tools = tools_for(gear, saved=saved_equipment([], none=True))

    result = propose(tools, *by_name("Dead Bug"))

    assert "needs none" not in str(result)
    assert result["error"]["code"] == "INVALID_INPUT"


# --- 9. a refused workout is never turned into a finished one ---


READS = ("get_user_profile", "get_current_workout_plan", "get_latest_workout_session")


def scripted_turn(*after):
    """The turn for MESSAGE: the reads and searches a workout rests on, in the first round,
    then after."""
    return (
        tool_turn(
            *(call(name) for name in READS),
            call("search_exercises", use="MAIN_WORKOUT", muscle="Core", difficulty="BEGINNER"),
            call("search_exercises", use="WARM_UP"),
            call("search_exercises", use="COOL_DOWN"),
        ),
        *after,
    )


_proposals = count(1)


def proposing(*main, **fields):
    return ToolCall(
        name="propose_workout_plan",
        arguments=workout(*main, **fields),
        id=f"proposal-{next(_proposals)}",
    )


def play(tools, *turns):
    provider = fake_provider(*turns)
    state = coach_graph.invoke(
        initial_state(MESSAGE), context=CoachContext(user_id=USER, provider=provider, tools=tools)
    )
    return state, provider


def results_of(provider, name):
    """The results the model was sent for its calls of this tool, in order: from its last
    request, which holds the whole turn."""
    return [
        part.function_response.response
        for content in sent_contents(provider, provider.generate_turn.call_count - 1)
        for part in content.parts or []
        if part.function_response is not None and part.function_response.name == name
    ]


def test_a_three_exercise_proposal_is_refused_and_a_corrected_one_is_accepted():
    tools = tools_for()
    three, five = by_name("Bird Dog", "Dead Bug", "Plank"), DIFFERENT_FIVE
    state, provider = play(
        tools,
        *scripted_turn(
            tool_turn(proposing(*three)),
            tool_turn(proposing(*five)),
            respond_turn("Here is a core workout to review and approve in Formiq.",
                         "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        ),
    )  # fmt: skip

    refused, accepted = results_of(provider, "propose_workout_plan")
    assert refused["error"]["code"] == "INVALID_INPUT"
    assert "fewer than the 4 it needs" in refused["error"]["message"]
    assert accepted["output"]["coverage"]["complete"] is True
    assert len(tools.proposals) == 1
    (_, shown) = tools.proposals[0]
    assert sum(row.section == "MAIN_WORKOUT" for row in shown.exercises) == 5
    assert state["final_response"].startswith("Here is a core workout")


def test_a_model_that_keeps_proposing_three_gets_nothing_proposed_within_its_rounds():
    tools = tools_for()
    attempts = [
        by_name("Bird Dog", "Dead Bug", "Plank"),
        by_name("Bird Dog", "Dead Bug", "Hollow Hold"),
        by_name("Bird Dog", "Dead Bug", "Scissor Kick"),
        by_name("Bird Dog", "Plank", "Hollow Hold"),
        by_name("Dead Bug", "Plank", "Hollow Hold"),
    ]
    # the reads and searches take the first round; four more rounds propose, and the round
    # past the limit that corrects a refused proposal proposes once more
    state, provider = play(
        tools,
        *scripted_turn(
            *(tool_turn(proposing(*attempt)) for attempt in attempts),
            respond_turn("Here is your abs workout to review and approve in Formiq.",
                         "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        ),
    )  # fmt: skip

    # no workout was made: the reply that says one was is Formiq's own, and the turn is bounded
    assert tools.proposals == []
    assert state["final_response"] == PROPOSAL_NOT_MADE_REPLY
    assert provider.generate_turn.call_count <= MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 1
    assert all(
        "error" in result for result in results_of(provider, "propose_workout_plan")
    )


def test_an_incomplete_workout_is_never_reported_complete():
    only = [*by_name("Bird Dog", "Dead Bug"), WALK]
    tools = tools_for(only)

    output = propose(tools, *by_name("Bird Dog", "Dead Bug"))["output"]

    # the card says it, whatever the reply says (the reply is checked against it)
    assert output["coverage"]["complete"] is False
    assert output["coverage"]["limitations"]
    (stored, shown) = tools.proposals[0]
    assert shown.coverage.complete is False and dict(stored.parameters)["focus"] == "CORE"


def test_a_tool_that_fails_proposes_nothing():
    tools = tools_for()
    tools.catalog.get_exercise_by_id.side_effect = RuntimeError("the database is gone")

    result = propose(tools, *DIFFERENT_FIVE)

    assert result["error"]["code"] == "TOOL_ERROR"
    assert tools.proposals == []


# --- 10. what the model is told, and what did not change ---


def test_a_request_for_a_workout_is_a_request_for_a_proposal():
    text = " ".join(COACH_INSTRUCTIONS.split())
    declaration = {tool.name: tool for tool in TOOL_DECLARATIONS}["propose_workout_plan"]

    assert "A request for a workout is the request to propose one" in text
    assert "Never answer it with a list of exercises, and never ask whether" in text
    assert "whenever the user asks you for a workout, routine or session" in declaration.description
    assert "WORKOUT_PLAN" in text and "abs or core is CORE" in text
    # the intents say where a requested workout belongs
    assert "a workout they ask you to make" in POLICY[Intent.WORKOUT_PLAN].description
    assert "not a request for a workout" in POLICY[Intent.EXERCISE].description


def test_the_instructions_ask_for_more_than_the_floor_and_a_prescription():
    text = " ".join(COACH_INSTRUCTIONS.split())

    assert "are floors, not targets" in text
    assert "More time means more different exercises, not many sets of a few" in text
    assert "sets, reps and rest_seconds" in text
    # the daily workout guidance is as it was
    assert "A plan for today (days_from_today 0) that suits the user: recommend it" in text
    assert "Every proposal has a warm-up, the main exercises and a cool-down" in text


def test_the_daily_workout_still_needs_only_what_it_always_did():
    # a full-body workout with no time given: four exercises, as before
    tools = tools_for()
    full_body = [SQUAT, PUSH_UP, ROW, *by_name("Bird Dog")]
    walk = {"exercise_id": WALK.id, "sets": 1, "duration_seconds": 180}

    output = run(
        tools, "propose_workout_plan", name="Today", warm_up=[walk], cool_down=[walk],
        exercises=[item(entry.id, sets=3) for entry in full_body], focus="FULL_BODY",
    )["output"]  # fmt: skip

    assert output["coverage"]["complete"] is True
    assert output["coverage"]["main_exercises_required"] == 4
