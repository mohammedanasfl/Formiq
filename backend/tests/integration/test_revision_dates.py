"""A revision keeps the day of the plan it revises (Phase 2.3).

The Phase 2.2 live pass found every revision proposed for Formiq's UTC "today", whatever
day the saved plan was for: editing Friday's workout moved it to today, and for a user
whose time zone is not UTC the applied plan could leave Home. Now a revision of a saved
plan keeps its day unless the user asked to move it:

- the day is the plan's own, whether it is before today in UTC (the user's day is behind
  it), after the 14 days a new workout may be planned for, or today;
- another day is accepted only when the user named one (app.tools.schedule), is within
  the usual window, and is shown as a change: the proposal's day, its comparison with the
  plan (`scheduled_date_changed`, the plan's own day) and the plan its approval saves
  agree;
- a refinement of a proposal that already moved the workout carries the day on;
- a plan with no day has none to keep: the model must give one;
- a new workout is as it was: today, or a day within the window.

The model is scripted: no test calls Gemini. They require the local PostgreSQL container
to be running.
"""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.models import WorkoutPlan
from tests.auth import bearer
from tests.coach import call, respond_turn, tool_turn
from tests.integration.test_coach_daily import TODAY, received, recommend
from tests.integration.test_coach_follow_ups import tools_in
from tests.integration.test_coach_target import ask, new_workout, reads, stored_proposals
from tests.integration.test_plan_proposals import approve, problem, proposal, propose
from tests.integration.test_plan_revisions import (  # noqa: F401 (fixtures)
    CORE_PLAN,
    clock,
    core_plan,
    ids,
    me,
    revision_of,
    saved_as_proposed,
    terms,
    today,
    tools,
    use_provider,
    use_terms,
    users,
)
from tests.integration.workout_plans import add_user

HARDER = "Make it a little harder."
REPLY = "Here is another version of your core workout. Approving it replaces the plan."
WINDOW = "scheduled_date must be today or up to 14 days later"


def day(offset):
    return TODAY + timedelta(days=offset)


def plan_on(session, user_id, ids, offset):
    """A PLANNED core plan for `offset` days from today in UTC, committed: its id."""
    plan = core_plan(session, user_id, ids)
    plan.scheduled_date = day(offset)
    session.commit()
    return plan.id


def adjust(plan_id, ids, sets=2, **fields):
    return revision_of(plan_id, "ADJUST", ids, *CORE_PLAN, sets=sets, **fields)


# --- the proposal tool ---


@pytest.mark.parametrize(
    "offset",
    [-1, -6, 0, 3, 14, 40],
    ids=[
        "a day before UTC today (the user's day is behind it)",
        "overdue",
        "today",
        "three days ahead",
        "the last day of the window",
        "beyond the window",
    ],
)
def test_a_revision_keeps_the_day_of_its_plan(tools, db_session, ids, offset):
    user = add_user(db_session, "dates@example.com")
    plan = core_plan(db_session, user.id, ids)
    plan.scheduled_date = day(offset)
    db_session.flush()
    tools_in(tools, ("user", HARDER))

    result = propose(tools, user, **adjust(plan.id, ids))

    output = result["output"]
    assert output["scheduled_date"] == day(offset).isoformat()
    assert output["days_from_today"] == offset
    # what is kept for the approval is the same day
    (kept, _) = tools.proposals[0]
    assert kept.values()["scheduled_date"] == day(offset).isoformat()


def test_a_new_workout_is_still_for_today_unless_it_gives_a_day(tools, db_session, ids):
    user = add_user(db_session, "dates@example.com")
    tools_in(tools, ("user", "Give me something else."))

    today_ = propose(tools, user, **new_workout(ids))
    later = propose(tools, user, **{**new_workout(ids), "scheduled_date": day(2).isoformat()})

    assert today_["output"]["scheduled_date"] == TODAY.isoformat()
    # a new workout names its day without the user's words, as before
    assert later["output"]["scheduled_date"] == day(2).isoformat()
    assert WINDOW in problem(
        propose(tools, user, **{**new_workout(ids), "scheduled_date": day(15).isoformat()})
    )
    assert WINDOW in problem(
        propose(tools, user, **{**new_workout(ids), "scheduled_date": day(-1).isoformat()})
    )


