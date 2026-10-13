"""Workout plans the coach proposes, and the user's approval that saves one.

First the proposal tool on the real catalog: what a proposal holds, the user's
time and equipment it must fit, and the exercises and prescriptions it
refuses. Then the whole flow through the API: the coach proposes, nothing is
saved, and only the signed-in user's approval of the exact proposal they were
shown creates the plan, once.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

import re
from datetime import UTC, datetime, timedelta
from itertools import count
from unittest.mock import ANY, Mock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import ToolCall
from app.api.dependencies import PROPOSAL_TTL, get_ai_provider, get_approval_store
from app.approvals import ApprovalStore
from app.main import app
from app.models import WorkoutPlan
from app.schemas import WorkoutPlanProposalResponse
from app.services import (
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.tools import FormiqTools, formiq_tools
from tests.auth import bearer
from tests.coach import call, fake_provider, respond_turn, tool_turn
from tests.integration.test_coach_daily import (
    TODAY,
    add_plan,
    create_user,
    daily_reads,
    received,
    recommend,
)
from tests.integration.workout_plans import add_user, retire_exercise

UNKNOWN_EXERCISE = 2_147_483_647


class Clock:
    def __init__(self):
        self.now = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def today(monkeypatch):
    """Formiq's date, fixed for these tests."""
    monkeypatch.setattr(formiq_tools, "utc_today", lambda: TODAY)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(clock):
    return ApprovalStore(clock=clock, ttl=PROPOSAL_TTL)


@pytest.fixture
def ids(catalog_exercise_ids):
    return catalog_exercise_ids


_call_ids = count(1)


def proposal(**arguments):
    """The model's propose_workout_plan call. (tests.coach.call would take its
    name argument for the tool's.)"""
    return ToolCall(name="propose_workout_plan", arguments=arguments, id=f"p-{next(_call_ids)}")


def exercise(exercise_id, sets=3, reps=10, **fields):
    return {"exercise_id": exercise_id, "sets": sets, "reps": reps, **fields}


def bodyweight(ids):
    """A short workout that needs no equipment."""
    return {
        "name": "Bodyweight Basics",
        "exercises": [
            exercise(ids["Push-Up"], rest_seconds=60),
            exercise(ids["Walking Lunge"], reps=12, rest_seconds=60, notes="Each leg"),
        ],
    }


# --- the proposal tool ---


@pytest.fixture
def tools(db_session, store):
    return FormiqTools(
        users=UserService(db_session),
        profiles=UserProfileService(db_session),
        plans=WorkoutPlanService(db_session),
        sessions=WorkoutSessionService(db_session),
        catalog=ExerciseCatalogService(db_session),
        # ending the read would roll back the flushed test data
        end_read=Mock(),
        today=TODAY,
        approvals=store,
    )


@pytest.fixture
def user(db_session):
    return add_user(db_session, "proposals@example.com")


def propose(tools, user, **arguments):
    (result,) = tools.run([proposal(**arguments)], user_id=user.id)
    return result


def test_a_proposal_is_built_from_the_catalog_and_saves_nothing(
    tools, db_session, user, ids, store, clock
):
    result = propose(
        tools, user, **bodyweight(ids), max_minutes=30, unavailable_equipment=["Dumbbell"]
    )

    output = result["output"]
    assert {key: value for key, value in output.items() if key != "expires_at"} == {
        "status": "awaiting_user_approval",
        "name": "Bodyweight Basics",
        "scheduled_date": "2026-10-13",
        "days_from_today": 0,
        "exercises": [
            {
                "exercise_order": 1,
                "exercise_id": ids["Push-Up"],
                "exercise_name": "Push-Up",
                "equipment": [],
                "sets": 3,
                "reps": 10,
                "rest_seconds": 60,
                "notes": None,
            },
            {
                "exercise_order": 2,
                "exercise_id": ids["Walking Lunge"],
                "exercise_name": "Walking Lunge",
                "equipment": [],
                "sets": 3,
                "reps": 12,
                "rest_seconds": 60,
                "notes": "Each leg",
            },
        ],
        # 6 sets of 45 s, each with 60 s of rest
        "estimated_minutes": 11,
    }
    # registered for the trusted user, waiting for their approval
    ((registered, shown),) = tools.proposals
    assert shown.model_dump(mode="json") == output
    assert registered.expires_at == clock.now + PROPOSAL_TTL
    assert store.find(registered.proposal_id) == (ANY, registered)
    assert registered.trusted_user_id == user.id
    assert registered.values()["exercises"] == [
        {
            "exercise_id": ids["Push-Up"],
            "exercise_order": 1,
            "sets": 3,
            "reps": 10,
            "rest_seconds": 60,
        },
        {
            "exercise_id": ids["Walking Lunge"],
            "exercise_order": 2,
            "sets": 3,
            "reps": 12,
            "rest_seconds": 60,
            "notes": "Each leg",
        },
    ]
    assert db_session.scalars(select(WorkoutPlan).where(WorkoutPlan.user_id == user.id)).all() == []


