"""Revising a saved workout plan: "rewrite this plan", "a different version".

The coach proposes the revision of a plan the turn read (revises_plan_id and
how it revises it, revision). Formiq checks it against the plan as saved: an
ALTERNATIVE keeps a main exercise of the plan only when the catalog has no
other suitable one for its part of the body, an ADJUST must change something,
and the plan must be the user's and PLANNED. The proposal saves and changes
nothing. Only the user's approval saves it, as a new plan, and cancels the plan
it revises in the same transaction: once, and only if that plan is still
PLANNED and as it was when proposed.

First the proposal tool on the seeded catalog (with test exercises added in a
rolled-back transaction), then the whole flow through the API, as the
2026-10-14 incident went: a core plan, "can rewrite these plan", an
alternative, its approval.

The model is scripted: no test calls Gemini. They require the local PostgreSQL
container to be running.
"""

import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import PROPOSAL_TTL, get_ai_provider, get_proposal_terms
from app.approvals import ProposalTerms
from app.main import app
from app.models import WorkoutPlan, WorkoutPlanExercise, WorkoutPlanProposal
from app.services import (
    ExerciseCatalogService,
    UserProfileService,
    UserService,
    WorkoutPlanService,
    WorkoutSessionService,
)
from app.services.plan_proposal_service import REPLACED_PLAN_CHANGED
from app.tools import FormiqTools, formiq_tools
from tests.auth import bearer
from tests.coach import call, fake_provider, tool_turn
from tests.integration.test_coach_daily import (
    TODAY,
    create_user,
    daily_reads,
    received,
    recommend,
)
from tests.integration.test_plan_proposals import (
    add_main_exercise,
    approve,
    ask,
    main_of,
    problem,
    proposal,
    propose,
    workout,
)
from tests.integration.workout_plans import add_user


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
def ids(catalog_exercise_ids):
    return catalog_exercise_ids


@pytest.fixture
def tools(db_session, terms):
    return FormiqTools(
        users=UserService(db_session),
        profiles=UserProfileService(db_session),
        plans=WorkoutPlanService(db_session),
        sessions=WorkoutSessionService(db_session),
        catalog=ExerciseCatalogService(db_session),
        # ending the read would roll back the flushed test data
        end_read=Mock(),
        today=TODAY,
        proposal_terms=terms,
    )


@pytest.fixture
def users(client, test_engine, profile_fields):
    """Two signed-up users with a profile."""
    with Session(test_engine) as session:
        return (
            create_user(session, "revisions-me@example.com", profile_fields),
            create_user(session, "revisions-them@example.com", profile_fields),
        )


# The incident's plan, on the seeded catalog: its only three core main exercises.
CORE_PLAN = ("Bird Dog", "Band Pallof Press", "Cable Woodchop")
REWRITE = "can rewrite these plan"


def core_plan(session, user_id, ids, *names, status="PLANNED"):
    """A core plan for today, flushed in the session's transaction (the caller
    commits it, or not)."""
    plan = WorkoutPlan(
        user_id=user_id,
        name="Core & Abs Focus",
        status=status,
        scheduled_date=TODAY,
        exercises=[
            WorkoutPlanExercise(
                exercise_id=ids[name], exercise_order=order, sets=3, reps=12, rest_seconds=90
            )
            for order, name in enumerate(names or CORE_PLAN, start=1)
        ],
    )
    session.add(plan)
    session.flush()
    return plan


def revision_of(plan_id, kind, ids, *names, sets=3, **fields):
    return {
        **workout(ids, *main_of(ids, *names, sets=sets), name="Core & Abs Focus (Alternative)"),
        "focus": "CORE",
        "revises_plan_id": plan_id,
        "revision": kind,
        **fields,
    }