def test_a_revision_may_not_move_its_plan_when_the_user_named_no_day(tools, db_session, ids):
    user = add_user(db_session, "dates@example.com")
    plan = core_plan(db_session, user.id, ids)
    plan.scheduled_date = day(3)
    db_session.flush()
    tools_in(tools, ("user", HARDER))

    # the model's habit: today, the tool's old default
    refused = propose(tools, user, **adjust(plan.id, ids, scheduled_date=TODAY.isoformat()))

    assert problem(refused) == (
        f"the user did not name a day to move workout plan {plan.id} to, and it is for "
        f"{day(3).isoformat()}: leave scheduled_date out and the revision keeps that day; give "
        "another day only when the user asked for one, and ask them (ASK_CLARIFICATION) when "
        "it is unclear"
    )
    assert tools.proposals == []


def test_a_revision_may_move_its_plan_when_the_user_named_a_day(tools, db_session, ids):
    user = add_user(db_session, "dates@example.com")
    plan, same = unchanged_plan(db_session, user.id, ids, 3)
    tools_in(tools, ("user", HARDER), ("coach", "Done."), ("user", "Can you move it to tomorrow?"))

    # only the day: the newest message asks for nothing else, and a move that also changed the
    # exercises would be refused (test_date_contract: a date-only move keeps what the plan holds)
    result = propose(tools, user, **same, scheduled_date=day(1).isoformat())

    assert result["output"]["scheduled_date"] == day(1).isoformat()
    assert result["output"]["days_from_today"] == 1


def test_a_day_the_coach_said_is_not_a_day_the_user_named(tools, db_session, ids):
    user = add_user(db_session, "dates@example.com")
    plan = core_plan(db_session, user.id, ids)
    plan.scheduled_date = day(3)
    db_session.flush()
    # only the coach's turn names a day: the client's word for what the coach said
    tools_in(tools, ("coach", "I can move it to tomorrow."), ("user", HARDER))

    refused = propose(tools, user, **adjust(plan.id, ids, scheduled_date=day(1).isoformat()))

    assert "did not name a day" in problem(refused)


def test_giving_the_plans_own_day_moves_nothing_and_needs_no_words(tools, db_session, ids):
    user = add_user(db_session, "dates@example.com")
    plan = core_plan(db_session, user.id, ids)
    plan.scheduled_date = day(3)
    db_session.flush()
    tools_in(tools, ("user", HARDER))

    result = propose(tools, user, **adjust(plan.id, ids, scheduled_date=day(3).isoformat()))

    assert result["output"]["scheduled_date"] == day(3).isoformat()


@pytest.mark.parametrize("offset", [-1, 15, 40])
def test_a_move_is_held_to_the_window_whatever_the_user_said(tools, db_session, ids, offset):
    user = add_user(db_session, "dates@example.com")
    plan = core_plan(db_session, user.id, ids)
    plan.scheduled_date = day(3)
    db_session.flush()
    tools_in(tools, ("user", f"Move it to {day(offset).isoformat()}"))

    refused = propose(tools, user, **adjust(plan.id, ids, scheduled_date=day(offset).isoformat()))

    assert problem(refused) == WINDOW
    assert tools.proposals == []


def test_the_day_is_not_checked_without_a_conversation_it_is_refused(tools, db_session, ids):
    """Fail closed: with no conversation there are no words to rest a move on."""
    user = add_user(db_session, "dates@example.com")
    plan = core_plan(db_session, user.id, ids)
    plan.scheduled_date = day(3)
    db_session.flush()
    tools.conversation = None
    tools.user_words = None

    moved = propose(tools, user, **adjust(plan.id, ids, scheduled_date=day(1).isoformat()))
    kept = propose(tools, user, **adjust(plan.id, ids))

    assert "did not name a day" in problem(moved)
    assert kept["output"]["scheduled_date"] == day(3).isoformat()


def test_a_plan_with_no_day_has_none_to_keep(tools, db_session, ids):
    user = add_user(db_session, "dates@example.com")
    plan = core_plan(db_session, user.id, ids)
    # not a plan the service would save as PLANNED, but a row the database allows
    plan.scheduled_date = None
    db_session.flush()
    tools_in(tools, ("user", HARDER))

    refused = propose(tools, user, **adjust(plan.id, ids))
    given = propose(tools, user, **adjust(plan.id, ids, scheduled_date=day(2).isoformat()))
    late = propose(tools, user, **adjust(plan.id, ids, scheduled_date=day(20).isoformat()))

    assert problem(refused) == (
        f"workout plan {plan.id} has no day to keep: give scheduled_date, today or up to 14 days "
        "later (ask the user which day when it is unclear)"
    )
    # nothing is moved, so no word of the user's is needed for the day it is given
    assert given["output"]["scheduled_date"] == day(2).isoformat()
    assert problem(late) == WINDOW


