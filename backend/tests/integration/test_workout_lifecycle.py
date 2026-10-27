"""A workout's whole life through the API: the coach proposes it, the user
approves it, the saved plan is reopened with each exercise's instructions from
Formiq's database, the workout runs as a session that survives a restart, and
the completed session is the user's history.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.orm import Session

from app.api.dependencies import PROPOSAL_TTL, get_ai_provider, get_proposal_terms
from app.approvals import ProposalTerms
from app.db.database import get_db
from app.main import app
from app.models import Exercise, WorkoutPlanProposal, WorkoutSession
from app.services import PlanProposalService
from app.tools import formiq_tools
from tests.auth import bearer
from tests.coach import fake_provider, respond_turn, tool_turn
from tests.integration.test_coach_daily import TODAY, create_user, daily_reads, recommend
from tests.integration.test_plan_proposal_persistence import proposal_for
from tests.integration.test_plan_proposals import (
    NO_PULL,
    approve,
    ask,
    at_home_searches,
    main_of,
    plans_of,
    proposal,
    workout,
)


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
def terms(clock):
    return ProposalTerms(clock=clock, ttl=PROPOSAL_TTL)


@pytest.fixture(autouse=True)
def use_terms(terms):
    app.dependency_overrides[get_proposal_terms] = lambda: terms
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_proposal_terms, None)


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


@pytest.fixture
def users(client, test_engine, profile_fields):
    """Two signed-up users with a profile and no plan."""
    with Session(test_engine) as session:
        return (
            create_user(session, "lifecycle-me@example.com", profile_fields),
            create_user(session, "lifecycle-them@example.com", profile_fields),
        )


@pytest.fixture
def ids(catalog_exercise_ids):
    return catalog_exercise_ids


def no_model():
    raise AssertionError("the model must not be asked: this is Formiq's own data")


def forbid_the_model():
    """From now on, any request that would reach the model fails the test
    (use_provider's teardown removes the override)."""
    app.dependency_overrides[get_ai_provider] = no_model


@pytest.fixture
def restart(test_database_url):
    """Serves the API's requests from a new engine, as a restarted process
    would: nothing is kept from before but what PostgreSQL holds."""
    engines = []
    previous = app.dependency_overrides.get(get_db)

    def restarted():
        engine = create_engine(test_database_url)
        engines.append(engine)

        def get_restarted_db():
            with Session(engine) as session:
                yield session

        app.dependency_overrides[get_db] = get_restarted_db

    try:
        yield restarted
    finally:
        app.dependency_overrides[get_db] = previous
        for engine in engines:
            engine.dispose()


def catalog_descriptions(test_engine, exercise_ids):
    with Session(test_engine) as session:
        return dict(
            session.execute(
                select(Exercise.id, Exercise.description).where(Exercise.id.in_(exercise_ids))
            ).all()
        )


def sessions_of(test_engine, user_id):
    with Session(test_engine) as session:
        return session.scalars(
            select(WorkoutSession.id).where(WorkoutSession.user_id == user_id)
        ).all()


AT_HOME_REPLY = (
    "Here is a full-body bodyweight workout, about 27 minutes. It has no pulling exercise: "
    "there is none you can do without equipment. Review it and approve it to save it."
)


def at_home(ids):
    """A model that proposes a full-body workout for a user without equipment:
    Formiq's catalog has no pull they can do, so the proposal is incomplete."""
    plan = workout(
        ids,
        *main_of(ids, "Bodyweight Squat", "Push-Up", "Walking Lunge", "Bird Dog"),
        available_equipment=[],
    )
    return (
        daily_reads(),
        at_home_searches(),
        tool_turn(proposal(**plan)),
        recommend(AT_HOME_REPLY),
    )


def test_a_workout_from_proposal_to_history(client, use_provider, users, ids, test_engine, restart):
    me, _ = users
    sessions = f"/users/{me}/workout-sessions"

    # 1. the coach proposes: what to show, and how complete it is, as data
    body, _ = ask(client, use_provider, me, *at_home(ids))
    shown = body["proposal"]
    assert body["reply"] == AT_HOME_REPLY
    assert [
        (item["exercise_order"], item["section"], item["exercise_name"], item["equipment"])
        for item in shown["exercises"]
    ] == [
        (1, "WARM_UP", "Brisk Walk", []),
        (2, "MAIN_WORKOUT", "Bodyweight Squat", []),
        (3, "MAIN_WORKOUT", "Push-Up", []),
        (4, "MAIN_WORKOUT", "Walking Lunge", []),
        (5, "MAIN_WORKOUT", "Bird Dog", []),
        (6, "COOL_DOWN", "Brisk Walk", []),
    ]
    assert shown["coverage"]["complete"] is False
    assert shown["coverage"]["missing_regions"] == ["UPPER_PULL"]
    assert shown["coverage"]["limitations"] == [NO_PULL]
    # proposed is not saved, and nothing can run yet
    assert plans_of(test_engine, me) == []
    assert sessions_of(test_engine, me) == []

    # 2. the user approves it: the plan is saved, each exercise with the
    # catalog's details, from the database
    saved = approve(client, me, shown)
    assert saved.status_code == 201
    plan = saved.json()
    assert (plan["status"], plan["name"], plan["scheduled_date"]) == (
        "PLANNED",
        "Today",
        TODAY.isoformat(),
    )
    descriptions = catalog_descriptions(
        test_engine, {item["exercise_id"] for item in plan["exercises"]}
    )
    assert [
        (
            item["exercise_order"],
            item["section"],
            item["exercise"]["name"],
            item["sets"],
            item["reps"],
            item["duration_seconds"],
        )
        for item in plan["exercises"]
    ] == [
        (
            item["exercise_order"],
            item["section"],
            item["exercise_name"],
            item["sets"],
            item["reps"],
            item["duration_seconds"],
        )
        for item in shown["exercises"]
    ]
    for item in plan["exercises"]:
        # Formiq's own exercises: a description, and no upstream steps
        assert item["exercise"]["description"] == descriptions[item["exercise_id"]]
        assert item["exercise"]["description"]
        assert item["exercise"]["instructions"] == []

    # 3. reopening the plan is Formiq's data alone: the model is not asked
    forbid_the_model()
    plan_url = f"/users/{me}/workout-plans/{plan['id']}"
    assert client.get(plan_url).json() == plan
    assert client.get(f"/users/{me}/workout-plans").json() == [plan]

    # 4. the workout starts from the plan and progress is recorded
    started = client.post(sessions, json={"workout_plan_id": plan["id"]})
    assert started.status_code == 201
    session_id = started.json()["id"]
    assert (started.json()["status"], started.json()["completed_at"]) == ("IN_PROGRESS", None)
    session_url = f"{sessions}/{session_id}"
    planned = plan["exercises"]

    def log(order, planned_exercise):
        logged = client.post(
            f"{session_url}/exercises",
            json={
                "exercise_id": planned_exercise["exercise_id"],
                "exercise_order": order,
                "plan_exercise_id": planned_exercise["id"],
            },
        )
        assert logged.status_code == 201, logged.json()
        return f"{session_url}/exercises/{logged.json()['id']}/sets"

    # the timed warm-up walk is recorded as done, without sets
    log(1, planned[0])
    squat_sets = log(2, planned[1])
    for number in (1, 2, 3):
        assert client.post(squat_sets, json={"set_number": number, "reps": 10}).status_code == 201
    push_up_sets = log(3, planned[2])
    assert client.post(push_up_sets, json={"set_number": 1, "reps": 10}).status_code == 201
    # a set the user could not finish is kept as not completed
    assert (
        client.post(
            push_up_sets, json={"set_number": 2, "reps": 6, "rpe": 9.5, "completed": False}
        ).status_code
        == 201
    )
    progress = client.get(session_url).json()

    # 5. the API restarts: the running workout is found again, as it was
    restart()
    assert client.get(sessions, params={"status": "IN_PROGRESS"}).json() == [progress]
    # an unfinished workout is not history
    assert client.get(sessions, params={"status": "COMPLETED"}).json() == []
    # retried requests change nothing: no second session, set or exercise
    again = client.post(sessions, json={"workout_plan_id": plan["id"]})
    assert again.status_code == 409
    assert f"already has workout session {session_id} IN_PROGRESS" in again.json()["detail"]
    assert client.post(push_up_sets, json={"set_number": 2, "reps": 6}).status_code == 409
    assert (
        client.post(
            f"{session_url}/exercises",
            json={"exercise_id": planned[2]["exercise_id"], "exercise_order": 3},
        ).status_code
        == 409
    )
    assert client.get(session_url).json() == progress
    assert sessions_of(test_engine, me) == [session_id]

    # 6. the user finishes: only what was recorded, never the rest of the plan
    completed = client.patch(session_url, json={"status": "COMPLETED"})
    assert completed.status_code == 200
    history = completed.json()
    assert history["status"] == "COMPLETED"
    assert history["completed_at"] is not None
    assert [
        (
            item["exercise_order"],
            item["plan_exercise_id"],
            [(s["set_number"], s["reps"], s["completed"]) for s in item["sets"]],
        )
        for item in history["exercises"]
    ] == [
        (1, planned[0]["id"], []),
        (2, planned[1]["id"], [(1, 10, True), (2, 10, True), (3, 10, True)]),
        (3, planned[2]["id"], [(1, 10, True), (2, 6, False)]),
    ]
    # history is final
    assert client.patch(session_url, json={"notes": "edited"}).status_code == 409
    assert client.post(push_up_sets, json={"set_number": 3, "reps": 5}).status_code == 409

    # 7. after another restart, the history is the user's and unchanged
    restart()
    assert client.get(sessions, params={"status": "COMPLETED"}).json() == [history]
    assert client.get(sessions, params={"status": "IN_PROGRESS"}).json() == []
    assert client.get(session_url).json() == history
    # performing the plan left its prescription as it was
    assert client.get(plan_url).json() == plan


def test_a_saved_plan_reads_its_exercises_details_in_one_query(client, users, ids, test_engine):
    """However many exercises and plans, their catalog details come in one
    query per request, never one per exercise."""
    me, _ = users
    names = ["Brisk Walk", "Push-Up", "Bodyweight Squat", "Walking Lunge", "Bird Dog"]
    for day in range(2):
        created = client.post(
            f"/users/{me}/workout-plans",
            json={
                "name": f"Plan {day}",
                "status": "PLANNED",
                "scheduled_date": (TODAY + timedelta(days=day)).isoformat(),
                "exercises": [
                    {"exercise_id": ids[name], "exercise_order": order, "sets": 3, "reps": 10}
                    for order, name in enumerate(names, start=1)
                ],
            },
        )
        assert created.status_code == 201
        assert [item["exercise"]["name"] for item in created.json()["exercises"]] == names

    statements = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(test_engine, "before_cursor_execute", record)
    try:
        listed = client.get(f"/users/{me}/workout-plans")
        reads_of_the_list = [s for s in statements if "FROM exercises" in s]
        statements.clear()
        one = client.get(f"/users/{me}/workout-plans/{created.json()['id']}")
        reads_of_one = [s for s in statements if "FROM exercises" in s]
    finally:
        event.remove(test_engine, "before_cursor_execute", record)

    assert [len(plan["exercises"]) for plan in listed.json()] == [5, 5]
    assert one.json() == created.json()
    assert len(reads_of_the_list) == len(reads_of_one) == 1


@pytest.mark.parametrize(
    ("fields", "details"),
    [
        (
            {"source_record": {"instructions": ["Stand tall.", "Squat down.", "Stand up."]}},
            {"description": None, "instructions": ["Stand tall.", "Squat down.", "Stand up."]},
        ),
        (
            {"description": "Squat down and stand up.", "source_record": None},
            {"description": "Squat down and stand up.", "instructions": []},
        ),
        # an imported record without steps, as five in the imported catalog are
        ({"source_record": {"instructions": []}}, {"description": None, "instructions": []}),
        ({"source_record": None}, {"description": None, "instructions": []}),
    ],
    ids=["imported_steps", "formiq_description", "imported_without_steps", "nothing"],
)
def test_an_approved_plan_shows_the_instructions_there_are_and_invents_none(
    client, users, test_engine, terms, retirable_exercise_id, fields, details
):
    me, _ = users
    with Session(test_engine) as session:
        session.execute(
            update(Exercise).where(Exercise.id == retirable_exercise_id).values(**fields)
        )
        session.commit()
        offered = proposal_for(me, retirable_exercise_id, terms.clock)
        PlanProposalService(session, terms).register(offered)

    saved = client.post(
        f"/coach/proposals/{offered.proposal_id}/approve",
        headers=bearer(me),
        json={"binding": offered.binding()},
    )

    assert saved.status_code == 201
    plan = saved.json()
    (item,) = plan["exercises"]
    assert item["exercise"] == {"name": "Test Retirable Exercise", **details}
    assert client.get(f"/users/{me}/workout-plans/{plan['id']}").json() == plan


def test_another_user_reaches_neither_the_plan_nor_its_workout(
    client, use_provider, users, ids, test_engine
):
    me, them = users
    body, _ = ask(client, use_provider, me, *at_home(ids))
    plan = approve(client, me, body["proposal"]).json()
    sessions = f"/users/{me}/workout-sessions"
    session_id = client.post(sessions, json={"workout_plan_id": plan["id"]}).json()["id"]
    logged = client.post(
        f"{sessions}/{session_id}/exercises",
        json={"exercise_id": plan["exercises"][1]["exercise_id"], "exercise_order": 1},
    ).json()
    mine = {
        "plan": f"/users/{me}/workout-plans/{plan['id']}",
        "session": f"{sessions}/{session_id}",
    }
    theirs = bearer(them)

    # through my paths, or through theirs: not found, never forbidden
    for path in (
        mine["plan"],
        f"/users/{me}/workout-plans",
        mine["session"],
        sessions,
        f"/users/{them}/workout-plans/{plan['id']}",
        f"/users/{them}/workout-sessions/{session_id}",
    ):
        assert client.get(path, headers=theirs).status_code == 404, path
    assert (
        client.post(
            f"/users/{them}/workout-sessions", headers=theirs, json={"workout_plan_id": plan["id"]}
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"{mine['session']}/exercises/{logged['id']}/sets",
            headers=theirs,
            json={"set_number": 1, "reps": 10},
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/users/{them}/workout-sessions/{session_id}",
            headers=theirs,
            json={"status": "COMPLETED"},
        ).status_code
        == 404
    )
    assert client.delete(mine["plan"], headers=theirs).status_code == 404

    # nothing of mine changed, and they have nothing
    assert client.get(mine["plan"]).json() == plan
    session = client.get(mine["session"]).json()
    assert (session["status"], [item["sets"] for item in session["exercises"]]) == (
        "IN_PROGRESS",
        [[]],
    )
    assert plans_of(test_engine, them) == []
    assert sessions_of(test_engine, them) == []


def test_approvals_at_once_or_repeated_save_one_plan(client, use_provider, users, ids, test_engine):
    me, _ = users
    body, _ = ask(client, use_provider, me, *at_home(ids))
    shown = body["proposal"]
    start = threading.Barrier(3)
    answers = []

    def approve_at_once():
        # each its own client, as separate requests would be
        each = TestClient(app)
        start.wait()
        answers.append(approve(each, me, shown))

    threads = [threading.Thread(target=approve_at_once) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)

    # one saved the plan; the others waited for its row and got that plan back
    assert sorted(answer.status_code for answer in answers) == [200, 200, 201]
    (saved,) = {answer.json()["id"] for answer in answers}
    # and a retry later
    later = approve(client, me, shown)
    assert (later.status_code, later.json()["id"]) == (200, saved)
    (plan_id,) = plans_of(test_engine, me)
    assert plan_id == saved
    with Session(test_engine) as session:
        stored = session.get(WorkoutPlanProposal, shown["proposal_id"])
        assert (stored.status, stored.workout_plan_id) == ("APPROVED", plan_id)


def test_a_proposal_not_approved_never_becomes_a_plan(
    client, use_provider, users, ids, test_engine, clock
):
    me, _ = users
    # refused by Formiq: three main exercises are no full-body workout, and
    # the user is shown nothing to approve
    refused = workout(ids, *main_of(ids, "Bodyweight Squat", "Bird Dog", "Walking Lunge"))
    body, _ = ask(
        client,
        use_provider,
        me,
        daily_reads(),
        at_home_searches(),
        tool_turn(proposal(**refused)),
        respond_turn(
            "I could not put a complete workout together.", "DAILY_WORKOUT", "CANNOT_ANSWER"
        ),
    )
    assert "proposal" not in body
    with Session(test_engine) as session:
        assert (
            session.scalars(
                select(WorkoutPlanProposal).where(WorkoutPlanProposal.user_id == me)
            ).all()
            == []
        )

    # shown, but never approved: no plan, so no workout can start from it
    body, _ = ask(client, use_provider, me, *at_home(ids))
    shown = body["proposal"]
    assert approve(client, me, shown, binding="0" * 64).status_code == 409
    assert client.get(f"/users/{me}/workout-plans").json() == []
    # and once it expires, it approves nothing
    clock.now += PROPOSAL_TTL
    expired = approve(client, me, shown)
    assert expired.json() == {"detail": "this proposal has expired: ask the coach for a new one"}
    assert plans_of(test_engine, me) == []
    assert sessions_of(test_engine, me) == []
