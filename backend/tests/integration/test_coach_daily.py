"""The daily coach, end to end: "What should I do today?" through CoachService
and the API, with the real tools on the test database and a scripted model.

The model is scripted, so these tests check what Formiq guarantees whatever the
model writes: a recommendation rests on the user's own profile, current plan
and last workout, read in this turn and placed relative to today; what is
missing is reported as missing, never as data; and safety and identity hold.
How well a real model recommends from that data is not checked here.

They require the local PostgreSQL container to be running. The services commit,
so the user tables are emptied before and after each test.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy.orm import Session

from app.agent import COACH_INSTRUCTIONS, SAFETY_POLICY, CoachDates, SafetyCategory
from app.agent.graph import date_note
from app.api.dependencies import get_ai_provider
from app.main import app
from app.models import (
    WorkoutPlan,
    WorkoutPlanExercise,
    WorkoutSession,
    WorkoutSessionExercise,
    WorkoutSet,
)
from app.observability import Tracer
from app.observability.memory import MemoryBackend
from app.schemas import UserCreate, UserProfileCreate
from app.services import CoachService, UserProfileService, UserService
from app.tools import FormiqTools, formiq_tools
from tests.auth import bearer
from tests.coach import (
    call,
    fake_provider,
    respond_turn,
    sent_contents,
    tool_responses,
    tool_turn,
)

TODAY = date(2026, 10, 13)
MESSAGE = "What should I do today?"
# what a daily recommendation must have checked in its turn
DAILY_READS = ("get_user_profile", "get_current_workout_plan", "get_latest_workout_session")


@pytest.fixture(autouse=True)
def today(monkeypatch):
    """Formiq's date, fixed for these tests."""
    monkeypatch.setattr(formiq_tools, "utc_today", lambda: TODAY)