# --- through the coach and the API ---


def revising_for(ids, plan_id, **fields):
    return (
        reads(),
        tool_turn(proposal(**adjust(plan_id, ids, **fields))),
        recommend(REPLY),
    )


def test_a_revision_shown_saved_and_compared_agrees_on_the_day(
    client, use_provider, me, ids, test_engine
):
    with Session(test_engine) as session:
        plan_id = plan_on(session, me, ids, 2)

    response, _ = ask(
        client, use_provider, me, *revising_for(ids, plan_id), workout_plan_id=plan_id
    )

    assert response.status_code == 200, response.json()
    shown = response.json()["proposal"]
    assert shown["scheduled_date"] == day(2).isoformat()
    assert shown["changes"]["scheduled_date_changed"] is False
    assert shown["changes"]["compared_with_scheduled_date"] == day(2).isoformat()
    (stored,) = stored_proposals(test_engine, me)
    assert stored["scheduled_date"] == day(2).isoformat()
    # as it is listed after a restart
    listed = client.get("/coach/proposals/pending", headers=bearer(me)).json()["proposals"]
    assert [item["scheduled_date"] for item in listed] == [day(2).isoformat()]
    assert listed[0]["changes"]["scheduled_date_changed"] is False

    saved = approve(client, me, shown)

    assert saved.status_code == 201
    assert saved.json()["scheduled_date"] == day(2).isoformat()
    # the plan it replaced keeps its own day, cancelled
    original = client.get(f"/users/{me}/workout-plans/{plan_id}").json()
    assert (original["status"], original["scheduled_date"]) == ("CANCELLED", day(2).isoformat())
    # and the plan is found on its day, as a device that reads Home by its own date does
    on_day = client.get(
        f"/users/{me}/workout-plans?scheduled_date={day(2).isoformat()}&status=PLANNED"
    ).json()
    assert [item["id"] for item in on_day] == [saved.json()["id"]]


def test_a_device_a_day_behind_utc_finds_the_revised_plan_on_its_own_day(
    client, use_provider, me, ids, test_engine
):
    """It is the 14th in Los Angeles in the evening and already the 15th in UTC: the plan
    is for the 14th, and a revision of it was proposed for the 15th, so Home (read by the
    device's date) no longer found it. The workout is not moved."""
    with Session(test_engine) as session:
        plan_id = plan_on(session, me, ids, -1)

    response, _ = ask(
        client, use_provider, me, *revising_for(ids, plan_id), workout_plan_id=plan_id
    )

    shown = response.json()["proposal"]
    assert shown["scheduled_date"] == day(-1).isoformat()
    saved = approve(client, me, shown).json()
    assert saved["scheduled_date"] == day(-1).isoformat()
    behind = client.get(
        f"/users/{me}/workout-plans?scheduled_date={day(-1).isoformat()}&status=PLANNED"
    ).json()
    assert [item["id"] for item in behind] == [saved["id"]]
    assert (
        client.get(
            f"/users/{me}/workout-plans?scheduled_date={TODAY.isoformat()}&status=PLANNED"
        ).json()
        == []
    )


def test_a_device_a_day_ahead_of_utc_keeps_its_plan_too(client, use_provider, me, ids, test_engine):
    with Session(test_engine) as session:
        plan_id = plan_on(session, me, ids, 1)

    response, _ = ask(
        client, use_provider, me, *revising_for(ids, plan_id), workout_plan_id=plan_id
    )

    shown = response.json()["proposal"]
    assert shown["scheduled_date"] == day(1).isoformat()
    assert approve(client, me, shown).json()["scheduled_date"] == day(1).isoformat()