@pytest.fixture
def more_core(db_session, ids):
    """Core exercises the user could do instead, with no equipment: in this
    test's transaction only. Four, as a core workout needs four different ones
    (Bug 2, 2026-10-27: three was its minimum before)."""
    return {
        **ids,
        **{
            name: add_main_exercise(db_session, name, "Core", "BEGINNER").id
            for name in ("Test Dead Bug", "Test Side Plank", "Test Hollow Hold", "Test Leg Raise")
        },
    }


# --- the proposal tool ---


def test_an_alternative_must_replace_what_the_catalog_has_replacements_for(
    tools, db_session, ids, more_core
):
    ids = more_core
    user = add_user(db_session, "rewrite@example.com")
    plan = core_plan(db_session, user.id, ids, "Bird Dog", "Band Pallof Press", "Test Dead Bug")

    # the incident's shape: most of the plan kept, though the catalog has others
    kept = propose(
        tools,
        user,
        **revision_of(
            plan.id, "ALTERNATIVE", ids, "Bird Dog", "Band Pallof Press", "Test Side Plank",
            "Test Leg Raise",
        ),
    )

    assert problem(kept) == (
        f"the user asked for a different workout than plan {plan.id}, but this one keeps "
        f"exercise {ids['Bird Dog']} (Bird Dog), exercise {ids['Band Pallof Press']} "
        "(Band Pallof Press) from it, and the catalog has other core exercises the user can "
        "do: replace them with ones the plan does not have, such as search_exercises finds "
        "with use MAIN_WORKOUT and muscle Core; or give revision ADJUST if the user asked "
        "only for some changes"
    )
    assert tools.proposals == []

    # the same exercises in another order are the same exercises
    reordered = propose(
        tools,
        user,
        **revision_of(
            plan.id, "ALTERNATIVE", ids, "Test Dead Bug", "Band Pallof Press", "Bird Dog",
            "Test Leg Raise",
        ),
    )
    assert "keeps exercise" in problem(reordered)

    different = propose(
        tools,
        user,
        **revision_of(
            plan.id, "ALTERNATIVE", ids, "Cable Woodchop", "Test Side Plank", "Test Hollow Hold",
            "Test Leg Raise",
        ),
    )

    output = different["output"]
    assert output["revision"] == {
        "replaces_plan_id": plan.id,
        "replaces_plan_name": "Core & Abs Focus",
        "kind": "ALTERNATIVE",
        "kept_exercises": [],
    }
    # the requested focus, fulfilled
    assert (output["coverage"]["focus"], output["coverage"]["complete"]) == ("CORE", True)
    assert output["coverage"]["trained_regions"] == ["CORE"]


def test_an_alternative_may_keep_what_the_catalog_has_no_replacement_for(
    tools, db_session, ids, more_core
):
    """With no equipment, the core exercises the user can do are Bird Dog and
    the four test ones. The plan holds three of them, so an alternative of the
    four a core workout needs can bring in only two others: it may keep two, and
    says which."""
    ids = more_core
    user = add_user(db_session, "rewrite@example.com")
    plan = core_plan(db_session, user.id, ids, "Bird Dog", "Test Dead Bug", "Test Side Plank")

    result = propose(
        tools,
        user,
        **revision_of(
            plan.id,
            "ALTERNATIVE",
            ids,
            "Bird Dog",
            "Test Hollow Hold",
            "Test Dead Bug",
            "Test Leg Raise",
            available_equipment=[],
        ),
    )

    assert result["output"]["revision"]["kept_exercises"] == ["Bird Dog", "Test Dead Bug"]


def test_an_alternative_to_a_plan_of_the_catalogs_only_core_exercises_keeps_them(
    tools, db_session, ids
):
    """The seeded catalog has three core main exercises, all in the plan: the
    alternative cannot be new, and says what it kept."""
    user = add_user(db_session, "rewrite@example.com")
    plan = core_plan(db_session, user.id, ids)

    result = propose(
        tools, user, **revision_of(plan.id, "ALTERNATIVE", ids, *reversed(CORE_PLAN), sets=4)
    )

    assert result["output"]["revision"]["kept_exercises"] == list(reversed(CORE_PLAN))