@pytest.fixture
def exercises(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Bench Press"], catalog_exercise_ids["Barbell Back Squat"]


def create_user(session: Session, email: str, profile: dict | None = None) -> int:
    user = UserService(session).create_user(UserCreate(email=email))
    if profile is not None:
        UserProfileService(session).create_profile(user.id, UserProfileCreate(**profile))
    return user.id


@pytest.fixture
def user_id(service_session, profile_fields):
    return create_user(service_session, "daily@example.com", profile_fields)


def add_plan(session, user_id, day, *exercises, name="Upper Body A", status="PLANNED"):
    """A plan scheduled `day` days from TODAY, committed. exercises are
    (exercise_id, sets, reps, weight_kg) tuples."""
    plan = WorkoutPlan(
        user_id=user_id,
        name=name,
        status=status,
        scheduled_date=TODAY + timedelta(days=day),
        exercises=[
            WorkoutPlanExercise(
                exercise_id=exercise_id,
                exercise_order=order,
                sets=sets,
                reps=reps,
                weight_kg=weight,
                rest_seconds=90,
            )
            for order, (exercise_id, sets, reps, weight) in enumerate(exercises, start=1)
        ],
    )
    session.add(plan)
    session.commit()
    return plan


def add_workout(session, user_id, day, exercise_id, sets, status="COMPLETED"):
    """A workout of one exercise, started `day` days from TODAY, committed.
    sets are (reps, weight_kg, rpe, completed) tuples."""
    started = datetime.combine(TODAY + timedelta(days=day), time(18), tzinfo=UTC)
    workout = WorkoutSession(
        user_id=user_id,
        status=status,
        started_at=started,
        completed_at=started + timedelta(hours=1) if status == "COMPLETED" else None,
        exercises=[
            WorkoutSessionExercise(
                exercise_id=exercise_id,
                exercise_order=1,
                sets=[
                    WorkoutSet(
                        set_number=number, reps=reps, weight_kg=weight, rpe=rpe, completed=done
                    )
                    for number, (reps, weight, rpe, done) in enumerate(sets, start=1)
                ],
            )
        ],
    )
    session.add(workout)
    session.commit()
    return workout


def daily_reads(*extra):
    """The model's turn reading what a daily recommendation needs, together."""
    return tool_turn(*(call(name) for name in DAILY_READS), *extra)


def recommend(reply):
    return respond_turn(reply, "DAILY_WORKOUT", "RETRIEVE_THEN_ANSWER")


def ask(session, user_id, *turns, message=MESSAGE):
    """The coach's reply, the request's traced outcome, and the scripted model."""
    provider = fake_provider(*turns)
    backend = MemoryBackend()
    reply = CoachService(session, provider, Tracer(backend)).reply(user_id, message)
    return reply, backend.root.metadata, provider


def received(provider, request=1):
    """The tool results sent to the model in its request-th request, by tool."""
    return {
        response.name: response.response
        for response in tool_responses(sent_contents(provider, request)[-1])
    }


# --- what the recommendation rests on ---


def test_a_plan_for_today_is_recommended_from_the_plan_itself(service_session, user_id, exercises):
    bench, squat = exercises
    plan = add_plan(service_session, user_id, 0, (bench, 3, 8, 60.0), (squat, 4, 6, None))
    add_plan(service_session, user_id, 2, (squat, 5, 5, 80.0), name="Lower Body B")
    add_workout(service_session, user_id, -2, bench, [(8, 57.5, 7.0, True)])
    answer = "Today is Upper Body A: bench press 3 x 8 at 60 kg, then back squat 4 x 6."

    reply, outcome, provider = ask(service_session, user_id, daily_reads(), recommend(answer))

    assert reply == answer
    assert outcome["intent"] == "DAILY_WORKOUT"
    assert outcome["decision"] == "RETRIEVE_THEN_ANSWER"
    assert outcome["tools_used"] == list(DAILY_READS)
    # the plan for today, as stored: no weight where the plan prescribes none
    current = received(provider)["get_current_workout_plan"]["output"]
    assert (current["plan_id"], current["today"], current["days_from_today"]) == (
        plan.id,
        "2026-10-13",
        0,
    )
    assert [
        (item["exercise_name"], item["sets"], item["reps"], item["weight_kg"])
        for item in current["exercises"]
    ] == [("Barbell Bench Press", 3, 8, 60.0), ("Barbell Back Squat", 4, 6, None)]


def test_the_last_workout_and_its_effort_reach_the_recommendation(
    service_session, user_id, exercises
):
    bench, _ = exercises
    add_plan(service_session, user_id, 0, (bench, 3, 8, 60.0))
    add_workout(service_session, user_id, -5, bench, [(8, 55.0, 6.0, True)])
    last = add_workout(
        service_session,
        user_id,
        -1,
        bench,
        [(8, 60.0, 8.5, True), (7, 60.0, 9.5, True), (4, 60.0, 10.0, False)],
    )

    _, outcome, provider = ask(
        service_session, user_id, daily_reads(), recommend("Go lighter today: 2 x 8.")
    )

    assert outcome["status"] == "success"
    # in the same turn as the plan: when it was and how hard it was
    workout = received(provider)["get_latest_workout_session"]["output"]
    assert (workout["session_id"], workout["days_ago"]) == (last.id, 1)
    assert [(item["rpe"], item["completed"]) for item in workout["exercises"][0]["sets"]] == [
        (8.5, True),
        (9.5, True),
        (10.0, False),
    ]


def test_without_a_plan_the_coach_is_told_there_is_none(service_session, user_id, exercises):
    bench, _ = exercises
    # not plans to do: one not ready, one cancelled
    add_plan(service_session, user_id, 0, (bench, 3, 8, 60.0), status="DRAFT")
    add_plan(service_session, user_id, 1, (bench, 3, 8, 60.0), status="CANCELLED")
    add_workout(service_session, user_id, -3, bench, [(8, 60.0, 7.0, True)])
    answer = "You have no workout planned in Formiq. Plan one, or try a short session."

    reply, outcome, provider = ask(service_session, user_id, daily_reads(), recommend(answer))

    assert reply == answer
    assert received(provider)["get_current_workout_plan"]["error"]["code"] == "RESOURCE_NOT_FOUND"
    # checked and missing: the answer rests on the profile and the last workout
    assert outcome["tools_used"] == ["get_user_profile", "get_latest_workout_session"]


def test_without_a_completed_workout_none_is_given_to_the_coach(
    service_session, user_id, exercises, profile_fields
):
    bench, _ = exercises
    add_plan(service_session, user_id, 0, (bench, 3, 8, 60.0))
    # not workouts done: one running, one cancelled, and another user's
    add_workout(service_session, user_id, 0, bench, [(8, 60.0, None, True)], "IN_PROGRESS")
    add_workout(service_session, user_id, -1, bench, [(8, 60.0, None, True)], "CANCELLED")
    other = create_user(service_session, "daily-other@example.com", profile_fields)
    add_workout(service_session, other, -1, bench, [(8, 60.0, 9.0, True)])

    _, outcome, provider = ask(
        service_session, user_id, daily_reads(), recommend("Start with today's plan.")
    )

    assert received(provider)["get_latest_workout_session"]["error"] == {
        "code": "RESOURCE_NOT_FOUND",
        "message": "the user has no completed workout session yet; there is no id to ask for",
    }
    assert outcome["tools_used"] == ["get_user_profile", "get_current_workout_plan"]


# --- constraints and safety ---


@pytest.mark.parametrize(
    ("message", "rule"),
    [
        ("I only have 20 minutes today. What should I do?", "- Limited time:"),
        ("I'm exhausted and only slept 4 hours. What should I do today?", "- Tired,"),
    ],
    ids=["limited_time", "tired"],
)
def test_time_and_tiredness_adapt_todays_plan_on_the_normal_path(
    service_session, user_id, exercises, message, rule
):
    bench, squat = exercises
    add_plan(service_session, user_id, 0, (bench, 3, 8, 60.0), (squat, 4, 6, 80.0))
    add_workout(service_session, user_id, -1, bench, [(8, 60.0, 9.0, True)])
    answer = "Do the bench press only, 2 x 8 at 60 kg, and skip the squats today."

    reply, outcome, provider = ask(
        service_session, user_id, daily_reads(), recommend(answer), message=message
    )

    # not a safety risk: the coach gets the plan and the last workout to adapt,
    # under its instructions for it
    assert reply == answer
    assert outcome["safety_category"] == "SAFE"
    assert outcome["tools_used"] == list(DAILY_READS)
    assert rule in COACH_INSTRUCTIONS
    # the instructions, then the calendar of the request (Phase 2.7): nothing else
    assert provider.generate_turn.call_args.kwargs["instructions"] == (
        f"{COACH_INSTRUCTIONS}\n\n{date_note(CoachDates(today=formiq_tools.utc_today()))}"
    )


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("My knee hurts. What should I do today?", SafetyCategory.INSUFFICIENT_SAFETY_CONTEXT),
        (
            "I have a sharp pain in my shoulder. What should I train today?",
            SafetyCategory.PAIN_OR_INJURY,
        ),
    ],
    ids=["unclear_discomfort", "sharp_pain"],
)
def test_pain_keeps_the_safety_path_and_reads_nothing(
    service_session, user_id, exercises, monkeypatch, message, category
):
    bench, _ = exercises
    add_plan(service_session, user_id, 0, (bench, 3, 8, 60.0))
    runs = []
    monkeypatch.setattr(FormiqTools, "run", lambda self, calls, **_: runs.append(calls))

    # a model that ignores the risk and recommends today's plan anyway
    reply, outcome, provider = ask(
        service_session,
        user_id,
        daily_reads(),
        recommend("Bench 3 x 8 at 60 kg."),
        message=message,
    )

    assert reply == SAFETY_POLICY[category].fallback_reply
    assert outcome["safety_category"] == category
    assert outcome["tools_used"] == []
    assert runs == []
    provider.generate_turn.assert_called_once()