def test_a_move_the_user_asked_for_is_shown_as_a_change_and_saved_on_the_new_day(
    client, use_provider, me, ids, test_engine
):
    with Session(test_engine) as session:
        plan_id = plan_on(session, me, ids, 3)

    response, _ = ask(
        client,
        use_provider,
        me,
        *revising_for(ids, plan_id, scheduled_date=day(1).isoformat()),
        message="Make it a little harder and move it to tomorrow.",
        workout_plan_id=plan_id,
    )

    assert response.status_code == 200, response.json()
    shown = response.json()["proposal"]
    assert shown["scheduled_date"] == day(1).isoformat()
    # the comparison names the plan's own day, so the change is not guessed at
    assert shown["changes"]["scheduled_date_changed"] is True
    assert shown["changes"]["compared_with_scheduled_date"] == day(3).isoformat()
    saved = approve(client, me, shown).json()
    assert saved["scheduled_date"] == day(1).isoformat()
    original = client.get(f"/users/{me}/workout-plans/{plan_id}").json()
    assert (original["status"], original["scheduled_date"]) == ("CANCELLED", day(3).isoformat())


def test_a_model_that_moves_the_plan_unasked_is_corrected_within_the_turn(
    client, use_provider, me, ids, test_engine
):
    with Session(test_engine) as session:
        plan_id = plan_on(session, me, ids, 3)

    response, provider = ask(
        client,
        use_provider,
        me,
        reads(),
        # today, because the old default said so
        tool_turn(proposal(**adjust(plan_id, ids, scheduled_date=TODAY.isoformat()))),
        tool_turn(proposal(**adjust(plan_id, ids))),
        recommend(REPLY),
        workout_plan_id=plan_id,
    )

    assert response.status_code == 200, response.json()
    refused = received(provider, 2)["propose_workout_plan"]["error"]
    assert refused["code"] == "INVALID_INPUT"
    assert "did not name a day" in refused["message"]
    assert response.json()["proposal"]["scheduled_date"] == day(3).isoformat()
    assert [item["scheduled_date"] for item in stored_proposals(test_engine, me)] == [
        day(3).isoformat()
    ]


def test_a_refinement_of_a_proposal_that_moved_the_workout_carries_the_day_on(
    client, use_provider, me, ids, test_engine
):
    with Session(test_engine) as session:
        plan_id = plan_on(session, me, ids, 3)
    moved = day(1).isoformat()
    first, _ = ask(
        client,
        use_provider,
        me,
        *revising_for(ids, plan_id, scheduled_date=moved),
        message="Make it a little harder and move it to tomorrow.",
        workout_plan_id=plan_id,
    )
    assert first.json()["proposal"]["scheduled_date"] == moved

    # the user says nothing of a day now, and the model repeats the proposal's own
    second, _ = ask(
        client,
        use_provider,
        me,
        reads(),
        tool_turn(
            proposal(**adjust(plan_id, ids, sets=4, scheduled_date=moved, name="Harder Core"))
        ),
        recommend(REPLY),
        message="Make it even harder.",
        workout_plan_id=plan_id,
    )

    assert second.status_code == 200, second.json()
    assert second.json()["proposal"]["scheduled_date"] == moved


def test_a_day_that_was_never_asked_for_is_not_carried_on_by_an_expired_proposal(
    client, use_provider, me, ids, test_engine, clock
):
    with Session(test_engine) as session:
        plan_id = plan_on(session, me, ids, 3)
    moved = day(1).isoformat()
    ask(
        client,
        use_provider,
        me,
        *revising_for(ids, plan_id, scheduled_date=moved),
        message="Make it a little harder and move it to tomorrow.",
        workout_plan_id=plan_id,
    )
    clock.now += timedelta(minutes=31)

    response, provider = ask(
        client,
        use_provider,
        me,
        reads(),
        tool_turn(
            proposal(**adjust(plan_id, ids, sets=4, scheduled_date=moved, name="Harder Core"))
        ),
        tool_turn(proposal(**adjust(plan_id, ids, sets=4, name="Harder Core"))),
        recommend(REPLY),
        message="Make it even harder.",
        workout_plan_id=plan_id,
    )

    assert "did not name a day" in received(provider, 2)["propose_workout_plan"]["error"]["message"]
    assert response.json()["proposal"]["scheduled_date"] == day(3).isoformat()