def saved_as_proposed(session, user_id, arguments):
    """A PLANNED plan for today holding exactly the workout these proposal
    arguments describe, as its approval would save it."""
    sections = [
        ("WARM_UP", arguments["warm_up"]),
        ("MAIN_WORKOUT", arguments["exercises"]),
        ("COOL_DOWN", arguments["cool_down"]),
    ]
    items = [(section, item) for section, items in sections for item in items]
    plan = WorkoutPlan(
        user_id=user_id,
        name=arguments["name"],
        status="PLANNED",
        scheduled_date=TODAY,
        exercises=[
            WorkoutPlanExercise(
                exercise_id=item["exercise_id"],
                exercise_order=order,
                section=section,
                sets=item["sets"],
                reps=item.get("reps"),
                duration_seconds=item.get("duration_seconds"),
                rest_seconds=item.get("rest_seconds"),
            )
            for order, (section, item) in enumerate(items, start=1)
        ],
    )
    session.add(plan)
    session.flush()
    return plan


def test_an_adjustment_must_change_something(tools, db_session, ids):
    user = add_user(db_session, "rewrite@example.com")
    as_saved = revision_of(None, "ADJUST", ids, *CORE_PLAN)
    plan = saved_as_proposed(db_session, user.id, as_saved)

    unchanged = propose(tools, user, **{**as_saved, "revises_plan_id": plan.id})

    # changed on purpose in Phase 2.5: the refusal also says how a move to another day is made
    assert problem(unchanged) == (
        f"this is workout plan {plan.id} unchanged, on its own day {TODAY.isoformat()}: make the "
        "changes the user asked for. To move it to another day, give scheduled_date for the day "
        "they named; when they did not name a day, ask which (ASK_CLARIFICATION) and do not "
        "choose one"
    )
    assert tools.proposals == []

    fewer_sets = revision_of(plan.id, "ADJUST", ids, *CORE_PLAN, sets=2)
    output = propose(tools, user, **fewer_sets)["output"]

    # an adjustment keeps what it does not change, and says so
    assert output["revision"] == {
        "replaces_plan_id": plan.id,
        "replaces_plan_name": "Core & Abs Focus (Alternative)",
        "kind": "ADJUST",
        "kept_exercises": list(CORE_PLAN),
    }


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"revision": None}, "revises_plan_id and revision go together"),
        ({"revises_plan_id": None}, "revises_plan_id and revision go together"),
        ({"revision": "REPLACE"}, "revision: Input should be 'ADJUST' or 'ALTERNATIVE'"),
    ],
)
def test_a_revision_names_its_plan_and_how_it_revises_it(tools, db_session, ids, change, message):
    user = add_user(db_session, "rewrite@example.com")
    plan = core_plan(db_session, user.id, ids)
    arguments = {**revision_of(plan.id, "ALTERNATIVE", ids, *CORE_PLAN), **change}

    assert message in problem(propose(tools, user, **arguments))


def test_only_the_users_own_planned_plan_is_revised(tools, db_session, ids):
    user = add_user(db_session, "rewrite@example.com")
    them = add_user(db_session, "rewrite-them@example.com")
    theirs = core_plan(db_session, them.id, ids)
    cancelled = core_plan(db_session, user.id, ids, status="CANCELLED")

    other = propose(tools, user, **revision_of(theirs.id, "ALTERNATIVE", ids, *CORE_PLAN))
    assert other["error"] == {
        "code": "RESOURCE_NOT_FOUND",
        "message": f"the user has no workout plan {theirs.id}",
    }
    assert problem(
        propose(tools, user, **revision_of(cancelled.id, "ALTERNATIVE", ids, *CORE_PLAN))
    ) == (
        f"workout plan {cancelled.id} is CANCELLED, and only a PLANNED plan can be revised: "
        "propose a new workout, without revises_plan_id and revision"
    )


# --- through the coach and the API ---