# --- nothing missing is presented as data ---


def test_a_recommendation_made_before_checking_never_reaches_the_user(service_session, user_id):
    invented = "Today is Push Day: bench press 3 x 8 at 60 kg."
    honest = "You have no workout planned and no workouts recorded yet. Plan one in Formiq."

    reply, outcome, provider = ask(
        service_session,
        user_id,
        # from the profile alone, inventing a plan
        tool_turn(call("get_user_profile")),
        recommend(invented),
        daily_reads(),
        recommend(honest),
    )

    assert reply == honest
    rejection = received(provider, 2)["respond"]["error"]
    assert rejection["code"] == "DECISION_REJECTED"
    assert "get_current_workout_plan, get_latest_workout_session checked" in rejection["message"]
    data = received(provider, 3)
    assert data["get_current_workout_plan"]["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert data["get_latest_workout_session"]["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert outcome["decision"] == "RETRIEVE_THEN_ANSWER"


def test_with_no_data_at_all_a_recommendation_is_not_an_answer_from_data(service_session):
    user_id = create_user(service_session, "daily-new@example.com")
    honest = "I don't have your profile, a plan or any workouts yet. Set up your profile first."

    reply, outcome, provider = ask(
        service_session,
        user_id,
        daily_reads(),
        recommend("Do your usual Push Day: bench press 3 x 8 at 60 kg."),
        respond_turn(honest, "DAILY_WORKOUT", "CANNOT_ANSWER"),
    )

    assert reply == honest
    assert {name: result["error"]["code"] for name, result in received(provider).items()} == {
        "get_user_profile": "PROFILE_NOT_FOUND",
        "get_current_workout_plan": "RESOURCE_NOT_FOUND",
        "get_latest_workout_session": "RESOURCE_NOT_FOUND",
    }
    assert "none was returned" in received(provider, 2)["respond"]["error"]["message"]
    assert (outcome["decision"], outcome["tools_used"]) == ("CANNOT_ANSWER", [])


# --- identity and ownership, through the API ---


@pytest.fixture
def use_provider(client):
    def use(provider):
        app.dependency_overrides[get_ai_provider] = lambda: provider
        return provider

    try:
        yield use
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)