def test_the_revision_cannot_move_another_users_plan_by_naming_a_day(
    client, use_provider, users, ids, test_engine
):
    me, them = users
    with Session(test_engine) as session:
        theirs = plan_on(session, them, ids, 3)

    response, provider = ask(
        client,
        use_provider,
        me,
        reads(),
        tool_turn(proposal(**adjust(theirs, ids, scheduled_date=day(1).isoformat()))),
        respond_turn("I could not change that workout.", "WORKOUT_PLAN", "CANNOT_ANSWER"),
        message="Move it to tomorrow",
    )

    # the plan is not told apart from a missing one, and nothing of theirs changed
    assert received(provider, 2)["propose_workout_plan"]["error"]["code"] in (
        "RESOURCE_NOT_FOUND",
        "ID_NOT_GROUNDED",
    )
    with Session(test_engine) as session:
        assert session.get(WorkoutPlan, theirs).scheduled_date == day(3)


# --- Phase 2.5: moving a workout is a change on its own ---
#
# An ADJUST that prescribed what the plan does was refused as "unchanged" whatever day it
# was for, so "move it to Friday" (the same workout, another day) could not be proposed
# (Phase 2.4 live pass). The day is part of what a revision changes: a proposal that moves
# the workout is a revision, and one that does not is still unchanged.


def unchanged_plan(session, user_id, ids, offset):
    """A PLANNED plan on offset days from today, and the arguments of a proposal that
    prescribes exactly what it does: its sections, sets, reps, rest, weights (none) and name."""
    as_saved = revision_of(None, "ADJUST", ids, *CORE_PLAN)
    plan = saved_as_proposed(session, user_id, as_saved)
    plan.scheduled_date = day(offset)
    session.flush()
    return plan, {**as_saved, "revises_plan_id": plan.id}


def test_a_date_only_move_is_a_revision(tools, db_session, ids):
    user = add_user(db_session, "moves@example.com")
    plan, same = unchanged_plan(db_session, user.id, ids, 3)
    tools_in(tools, ("user", "Move it to tomorrow."))

    result = propose(tools, user, **same, scheduled_date=day(1).isoformat())

    output = result["output"]
    assert (output["scheduled_date"], output["days_from_today"]) == (day(1).isoformat(), 1)
    assert output["revision"]["kind"] == "ADJUST"
    assert output["revision"]["replaces_plan_id"] == plan.id
    # nothing else differs: the same exercises, every one kept
    assert output["revision"]["kept_exercises"] == list(CORE_PLAN)
    (kept, _) = tools.proposals[0]
    assert kept.values()["scheduled_date"] == day(1).isoformat()


def test_the_same_workout_on_its_own_day_is_still_unchanged(tools, db_session, ids):
    user = add_user(db_session, "moves@example.com")
    plan, same = unchanged_plan(db_session, user.id, ids, 3)
    tools_in(tools, ("user", "Make it a little harder."))

    left_out = propose(tools, user, **same)

    assert problem(left_out) == (
        f"this is workout plan {plan.id} unchanged, on its own day {day(3).isoformat()}: make "
        "the changes the user asked for. To move it to another day, give scheduled_date for the "
        "day they named; when they did not name a day, ask which (ASK_CLARIFICATION) and do not "
        "choose one"
    )
    assert tools.proposals == []


def test_a_move_to_the_day_the_plan_is_already_on_is_unchanged_and_says_so(
    tools, db_session, ids
):
    user = add_user(db_session, "moves@example.com")
    plan, same = unchanged_plan(db_session, user.id, ids, 3)
    tools_in(tools, ("user", f"Move it to {day(3).isoformat()}."))

    refused = propose(tools, user, **same, scheduled_date=day(3).isoformat())

    assert problem(refused) == (
        f"workout plan {plan.id} is already planned for {day(3).isoformat()} and this proposal "
        "changes nothing else: it is unchanged. Do not propose it again; tell the user it is "
        "already on that day"
    )
    assert tools.proposals == []


@pytest.mark.parametrize("offset", [0, 1, 14], ids=["today", "tomorrow", "the last day of the window"])
def test_a_move_within_the_window_is_accepted(tools, db_session, ids, offset):
    user = add_user(db_session, "moves@example.com")
    plan, same = unchanged_plan(db_session, user.id, ids, 3)
    tools_in(tools, ("user", f"Move it to {day(offset).isoformat()}"))

    result = propose(tools, user, **same, scheduled_date=day(offset).isoformat())

    assert result["output"]["scheduled_date"] == day(offset).isoformat()
    assert result["output"]["days_from_today"] == offset