def rewriting(ids, plan_id, *names, sets=4):
    """A model asked to rewrite today's plan: it reads what today needs (the
    plan among it), core exercises and warm-up activities, then proposes an
    alternative, of sets sets each."""
    return (
        daily_reads(
            call("search_exercises", use="MAIN_WORKOUT", muscle="Core"),
            call("search_exercises", use="WARM_UP"),
        ),
        tool_turn(proposal(**revision_of(plan_id, "ALTERNATIVE", ids, *names, sets=sets))),
        recommend(
            "Here is another version of your core workout. Approving it in Formiq replaces "
            "today's plan; it keeps the same three exercises, as they are the only core ones "
            "the catalog has."
        ),
    )


@pytest.fixture
def me(users):
    return users[0]


@pytest.fixture
def plan_id(me, ids, test_engine):
    with Session(test_engine) as session:
        plan = core_plan(session, me, ids)
        session.commit()
        return plan.id


def stored_plans(test_engine, user_id):
    with Session(test_engine) as session:
        return session.execute(
            select(WorkoutPlan.id, WorkoutPlan.status)
            .where(WorkoutPlan.user_id == user_id)
            .order_by(WorkoutPlan.id)
        ).all()


def test_a_rewrite_is_proposed_saving_nothing_and_its_approval_replaces_the_plan(
    client, use_provider, me, plan_id, ids, test_engine
):
    original = client.get(f"/users/{me}/workout-plans/{plan_id}").json()

    body, _ = ask(client, use_provider, me, *rewriting(ids, plan_id, *CORE_PLAN), message=REWRITE)

    shown = body["proposal"]
    assert shown["revision"] == {
        "replaces_plan_id": plan_id,
        "replaces_plan_name": "Core & Abs Focus",
        "kind": "ALTERNATIVE",
        "kept_exercises": list(CORE_PLAN),
        # three main exercises of 3 sets, each of 45 s and 90 s of rest: 3 x 3 x 135 s = 1215 s,
        # and no warm-up or cool-down
        "replaces_plan_estimated_minutes": 21,
    }
    assert shown["coverage"]["focus"] == "CORE"
    # proposed: nothing saved, nothing replaced
    assert stored_plans(test_engine, me) == [(plan_id, "PLANNED")]
    assert client.get(f"/users/{me}/workout-plans/{plan_id}").json() == original

    response = approve(client, me, shown)

    assert response.status_code == 201
    saved = response.json()
    assert (saved["name"], saved["status"]) == ("Core & Abs Focus (Alternative)", "PLANNED")
    assert [item["sets"] for item in saved["exercises"] if item["section"] == "MAIN_WORKOUT"] == [
        4,
        4,
        4,
    ]
    # the original is cancelled, never edited: what it prescribed is kept
    assert stored_plans(test_engine, me) == [(plan_id, "CANCELLED"), (saved["id"], "PLANNED")]
    cancelled = client.get(f"/users/{me}/workout-plans/{plan_id}").json()
    assert cancelled["exercises"] == original["exercises"]
    # reopening the saved plan reads what PostgreSQL holds
    assert client.get(f"/users/{me}/workout-plans/{saved['id']}").json() == saved
    # once: approving again saves nothing and replaces nothing, and returns the plan it saved
    again = approve(client, me, shown)
    assert (again.status_code, again.json()) == (200, saved)
    assert stored_plans(test_engine, me) == [(plan_id, "CANCELLED"), (saved["id"], "PLANNED")]


