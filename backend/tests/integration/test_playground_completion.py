"""The playground's "Completed" button against the real API and PostgreSQL (the test
database, never the dev one).

The page's own code (playground/static/playground.js, P.logPlan) runs in Node, and
each request it makes is answered by the application's own API, through the test client,
with the access token the page would hold. So these tests show what the button does
with the real routes, schemas and rules: it logs a saved plan's workout as done,
exactly as prescribed, as a completed workout session; it logs it once; and a step that
fails leaves no running session behind.

A plan has no completed status (DRAFT, PLANNED, CANCELLED): it stays PLANNED. The
workout is done when a COMPLETED session of the plan says so. No test calls Gemini.
They require Node.js and the local PostgreSQL container.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorkoutPlan, WorkoutSession
from tests.auth import bearer
from tests.integration.test_coach_accepted_proposal_fallback import MESSAGE, claiming
from tests.integration.test_coach_follow_ups import ask
from tests.integration.test_plan_proposals import approve, proposing
from tests.integration.test_plan_revisions import (  # noqa: F401 (fixtures)
    CORE_PLAN,
    REWRITE,
    clock,
    core_plan,
    ids,
    me,
    plan_id,
    rewriting,
    stored_plans,
    terms,
    today,
    tools,
    use_provider,
    use_terms,
    users,
)

PLAYGROUND_JS = Path(__file__).resolve().parents[3] / "playground" / "static" / "playground.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")

# The page's logging, run in Node: each request goes to this test on stdout and its
# answer comes back on stdin, one JSON line each.
BRIDGE = """
const readline = require("node:readline");
const P = require(process.argv[1]);
const { token, plan } = JSON.parse(process.argv[2]);
const lines = readline.createInterface({ input: process.stdin })[Symbol.asyncIterator]();
async function call(method, path, body) {
  process.stdout.write(JSON.stringify({ method, path, body }) + "\\n");
  const { value } = await lines.next();
  return JSON.parse(value);
}
(async () => {
  const session = P.signIn(P.createSession(), "one@example.test", token);
  const result = await P.logPlan(session, plan, call);
  process.stdout.write(JSON.stringify({ done: result }) + "\\n");
  process.exit(0);
})();
"""


def press_completed(client, user_id, plan):
    """The button pressed on this saved plan, as the page holds it (the API's own JSON):
    the page's result, and the requests it made, each with the API's status."""
    headers = bearer(user_id)
    token = headers["Authorization"].removeprefix("Bearer ")
    node = subprocess.Popen(
        ["node", "-e", BRIDGE, str(PLAYGROUND_JS), json.dumps({"token": token, "plan": plan})],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    made, result = [], None
    try:
        for line in node.stdout:
            message = json.loads(line)
            if "done" in message:
                result = message["done"]
                break
            response = client.request(
                message["method"], message["path"], json=message.get("body"), headers=headers
            )
            made.append((message["method"], message["path"], response.status_code))
            data = response.json() if response.content else None
            node.stdin.write(json.dumps({"status": response.status_code, "data": data}) + "\n")
            node.stdin.flush()
    finally:
        node.stdin.close()
        node.wait(timeout=20)
    return result, made


@pytest.fixture
def saved_plan(client, use_provider, users, ids):
    """A saved plan of the first user with a warm-up and a cool-down (timed) and main
    exercises (sets of reps): the coach's proposal, approved by its user, read back as
    the page reads it."""
    user, _ = users
    body, _ = ask(client, use_provider, user, *claiming(proposing(ids)[:-1]), message=MESSAGE)
    saved = approve(client, user, body["proposal"])
    assert saved.status_code == 201
    plan = client.get(f"/users/{user}/workout-plans/{saved.json()['id']}", headers=bearer(user))
    assert plan.status_code == 200
    return user, plan.json()


def sessions_of(test_engine, user):
    with Session(test_engine) as session:
        rows = session.scalars(
            select(WorkoutSession).where(WorkoutSession.user_id == user).order_by(WorkoutSession.id)
        ).all()
        return [
            (
                row.id,
                row.status,
                row.workout_plan_id,
                [
                    (e.exercise_order, e.exercise_id, e.plan_exercise_id, [(s.set_number, s.reps, s.completed) for s in e.sets])
                    for e in row.exercises
                ],
            )
            for row in rows
        ]


def test_the_button_logs_the_plan_as_a_completed_session_exactly_as_prescribed(
    client, saved_plan, test_engine
):
    user, plan = saved_plan
    assert any(item["reps"] is None for item in plan["exercises"])  # the plan has timed activities
    assert any(item["reps"] for item in plan["exercises"])  # and sets of reps

    result, made = press_completed(client, user, plan)

    assert result["ok"] is True and result["already"] is False
    assert [status for _, _, status in made if status >= 400] == []
    (session,) = sessions_of(test_engine, user)
    assert session[1:3] == ("COMPLETED", plan["id"])
    # each exercise of the plan, in its order, linked to its plan exercise; every prescribed
    # set of reps done as prescribed; a timed activity is logged without sets
    ordered = sorted(plan["exercises"], key=lambda item: item["exercise_order"])
    assert session[3] == [
        (
            item["exercise_order"],
            item["exercise_id"],
            item["id"],
            [(n, item["reps"], True) for n in range(1, item["sets"] + 1)] if item["reps"] else [],
        )
        for item in ordered
    ]
    # the plan itself is as it was: a plan has no completed status
    with Session(test_engine) as db:
        assert db.get(WorkoutPlan, plan["id"]).status == "PLANNED"
    # only the signed-in user's own sessions were reached
    assert all(path.startswith(f"/users/{user}/workout-sessions") for _, path, _ in made)
    assert {method for method, _, _ in made} <= {"GET", "POST", "PATCH"}


def test_the_completed_workout_can_be_summarised_for_calories_and_recovery(client, saved_plan):
    user, plan = saved_plan
    result, _ = press_completed(client, user, plan)

    summary = client.post(
        f"/users/{user}/workout-sessions/{result['sessionId']}/recovery-summary",
        headers=bearer(user),
    )

    # what the logged session is for: Formiq's recovery summary reads a COMPLETED session
    assert summary.status_code == 200, summary.text


def test_pressing_it_again_logs_nothing_more(client, saved_plan, test_engine):
    user, plan = saved_plan
    first, _ = press_completed(client, user, plan)

    again, made = press_completed(client, user, plan)

    assert again == {"ok": True, "sessionId": first["sessionId"], "already": True}
    assert [method for method, _, _ in made] == ["GET"]
    assert len(sessions_of(test_engine, user)) == 1


def test_a_step_that_fails_leaves_no_running_session_behind(client, saved_plan, test_engine):
    user, plan = saved_plan
    broken = json.loads(json.dumps(plan))
    # a catalog exercise that does not exist: the API refuses it after the session was started
    broken["exercises"][-1]["exercise_id"] = 2_000_000

    result, made = press_completed(client, user, broken)

    assert result["ok"] is False and result["cleaned"] is True
    assert result["status"] in (400, 404)
    assert made[-1][0] == "DELETE"
    # nothing of the attempt is kept, so the user's next workout is not blocked
    assert sessions_of(test_engine, user) == []
    again, _ = press_completed(client, user, plan)
    assert again["ok"] is True


def test_a_workout_already_in_progress_is_not_disturbed(client, saved_plan, test_engine):
    user, plan = saved_plan
    started = client.post(f"/users/{user}/workout-sessions", json={}, headers=bearer(user))
    assert started.status_code == 201

    result, made = press_completed(client, user, plan)

    assert result == {"ok": False, "step": "start the session", "status": 409, "cleaned": True}
    assert [method for method, _, _ in made] == ["GET", "POST"]  # nothing deleted: none was started
    assert [(row[0], row[1]) for row in sessions_of(test_engine, user)] == [
        (started.json()["id"], "IN_PROGRESS")
    ]