@pytest.mark.parametrize("offset", [-1, 15, 40], ids=["the day before today", "past the window", "far"])
def test_a_move_outside_the_window_is_refused_even_when_it_is_the_only_change(
    tools, db_session, ids, offset
):
    user = add_user(db_session, "moves@example.com")
    plan, same = unchanged_plan(db_session, user.id, ids, 3)
    tools_in(tools, ("user", f"Move it to {day(offset).isoformat()}"))

    refused = propose(tools, user, **same, scheduled_date=day(offset).isoformat())

    assert problem(refused) == WINDOW
    assert tools.proposals == []


def test_a_move_the_user_did_not_name_a_day_for_is_refused_whatever_else_is_the_same(
    tools, db_session, ids
):
    """"Reschedule it" names no day: the model may not pick one, and the refusal tells it to
    ask. A day the model chose is no move."""
    user = add_user(db_session, "moves@example.com")
    plan, same = unchanged_plan(db_session, user.id, ids, 3)
    tools_in(tools, ("user", "Can you reschedule it?"))

    chosen = propose(tools, user, **same, scheduled_date=day(1).isoformat())
    nothing = propose(tools, user, **same)

    assert "did not name a day" in problem(chosen)
    assert "ask them (ASK_CLARIFICATION)" in problem(chosen)
    assert "when they did not name a day, ask which (ASK_CLARIFICATION)" in problem(nothing)
    assert tools.proposals == []


@pytest.mark.parametrize("given", ["next Friday", "2026-13-40", "tomorrow", ""])
def test_a_day_that_is_not_a_date_is_refused(tools, db_session, ids, given):
    user = add_user(db_session, "moves@example.com")
    plan, same = unchanged_plan(db_session, user.id, ids, 3)
    tools_in(tools, ("user", "Move it to tomorrow."))

    refused = propose(tools, user, **same, scheduled_date=given)

    assert "scheduled_date" in problem(refused)
    assert tools.proposals == []


def test_a_moved_workout_that_is_also_changed_is_one_revision(tools, db_session, ids):
    user = add_user(db_session, "moves@example.com")
    plan, same = unchanged_plan(db_session, user.id, ids, 3)
    tools_in(tools, ("user", "Make it harder and move it to tomorrow."))
    harder = revision_of(plan.id, "ADJUST", ids, *CORE_PLAN, sets=4)

    result = propose(tools, user, **harder, scheduled_date=day(1).isoformat())

    assert result["output"]["scheduled_date"] == day(1).isoformat()


def moving(ids, plan_id, offset, **fields):
    """A model asked to move a plan to another day: it reads, proposes the same workout for
    the day, and replies."""
    return (
        reads(),
        tool_turn(
            proposal(
                **{
                    **revision_of(None, "ADJUST", ids, *CORE_PLAN),
                    "revises_plan_id": plan_id,
                    "scheduled_date": day(offset).isoformat(),
                    **fields,
                }
            )
        ),
        recommend("Here is the same workout on the new day. Approving it in Formiq replaces the plan."),
    )


@pytest.fixture
def unchanged_plan_id(me, ids, test_engine):
    with Session(test_engine) as session:
        plan, _ = unchanged_plan(session, me, ids, 3)
        session.commit()
        return plan.id


def test_a_date_only_move_through_the_api_is_shown_pending_and_saved_on_the_same_day(
    client, use_provider, me, ids, test_engine, unchanged_plan_id
):
    response, _ = ask(
        client,
        use_provider,
        me,
        *moving(ids, unchanged_plan_id, 1),
        message="Move it to tomorrow.",
        workout_plan_id=unchanged_plan_id,
    )

    assert response.status_code == 200, response.json()
    shown = response.json()["proposal"]
    assert shown["scheduled_date"] == day(1).isoformat()
    changes = shown["changes"]
    # only the day differs, and every figure agrees on it
    assert (changes["added"], changes["removed"], changes["changed"]) == ([], [], [])
    assert changes["unchanged"] == ["Brisk Walk", *CORE_PLAN, "Brisk Walk"]
    assert changes["scheduled_date_changed"] is True
    assert changes["compared_with_scheduled_date"] == day(3).isoformat()
    assert changes["name_changed"] is False
    (stored,) = stored_proposals(test_engine, me)
    assert stored["scheduled_date"] == day(1).isoformat()
    # as it is listed after a restart, from the stored values
    (listed,) = client.get("/coach/proposals/pending", headers=bearer(me)).json()["proposals"]
    assert listed["scheduled_date"] == day(1).isoformat()
    assert listed["changes"] == changes

    saved = approve(client, me, shown)

    # what the approval saves is exactly the day that was proposed
    assert saved.status_code == 201
    assert saved.json()["scheduled_date"] == day(1).isoformat()
    original = client.get(f"/users/{me}/workout-plans/{unchanged_plan_id}").json()
    assert (original["status"], original["scheduled_date"]) == ("CANCELLED", day(3).isoformat())
    planned = client.get(f"/users/{me}/workout-plans?status=PLANNED").json()
    assert [(item["id"], item["scheduled_date"]) for item in planned] == [
        (saved.json()["id"], day(1).isoformat())
    ]
    # and once approved, the proposal no longer waits
    assert client.get("/coach/proposals/pending", headers=bearer(me)).json() == {"proposals": []}