@pytest.fixture
def two_users(client, test_engine, profile_fields, exercises):
    """A signed-in user with a profile and nothing else, and another user with a
    plan for today and a workout yesterday."""
    bench, _ = exercises
    with Session(test_engine) as session:
        mine = create_user(session, "daily-me@example.com", profile_fields)
        theirs = create_user(session, "daily-them@example.com", profile_fields)
        plan = add_plan(session, theirs, 0, (bench, 5, 5, 100.0), name="Their Plan")
        workout = add_workout(session, theirs, -1, bench, [(5, 100.0, 9.0, True)])
        return mine, theirs, plan.id, workout.id


def test_another_users_plan_and_workout_are_never_recommended(client, use_provider, two_users):
    mine, _, their_plan, _ = two_users
    provider = use_provider(
        fake_provider(
            # the user names the other user's plan, so its id is grounded
            daily_reads(call("get_workout_plan", plan_id=their_plan)),
            recommend("You have no workout planned today."),
        )
    )

    response = client.post(
        "/coach/message",
        headers=bearer(mine),
        json={"message": f"What should I do today? My friend does plan {their_plan}."},
    )

    assert response.status_code == 200
    data = received(provider)
    assert data["get_user_profile"]["output"]["user_id"] == mine
    # the other user's plan and workout are missing for this user, as if they did not exist
    for name in ("get_current_workout_plan", "get_latest_workout_session", "get_workout_plan"):
        assert data[name]["error"]["code"] == "RESOURCE_NOT_FOUND", name


def test_the_model_and_the_body_cannot_choose_whose_day_is_planned(client, use_provider, two_users):
    mine, theirs, _, _ = two_users
    provider = use_provider(
        fake_provider(
            tool_turn(
                call("get_current_workout_plan", user_id=theirs),
                call("get_latest_workout_session", user_id=theirs),
            ),
            daily_reads(),
            recommend("You have no workout planned today."),
        )
    )

    rejected = client.post(
        "/coach/message", headers=bearer(mine), json={"user_id": theirs, "message": MESSAGE}
    )
    response = client.post("/coach/message", headers=bearer(mine), json={"message": MESSAGE})

    # a body naming a user is refused before the coach runs
    assert rejected.status_code == 422
    assert response.status_code == 200
    # the model's user is refused before anything is read
    assert {name: result["error"]["code"] for name, result in received(provider, 1).items()} == {
        "get_current_workout_plan": "INVALID_INPUT",
        "get_latest_workout_session": "INVALID_INPUT",
    }
    # and the reads are the signed-in user's
    data = received(provider, 2)
    assert data["get_user_profile"]["output"]["user_id"] == mine
    assert data["get_current_workout_plan"]["error"]["code"] == "RESOURCE_NOT_FOUND"