@pytest.mark.parametrize(
    ("names", "constraints", "reason"),
    [
        (
            [("Dumbbell Shoulder Press", 3)],
            {"unavailable_equipment": ["dumbbell"]},
            "needs Dumbbell, which the user cannot use",
        ),
        (
            [("Barbell Back Squat", 3)],
            {"unavailable_equipment": ["Squat Rack"]},
            "needs Squat Rack",
        ),
        (
            # 12 sets of 45 s with 90 s of rest, the default
            [("Push-Up", 4), ("Walking Lunge", 4), ("Pull-Up", 4)],
            {"max_minutes": 20},
            "takes about 27 minutes, more than the 20 the user has",
        ),
    ],
    ids=["no_dumbbells", "crowded_gym", "limited_time"],
)
def test_a_proposal_must_fit_the_users_time_and_equipment(
    tools, user, ids, names, constraints, reason
):
    exercises = [exercise(ids[name], sets=sets) for name, sets in names]

    result = propose(tools, user, name="Today", exercises=exercises, **constraints)

    assert result["error"]["code"] == "INVALID_INPUT"
    assert reason in result["error"]["message"]
    assert tools.proposals == []


@pytest.mark.parametrize(
    "change",
    [
        {"exercises": [exercise(UNKNOWN_EXERCISE)]},
        {"exercises": []},
        {"exercises": [exercise(1)] * 11},
        {"exercises": [exercise(1, sets=0)]},
        {"exercises": [exercise(1, sets=11)]},
        {"exercises": [exercise(1, reps=31)]},
        {"exercises": [exercise(1, sets=3.0)]},
        {"exercises": [exercise(1, sets="3")]},
        {"exercises": [exercise(1, rest_seconds=301)]},
        {"exercises": [exercise(1, weight_kg=60)]},
        {"exercises": [exercise(1, user_id=2)]},
        {"scheduled_date": "2026-10-12"},
        {"scheduled_date": "2026-10-28"},
        {"approved": True},
        {"exercises": [exercise(1, notes="Push through the pain")]},
    ],
    ids=[
        "unknown_exercise",
        "no_exercise",
        "too_many_exercises",
        "no_sets",
        "too_many_sets",
        "too_many_reps",
        "float_sets",
        "text_sets",
        "too_long_rest",
        "a_weight",
        "a_user",
        "yesterday",
        "too_far_ahead",
        "an_approval",
        "unsafe_notes",
    ],
)
def test_invalid_exercises_or_prescriptions_are_rejected(tools, user, ids, change):
    arguments = {"name": "Today", "exercises": [exercise(ids["Push-Up"])], **change}
    if change.get("exercises") and change["exercises"][0]["exercise_id"] == 1:
        # a real exercise, so only the prescription is wrong
        arguments["exercises"] = [
            {**item, "exercise_id": ids["Push-Up"]} for item in change["exercises"]
        ]

    result = propose(tools, user, **arguments)

    assert result["error"]["code"] == "INVALID_INPUT"
    assert tools.proposals == []


def test_a_retired_exercise_is_never_proposed(tools, user, retirable_exercise_id, test_engine):
    retire_exercise(test_engine, retirable_exercise_id)

    result = propose(tools, user, name="Today", exercises=[exercise(retirable_exercise_id)])

    assert result["error"] == {
        "code": "INVALID_INPUT",
        "message": f"exercise {retirable_exercise_id} is not an active Formiq catalog exercise",
    }