def test_the_coach_reads_a_date_only_move_back_as_a_move(
    client, use_provider, me, ids, test_engine, unchanged_plan_id
):
    ask(
        client,
        use_provider,
        me,
        *moving(ids, unchanged_plan_id, 1),
        message="Move it to tomorrow.",
        workout_plan_id=unchanged_plan_id,
    )

    _, provider = ask(
        client,
        use_provider,
        me,
        tool_turn(call("get_pending_proposal")),
        respond_turn("Yes: it is the same workout, on tomorrow instead.", "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        message="What did you propose?",
        workout_plan_id=unchanged_plan_id,
    )

    told = received(provider, 1)["get_pending_proposal"]["output"]
    assert told["scheduled_date"] == day(1).isoformat()
    assert told["changes"]["scheduled_date_changed"] is True
    assert (told["changes"]["added"], told["changes"]["removed"], told["changes"]["changed"]) == (
        [],
        [],
        [],
    )
    assert told["replaced_plan_unchanged"] is True


def test_a_refinement_of_a_date_only_move_carries_the_move_on_and_shows_both_changes(
    client, use_provider, me, ids, test_engine, unchanged_plan_id
):
    moved = day(1).isoformat()
    first, _ = ask(
        client,
        use_provider,
        me,
        *moving(ids, unchanged_plan_id, 1),
        message="Move it to tomorrow.",
        workout_plan_id=unchanged_plan_id,
    )
    assert first.json()["proposal"]["scheduled_date"] == moved

    # the user says nothing of a day now; the model repeats the proposal's own day
    second, _ = ask(
        client,
        use_provider,
        me,
        reads(),
        tool_turn(
            proposal(
                **{
                    **revision_of(unchanged_plan_id, "ADJUST", ids, *CORE_PLAN, sets=4),
                    "scheduled_date": moved,
                }
            )
        ),
        recommend(REPLY),
        message="Make it a little harder.",
        workout_plan_id=unchanged_plan_id,
    )

    assert second.status_code == 200, second.json()
    changes = second.json()["proposal"]["changes"]
    assert second.json()["proposal"]["scheduled_date"] == moved
    assert changes["scheduled_date_changed"] is True
    assert changes["compared_with_scheduled_date"] == day(3).isoformat()
    assert [item["exercise_name"] for item in changes["changed"]] == list(CORE_PLAN)


def test_a_date_only_request_for_the_day_the_plan_is_on_proposes_nothing(
    client, use_provider, me, ids, test_engine, unchanged_plan_id
):
    response, provider = ask(
        client,
        use_provider,
        me,
        reads(),
        tool_turn(
            proposal(
                **{
                    **revision_of(None, "ADJUST", ids, *CORE_PLAN),
                    "revises_plan_id": unchanged_plan_id,
                    "scheduled_date": day(3).isoformat(),
                }
            )
        ),
        respond_turn(
            "It is already planned for that day, so there is nothing to move.",
            "WORKOUT_PLAN",
            "CANNOT_ANSWER",
        ),
        message=f"Move it to {day(3).isoformat()}.",
        workout_plan_id=unchanged_plan_id,
    )

    assert response.status_code == 200, response.json()
    assert response.json().get("proposal") is None
    assert "already planned for" in received(provider, 2)["propose_workout_plan"]["error"]["message"]
    assert stored_proposals(test_engine, me) == []
    plan = client.get(f"/users/{me}/workout-plans/{unchanged_plan_id}").json()
    assert (plan["status"], plan["scheduled_date"]) == ("PLANNED", day(3).isoformat())