@pytest.mark.parametrize(
    "change",
    [
        {"name": "Core Day"},
        {"status": "CANCELLED"},
    ],
)
def test_a_revision_of_a_plan_changed_since_saves_nothing(
    client, use_provider, me, plan_id, ids, test_engine, change
):
    body, _ = ask(client, use_provider, me, *rewriting(ids, plan_id, *CORE_PLAN), message=REWRITE)
    shown = body["proposal"]
    assert client.patch(f"/users/{me}/workout-plans/{plan_id}", json=change).status_code == 200
    changed = client.get(f"/users/{me}/workout-plans/{plan_id}").json()

    response = approve(client, me, shown)

    assert (response.status_code, response.json()) == (409, {"detail": REPLACED_PLAN_CHANGED})
    assert stored_plans(test_engine, me) == [(plan_id, changed["status"])]
    assert client.get(f"/users/{me}/workout-plans/{plan_id}").json() == changed
    # and the proposal was not used up by the refusal
    with Session(test_engine) as session:
        assert session.get(WorkoutPlanProposal, shown["proposal_id"]).status == "PENDING"


def test_an_expired_or_another_users_revision_changes_no_plan(
    client, use_provider, users, me, plan_id, ids, test_engine, clock
):
    _, them = users
    body, _ = ask(client, use_provider, me, *rewriting(ids, plan_id, *CORE_PLAN), message=REWRITE)
    shown = body["proposal"]

    stranger = client.post(
        f"/coach/proposals/{shown['proposal_id']}/approve",
        headers=bearer(them),
        json={"binding": shown["binding"]},
    )
    assert stranger.status_code == 404
    clock.now += PROPOSAL_TTL + timedelta(seconds=1)
    expired = approve(client, me, shown)

    assert (expired.status_code, expired.json()) == (
        409,
        {"detail": "this proposal has expired: ask the coach for a new one"},
    )
    assert stored_plans(test_engine, me) == [(plan_id, "PLANNED")]
    assert stored_plans(test_engine, them) == []


def test_two_revisions_of_one_plan_approved_at_once_save_one_plan(
    client, use_provider, me, plan_id, ids, test_engine
):
    # two different revisions: the same one again would not be proposed twice
    shown = [
        ask(
            client, use_provider, me, *rewriting(ids, plan_id, *CORE_PLAN, sets=sets),
            message=REWRITE,
        )[0]["proposal"]
        for sets in (4, 3)
    ]  # fmt: skip
    start = threading.Barrier(2)
    statuses = []

    def approve_at_once(each_shown):
        # each its own client, as separate requests would be
        each = TestClient(app)
        start.wait()
        statuses.append(approve(each, me, each_shown).status_code)

    threads = [threading.Thread(target=approve_at_once, args=(item,)) for item in shown]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)

    assert sorted(statuses) == [201, 409]
    plans = stored_plans(test_engine, me)
    assert [status for _, status in plans] == ["CANCELLED", "PLANNED"]
    assert plans[0][0] == plan_id


def test_the_plan_revised_is_one_formiq_returned_in_the_turn(
    client, use_provider, me, plan_id, ids, test_engine
):
    """The coach finds the plan to rewrite in Formiq's data, read in the turn:
    a plan id it was not given (another plan of the user's, read in no tool
    result) is refused before the tools run, and only today's plan, which
    get_current_workout_plan returned, is revised."""
    with Session(test_engine) as session:
        later = core_plan(session, me, ids)
        later.scheduled_date = TODAY + timedelta(days=3)
        session.commit()
        later_id = later.id
    alternative = revision_of(plan_id, "ALTERNATIVE", ids, *CORE_PLAN, sets=4)
    turns = rewriting(ids, plan_id, *CORE_PLAN)

    body, provider = ask(
        client,
        use_provider,
        me,
        turns[0],
        tool_turn(proposal(**{**alternative, "revises_plan_id": later_id})),
        *turns[1:],
        # with two plans, the user says which: today's
        message="can you rewrite today's plan",
    )

    refused = received(provider, 2)["propose_workout_plan"]["error"]
    assert refused["code"] == "ID_NOT_GROUNDED"
    assert refused["message"].startswith(f"revises_plan_id={later_id}: neither the user nor")
    assert body["proposal"]["revision"]["replaces_plan_id"] == plan_id
    assert stored_plans(test_engine, me) == [(plan_id, "PLANNED"), (later_id, "PLANNED")]