# --- through the coach and the API ---


@pytest.fixture
def use_provider(client):
    def use(*turns):
        provider = fake_provider(*turns)
        app.dependency_overrides[get_ai_provider] = lambda: provider
        return provider

    try:
        yield use
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)


@pytest.fixture(autouse=True)
def use_store(store):
    app.dependency_overrides[get_approval_store] = lambda: store
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_approval_store, None)


@pytest.fixture
def users(client, test_engine, profile_fields):
    """Two signed-up users with a profile and no plan."""
    with Session(test_engine) as session:
        return (
            create_user(session, "proposals-me@example.com", profile_fields),
            create_user(session, "proposals-them@example.com", profile_fields),
        )


def plans_of(test_engine, user_id):
    with Session(test_engine) as session:
        return session.scalars(select(WorkoutPlan.id).where(WorkoutPlan.user_id == user_id)).all()


def ask(client, use_provider, user_id, *turns, message="What should I do today?"):
    provider = use_provider(*turns)
    response = client.post("/coach/message", headers=bearer(user_id), json={"message": message})
    assert response.status_code == 200, response.json()
    return response.json(), provider


def proposing(ids):
    """A model that reads what today needs and the catalog, then proposes a
    bodyweight workout that fits 30 minutes without dumbbells."""
    return (
        daily_reads(
            call("search_exercises", movement_pattern="HORIZONTAL_PUSH"),
            call("search_exercises", movement_pattern="LUNGE"),
        ),
        tool_turn(proposal(**bodyweight(ids), max_minutes=30, unavailable_equipment=["Dumbbell"])),
        recommend("Here is a short bodyweight workout. Review it, and approve it to save it."),
    )


def approve(client, user_id, shown, binding=None):
    """The user approves the proposal as the coach's response showed it."""
    return client.post(
        f"/coach/proposals/{shown['proposal_id']}/approve",
        headers=bearer(user_id),
        json={"binding": binding or shown["binding"]},
    )


def test_a_suitable_planned_workout_is_recommended_not_proposed_again(
    client, use_provider, users, ids, test_engine
):
    me, _ = users
    with Session(test_engine) as session:
        planned = add_plan(session, me, 0, (ids["Barbell Bench Press"], 3, 8, 60.0)).id
    answer = "Today is Upper Body A: bench press 3 x 8 at 60 kg."

    body, provider = ask(
        client,
        use_provider,
        me,
        # proposing before looking at the plan is refused
        tool_turn(proposal(**bodyweight(ids))),
        daily_reads(),
        recommend(answer),
    )

    assert body == {"reply": answer}
    refusal = received(provider, 1)["propose_workout_plan"]["error"]
    assert refusal["code"] == "PROPOSAL_REFUSED"
    assert "a suitable planned workout is recommended, not duplicated" in refusal["message"]
    assert plans_of(test_engine, me) == [planned]


def test_a_proposed_plan_is_saved_only_by_the_users_approval_and_once(
    client, use_provider, users, ids, test_engine
):
    me, _ = users

    body, _ = ask(client, use_provider, me, *proposing(ids))

    shown = body["proposal"]
    assert set(shown) == set(WorkoutPlanProposalResponse.model_fields)
    assert re.fullmatch(r"[0-9a-f]{32}", shown["proposal_id"])
    assert re.fullmatch(r"[0-9a-f]{64}", shown["binding"])
    assert (shown["name"], shown["scheduled_date"], shown["estimated_minutes"]) == (
        "Bodyweight Basics",
        "2026-10-13",
        11,
    )
    assert [
        (item["exercise_name"], item["equipment"], item["sets"], item["reps"])
        for item in shown["exercises"]
    ] == [("Push-Up", [], 3, 10), ("Walking Lunge", [], 3, 12)]
    # proposed, not saved
    assert plans_of(test_engine, me) == []

    response = approve(client, me, shown)

    assert response.status_code == 201
    plan = response.json()
    assert (plan["user_id"], plan["name"], plan["status"], plan["scheduled_date"]) == (
        me,
        "Bodyweight Basics",
        "PLANNED",
        "2026-10-13",
    )
    assert [
        (
            item["exercise_order"],
            item["exercise_id"],
            item["sets"],
            item["reps"],
            item["weight_kg"],
            item["rest_seconds"],
            item["notes"],
        )
        for item in plan["exercises"]
    ] == [
        (1, ids["Push-Up"], 3, 10, None, 60, None),
        (2, ids["Walking Lunge"], 3, 12, None, 60, "Each leg"),
    ]
    assert client.get(f"/users/{me}/workout-plans/{plan['id']}").json() == plan
    # the approval is used up
    again = approve(client, me, shown)
    assert (again.status_code, again.json()) == (
        409,
        {"detail": "this proposal was already approved"},
    )
    assert plans_of(test_engine, me) == [plan["id"]]


def test_an_approval_covers_only_the_proposal_shown_and_only_until_it_expires(
    client, use_provider, users, ids, test_engine, clock
):
    me, _ = users
    first, _ = ask(client, use_provider, me, *proposing(ids))
    second, _ = ask(client, use_provider, me, *proposing(ids))
    first, second = first["proposal"], second["proposal"]

    # approving one proposal with what was shown of another approves nothing
    mixed = approve(client, me, first, binding=second["binding"])
    assert mixed.status_code == 409
    assert "different version of the proposal" in mixed.json()["detail"]
    assert plans_of(test_engine, me) == []
    # the proposal itself is still waiting for the user
    assert approve(client, me, first).status_code == 201

    clock.now += PROPOSAL_TTL
    expired = approve(client, me, second)
    assert (expired.status_code, expired.json()) == (
        409,
        {"detail": "this proposal has expired: ask the coach for a new one"},
    )
    assert len(plans_of(test_engine, me)) == 1


def test_another_user_can_neither_approve_nor_find_a_proposal(
    client, use_provider, users, ids, test_engine
):
    me, them = users
    body, _ = ask(client, use_provider, me, *proposing(ids))
    shown = body["proposal"]

    theirs = approve(client, them, shown)

    # not told apart from a proposal that does not exist
    assert theirs.status_code == 404
    missing = approve(client, them, {**shown, "proposal_id": "0" * 32})
    assert missing.json() == {"detail": f"there is no workout plan proposal {'0' * 32}"}
    assert theirs.json() == {"detail": f"there is no workout plan proposal {shown['proposal_id']}"}
    assert plans_of(test_engine, me) == plans_of(test_engine, them) == []
    # their attempt decided nothing
    assert approve(client, me, shown).status_code == 201


@pytest.mark.parametrize(
    ("proposal_id", "body", "signed_in", "status"),
    [
        ("not-a-proposal", {"binding": "a" * 64}, True, 422),
        ("a" * 32, {"binding": "not-a-binding"}, True, 422),
        ("a" * 32, {"binding": "a" * 64, "user_id": 1}, True, 422),
        ("a" * 32, {}, True, 422),
        ("a" * 32, {"binding": "a" * 64}, False, 401),
    ],
    ids=["bad_id", "bad_binding", "user_id_in_body", "no_binding", "signed_out"],
)
def test_a_malformed_or_unauthenticated_approval_is_refused(
    client, users, proposal_id, body, signed_in, status
):
    me, _ = users
    headers = bearer(me) if signed_in else {}

    response = client.post(f"/coach/proposals/{proposal_id}/approve", headers=headers, json=body)

    assert response.status_code == status


def test_without_a_profile_the_coach_asks_instead_of_proposing(
    client, use_provider, test_engine, ids
):
    with Session(test_engine) as session:
        me = create_user(session, "proposals-new@example.com")
    question = "How experienced are you, and what equipment do you have?"

    body, provider = ask(
        client,
        use_provider,
        me,
        daily_reads(call("search_exercises", movement_pattern="HORIZONTAL_PUSH")),
        tool_turn(proposal(**bodyweight(ids))),
        respond_turn(question, "DAILY_WORKOUT", "ASK_CLARIFICATION"),
    )

    assert body == {"reply": question}
    refusal = received(provider, 2)["propose_workout_plan"]["error"]
    assert refusal["code"] == "PROPOSAL_REFUSED"
    assert "no fitness profile" in refusal["message"]
    assert plans_of(test_engine, me) == []
