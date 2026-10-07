"""Integration tests for the workout session API routes.

They require the local PostgreSQL container to be running. The client fixture
sends every request to the test database and empties the user, workout plan
and workout session tables before and after each test.
"""

from datetime import datetime

import pytest

from app.schemas import WorkoutSessionExerciseResponse, WorkoutSessionResponse, WorkoutSetResponse
from tests.integration.workout_plans import retire_exercise

DATE = "2026-10-10"


@pytest.fixture
def user_id(client):
    return client.post("/users", json={"email": "session-api@example.com"}).json()["id"]


@pytest.fixture
def other_user_id(client):
    return client.post("/users", json={"email": "session-api-other@example.com"}).json()["id"]


@pytest.fixture
def bench_press(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Bench Press"]


@pytest.fixture
def squat(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Back Squat"]


def sessions_url(user_id, session_id=None, session_exercise_id=None, set_id=None):
    url = f"/users/{user_id}/workout-sessions"
    if session_id is not None:
        url += f"/{session_id}"
    if session_exercise_id is not None:
        url += f"/exercises/{session_exercise_id}"
        if set_id is not None:
            url += f"/sets/{set_id}"
    return url


def exercises_url(user_id, session_id):
    return f"{sessions_url(user_id, session_id)}/exercises"


def sets_url(user_id, session_id, session_exercise_id):
    return f"{sessions_url(user_id, session_id, session_exercise_id)}/sets"


@pytest.fixture
def make_plan(client, user_id, bench_press):
    """Creates a plan through the API, PLANNED by default, with a bench press at
    exercise_order 1."""

    def make(owner=None, *, status="PLANNED"):
        body = {
            "name": "Push Day",
            "status": status,
            "scheduled_date": DATE,
            "exercises": [{"exercise_id": bench_press, "exercise_order": 1, "sets": 3, "reps": 8}],
        }
        response = client.post(f"/users/{owner or user_id}/workout-plans", json=body)
        assert response.status_code == 201, response.json()
        return response.json()

    return make


@pytest.fixture
def make_session(client, user_id, bench_press):
    """Creates a session through the API in the given status, by default with a
    bench press at exercise_order 1 with set 1 (8 reps at 50 kg). Returns the
    session as GET returns it."""

    def make(status="IN_PROGRESS", *, owner=None, workout_plan_id=None, with_exercise=True):
        owner = owner or user_id
        response = client.post(sessions_url(owner), json={"workout_plan_id": workout_plan_id})
        assert response.status_code == 201, response.json()
        session_id = response.json()["id"]
        if with_exercise:
            session_exercise = client.post(
                exercises_url(owner, session_id),
                json={"exercise_id": bench_press, "exercise_order": 1},
            ).json()
            client.post(
                sets_url(owner, session_id, session_exercise["id"]),
                json={"set_number": 1, "reps": 8, "weight_kg": 50},
            )
        if status != "IN_PROGRESS":
            client.patch(sessions_url(owner, session_id), json={"status": status})
        return client.get(sessions_url(owner, session_id)).json()

    return make


# POST /users/{user_id}/workout-sessions


def test_create_manual_session_returns_201_and_the_session(client, user_id):
    response = client.post(sessions_url(user_id), json={"notes": "Quick one"})

    assert response.status_code == 201
    created = response.json()
    assert set(created) == set(WorkoutSessionResponse.model_fields)
    assert {
        key: created[key]
        for key in ["user_id", "workout_plan_id", "status", "completed_at", "notes", "exercises"]
    } == {
        "user_id": user_id,
        "workout_plan_id": None,
        "status": "IN_PROGRESS",
        "completed_at": None,
        "notes": "Quick one",
        "exercises": [],
    }
    assert created["started_at"] == created["created_at"]
    assert client.get(sessions_url(user_id, created["id"])).json() == created


def test_create_session_from_a_plan_returns_201(client, user_id, make_plan):
    plan = make_plan()

    response = client.post(sessions_url(user_id), json={"workout_plan_id": plan["id"]})

    assert response.status_code == 201
    assert response.json()["workout_plan_id"] == plan["id"]


def test_create_session_ignores_client_status_timestamps_and_owner(client, user_id, other_user_id):
    response = client.post(
        sessions_url(user_id),
        json={
            "status": "COMPLETED",
            "started_at": "2000-01-01T00:00:00Z",
            "completed_at": "2000-01-01T01:00:00Z",
            "user_id": other_user_id,
            "id": 999_999,
        },
    )

    assert response.status_code == 201
    created = response.json()
    assert (created["status"], created["completed_at"], created["user_id"]) == (
        "IN_PROGRESS",
        None,
        user_id,
    )
    assert datetime.fromisoformat(created["started_at"]).year > 2000
    assert client.get(sessions_url(other_user_id)).json() == []


@pytest.mark.parametrize("plan_owner", ["other user", "missing"])
def test_create_session_from_a_plan_the_user_does_not_have_returns_400(
    client, user_id, other_user_id, make_plan, plan_owner
):
    plan_id = make_plan(owner=other_user_id)["id"] if plan_owner == "other user" else 2_147_483_647

    response = client.post(sessions_url(user_id), json={"workout_plan_id": plan_id})

    assert response.status_code == 400
    assert response.json() == {"detail": f"user {user_id} has no workout plan {plan_id}"}
    assert client.get(sessions_url(user_id)).json() == []


@pytest.mark.parametrize("plan_status", ["DRAFT", "CANCELLED"])
def test_create_session_from_a_plan_that_is_not_planned_returns_400(
    client, user_id, make_plan, plan_status
):
    if plan_status == "DRAFT":
        plan = make_plan(status="DRAFT")
    else:
        plan = client.patch(
            f"/users/{user_id}/workout-plans/{make_plan()['id']}", json={"status": "CANCELLED"}
        ).json()
    assert plan["status"] == plan_status

    response = client.post(sessions_url(user_id), json={"workout_plan_id": plan["id"]})

    assert response.status_code == 400
    assert response.json() == {
        "detail": f"workout plan {plan['id']} is {plan_status}; only PLANNED workout plans "
        "can start a workout session"
    }
    assert client.get(sessions_url(user_id)).json() == []


@pytest.mark.parametrize("second", ["manual", "planned"])
@pytest.mark.parametrize("first", ["manual", "planned"])
def test_create_second_session_in_progress_returns_409(client, user_id, make_plan, first, second):
    plan_id = make_plan()["id"]
    response = client.post(
        sessions_url(user_id), json={"workout_plan_id": plan_id if first == "planned" else None}
    )
    assert response.status_code == 201
    running = response.json()

    response = client.post(
        sessions_url(user_id), json={"workout_plan_id": plan_id if second == "planned" else None}
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": f"user {user_id} already has workout session {running['id']} IN_PROGRESS; "
        "complete or cancel it first"
    }
    assert client.get(sessions_url(user_id)).json() == [running]


@pytest.mark.parametrize("new", ["manual", "planned"])
@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED"])
def test_create_session_after_finishing_the_one_in_progress_returns_201(
    client, user_id, make_plan, make_session, status, new
):
    finished = make_session(status)
    plan_id = make_plan()["id"] if new == "planned" else None

    response = client.post(sessions_url(user_id), json={"workout_plan_id": plan_id})

    assert response.status_code == 201
    assert [(s["id"], s["status"]) for s in client.get(sessions_url(user_id)).json()] == [
        (response.json()["id"], "IN_PROGRESS"),
        (finished["id"], status),
    ]


def test_create_session_for_missing_user_returns_404(client):
    response = client.post(sessions_url(2_147_483_647), json={})

    assert response.status_code == 404
    assert response.json() == {"detail": "user 2147483647 does not exist"}


@pytest.mark.parametrize(
    "body", [{"workout_plan_id": 0}, {"workout_plan_id": "plan"}, {"notes": ""}]
)
def test_create_session_with_invalid_body_returns_422(client, user_id, body):
    assert client.post(sessions_url(user_id), json=body).status_code == 422


# GET /users/{user_id}/workout-sessions


def test_list_sessions_returns_only_the_users_sessions_latest_first(
    client, user_id, other_user_id, make_session
):
    first = make_session("COMPLETED")
    second = make_session()
    make_session(owner=other_user_id)

    response = client.get(sessions_url(user_id))

    assert response.status_code == 200
    assert response.json() == [second, first]


@pytest.mark.parametrize(
    ("status", "expected"),
    [("IN_PROGRESS", ["in progress"]), ("COMPLETED", ["completed"]), ("CANCELLED", [])],
)
def test_list_sessions_filters_by_status(client, user_id, make_session, status, expected):
    # the completed one first: a user has one session IN_PROGRESS at a time
    sessions = {"completed": make_session("COMPLETED"), "in progress": make_session()}

    response = client.get(sessions_url(user_id), params={"status": status})

    assert [s["id"] for s in response.json()] == [sessions[key]["id"] for key in expected]


def test_list_sessions_with_invalid_filter_returns_422(client, user_id):
    assert client.get(sessions_url(user_id), params={"status": "PLANNED"}).status_code == 422


def test_list_sessions_of_missing_user_returns_404(client):
    assert client.get(sessions_url(2_147_483_647)).status_code == 404


# GET /users/{user_id}/workout-sessions/{session_id}


def test_get_session_returns_200_with_exercises_and_sets(
    client, user_id, make_session, bench_press
):
    created = make_session()

    response = client.get(sessions_url(user_id, created["id"]))

    assert response.status_code == 200
    (session_exercise,) = response.json()["exercises"]
    assert set(session_exercise) == set(WorkoutSessionExerciseResponse.model_fields)
    assert (session_exercise["exercise_id"], session_exercise["exercise_order"]) == (bench_press, 1)
    (workout_set,) = session_exercise["sets"]
    assert set(workout_set) == set(WorkoutSetResponse.model_fields)
    assert (workout_set["set_number"], workout_set["reps"], workout_set["weight_kg"]) == (
        1,
        8,
        50.0,
    )


def test_get_another_users_or_a_missing_session_returns_404(
    client, user_id, other_user_id, make_session
):
    others = make_session(owner=other_user_id)

    response = client.get(sessions_url(user_id, others["id"]))

    assert response.status_code == 404
    assert response.json() == {"detail": f"user {user_id} has no workout session {others['id']}"}
    assert client.get(sessions_url(user_id, 2_147_483_647)).status_code == 404


# PATCH /users/{user_id}/workout-sessions/{session_id}


def test_complete_session_returns_200_and_sets_completed_at(client, user_id, make_session):
    created = make_session()

    response = client.patch(sessions_url(user_id, created["id"]), json={"status": "COMPLETED"})

    assert response.status_code == 200
    completed = response.json()
    assert completed["status"] == "COMPLETED"
    assert datetime.fromisoformat(completed["completed_at"]) >= datetime.fromisoformat(
        completed["started_at"]
    )
    assert completed["exercises"] == created["exercises"]


def test_complete_empty_session_returns_400(client, user_id, make_session):
    created = make_session(with_exercise=False)

    response = client.patch(sessions_url(user_id, created["id"]), json={"status": "COMPLETED"})

    assert response.status_code == 400
    assert response.json() == {"detail": "a COMPLETED workout session needs at least one exercise"}
    assert client.get(sessions_url(user_id, created["id"])).json() == created


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("COMPLETED", "IN_PROGRESS"),
        ("COMPLETED", "CANCELLED"),
        ("CANCELLED", "IN_PROGRESS"),
        ("CANCELLED", "COMPLETED"),
    ],
)
def test_patch_finished_session_to_another_status_returns_409(
    client, user_id, make_session, current, new
):
    created = make_session(current)

    response = client.patch(sessions_url(user_id, created["id"]), json={"status": new})

    assert response.status_code == 409
    assert response.json() == {"detail": f"a {current} workout session cannot become {new}"}
    assert client.get(sessions_url(user_id, created["id"])).json() == created


@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED"])
def test_patch_finished_session_notes_returns_409(client, user_id, make_session, status):
    created = make_session(status)

    response = client.patch(sessions_url(user_id, created["id"]), json={"notes": "Rewritten"})

    assert response.status_code == 409
    assert response.json() == {
        "detail": f"workout session {created['id']} is {status} and cannot be changed"
    }
    assert client.get(sessions_url(user_id, created["id"])).json() == created


def test_patch_session_with_null_status_returns_400(client, user_id, make_session):
    created = make_session()

    response = client.patch(sessions_url(user_id, created["id"]), json={"status": None})

    assert response.status_code == 400
    assert response.json() == {"detail": "these fields cannot be null: status"}


@pytest.mark.parametrize("body", [{"status": "PLANNED"}, {"status": "done"}, {"notes": ""}])
def test_patch_session_with_invalid_body_returns_422(client, user_id, make_session, body):
    created = make_session()

    assert client.patch(sessions_url(user_id, created["id"]), json=body).status_code == 422


def test_patch_session_ignores_plan_timestamps_and_owner_in_the_body(
    client, user_id, other_user_id, make_plan, make_session
):
    created = make_session()

    response = client.patch(
        sessions_url(user_id, created["id"]),
        json={
            "notes": "Changed",
            "workout_plan_id": make_plan()["id"],
            "started_at": "2000-01-01T00:00:00Z",
            "completed_at": "2000-01-01T01:00:00Z",
            "user_id": other_user_id,
        },
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["notes"] == "Changed"
    unchanged = ["workout_plan_id", "started_at", "completed_at", "user_id", "status"]
    assert {key: updated[key] for key in unchanged} == {key: created[key] for key in unchanged}


def test_patch_another_users_session_returns_404_and_changes_nothing(
    client, user_id, other_user_id, make_session
):
    others = make_session(owner=other_user_id)

    response = client.patch(sessions_url(user_id, others["id"]), json={"status": "CANCELLED"})

    assert response.status_code == 404
    assert client.get(sessions_url(other_user_id, others["id"])).json() == others


# DELETE /users/{user_id}/workout-sessions/{session_id}


def test_delete_in_progress_session_returns_204(client, user_id, make_session):
    created = make_session()

    response = client.delete(sessions_url(user_id, created["id"]))

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(sessions_url(user_id, created["id"])).status_code == 404


@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED"])
def test_delete_finished_session_returns_409(client, user_id, make_session, status):
    created = make_session(status)

    response = client.delete(sessions_url(user_id, created["id"]))

    assert response.status_code == 409
    assert "only IN_PROGRESS workout sessions can be deleted" in response.json()["detail"]
    assert client.get(sessions_url(user_id, created["id"])).json() == created


def test_delete_another_users_session_returns_404_and_keeps_it(
    client, user_id, other_user_id, make_session
):
    others = make_session(owner=other_user_id)

    assert client.delete(sessions_url(user_id, others["id"])).status_code == 404
    assert client.get(sessions_url(other_user_id, others["id"])).json() == others


# POST /users/{user_id}/workout-sessions/{session_id}/exercises


def test_add_exercise_returns_201_and_the_session_exercise(client, user_id, make_session, squat):
    created = make_session(with_exercise=False)

    # an id or workout_session_id in the body is ignored
    response = client.post(
        exercises_url(user_id, created["id"]),
        json={
            "exercise_id": squat,
            "exercise_order": 1,
            "notes": "Deep",
            "id": 1,
            "workout_session_id": 999_999,
        },
    )

    assert response.status_code == 201
    added = response.json()
    assert set(added) == set(WorkoutSessionExerciseResponse.model_fields)
    assert {
        key: added[key]
        for key in [
            "workout_session_id",
            "plan_exercise_id",
            "exercise_id",
            "exercise_order",
            "notes",
            "sets",
        ]
    } == {
        "workout_session_id": created["id"],
        "plan_exercise_id": None,
        "exercise_id": squat,
        "exercise_order": 1,
        "notes": "Deep",
        "sets": [],
    }
    assert client.get(sessions_url(user_id, created["id"])).json()["exercises"] == [added]


def test_add_substitute_for_a_planned_exercise_returns_201(
    client, user_id, make_plan, make_session, squat
):
    plan = make_plan()
    created = make_session(workout_plan_id=plan["id"], with_exercise=False)
    planned_id = plan["exercises"][0]["id"]

    response = client.post(
        exercises_url(user_id, created["id"]),
        json={"exercise_id": squat, "exercise_order": 1, "plan_exercise_id": planned_id},
    )

    assert response.status_code == 201
    assert (response.json()["exercise_id"], response.json()["plan_exercise_id"]) == (
        squat,
        planned_id,
    )


@pytest.mark.parametrize(
    ("case", "detail"),
    [
        ("unknown exercise", "exercise 2147483647 does not exist"),
        ("inactive exercise", "is inactive and cannot be added"),
        ("link without a plan", "has no workout plan, so it cannot link"),
        ("link to another plan", "has no exercise"),
    ],
)
def test_add_exercise_breaking_a_rule_returns_400(
    client,
    user_id,
    make_plan,
    make_session,
    bench_press,
    retirable_exercise_id,
    test_engine,
    case,
    detail,
):
    plan = make_plan()
    other_plan = make_plan()
    created = make_session(
        workout_plan_id=plan["id"] if case == "link to another plan" else None,
        with_exercise=False,
    )
    retire_exercise(test_engine, retirable_exercise_id)
    body = {
        "unknown exercise": {"exercise_id": 2_147_483_647},
        "inactive exercise": {"exercise_id": retirable_exercise_id},
        "link without a plan": {
            "exercise_id": bench_press,
            "plan_exercise_id": plan["exercises"][0]["id"],
        },
        "link to another plan": {
            "exercise_id": bench_press,
            "plan_exercise_id": other_plan["exercises"][0]["id"],
        },
    }[case]

    response = client.post(
        exercises_url(user_id, created["id"]), json={**body, "exercise_order": 1}
    )

    assert response.status_code == 400
    assert detail in response.json()["detail"]
    assert client.get(sessions_url(user_id, created["id"])).json() == created


@pytest.mark.parametrize("case", ["taken order", "finished session"])
def test_add_exercise_conflicting_with_the_session_returns_409(
    client, user_id, make_session, squat, case
):
    created = make_session("COMPLETED" if case == "finished session" else "IN_PROGRESS")

    response = client.post(
        exercises_url(user_id, created["id"]),
        json={"exercise_id": squat, "exercise_order": 1 if case == "taken order" else 2},
    )

    assert response.status_code == 409
    assert client.get(sessions_url(user_id, created["id"])).json() == created


def test_add_exercise_to_another_users_session_returns_404(
    client, user_id, other_user_id, make_session, squat
):
    others = make_session(owner=other_user_id)

    response = client.post(
        exercises_url(user_id, others["id"]), json={"exercise_id": squat, "exercise_order": 2}
    )

    assert response.status_code == 404
    assert client.get(sessions_url(other_user_id, others["id"])).json() == others


@pytest.mark.parametrize(
    "body",
    [
        {"exercise_order": 1},
        {"exercise_id": 1},
        {"exercise_id": 0, "exercise_order": 1},
        {"exercise_id": 1, "exercise_order": 0},
        {"exercise_id": 1, "exercise_order": 1, "plan_exercise_id": 0},
        {"exercise_id": "squat", "exercise_order": 1},
    ],
)
def test_add_exercise_with_invalid_body_returns_422(client, user_id, make_session, body):
    created = make_session(with_exercise=False)

    assert client.post(exercises_url(user_id, created["id"]), json=body).status_code == 422


# PATCH /users/{user_id}/workout-sessions/{session_id}/exercises/{session_exercise_id}


def test_patch_exercise_returns_200_and_changes_only_the_supplied_fields(
    client, user_id, make_session, squat
):
    created = make_session()
    before = created["exercises"][0]

    response = client.patch(
        sessions_url(user_id, created["id"], before["id"]),
        json={"exercise_id": squat, "notes": "Swapped"},
    )

    assert response.status_code == 200
    after = response.json()
    assert (after["exercise_id"], after["notes"]) == (squat, "Swapped")
    unchanged = set(before) - {"exercise_id", "notes", "updated_at"}
    assert {key: after[key] for key in unchanged} == {key: before[key] for key in unchanged}


@pytest.mark.parametrize(
    ("status", "change", "status_code", "detail"),
    [
        ("IN_PROGRESS", {"exercise_order": None}, 400, "these fields cannot be null"),
        ("IN_PROGRESS", {"exercise_order": 2}, 409, "already has an exercise at exercise_order 2"),
        ("COMPLETED", {"notes": "Rewritten"}, 409, "is COMPLETED and cannot be changed"),
    ],
)
def test_patch_exercise_breaking_a_rule_returns_400_or_409(
    client, user_id, make_session, squat, status, change, status_code, detail
):
    created = make_session()
    if status == "IN_PROGRESS":
        client.post(
            exercises_url(user_id, created["id"]), json={"exercise_id": squat, "exercise_order": 2}
        )
    else:
        client.patch(sessions_url(user_id, created["id"]), json={"status": status})
    before = client.get(sessions_url(user_id, created["id"])).json()

    response = client.patch(
        sessions_url(user_id, created["id"], created["exercises"][0]["id"]), json=change
    )

    assert response.status_code == status_code
    assert detail in response.json()["detail"]
    assert client.get(sessions_url(user_id, created["id"])).json() == before


def test_patch_exercise_of_another_session_or_user_returns_404(
    client, user_id, other_user_id, make_session
):
    # the user's earlier session: one session is IN_PROGRESS at a time
    other = make_session("COMPLETED")
    created = make_session()
    others = make_session(owner=other_user_id)
    other_exercise = other["exercises"][0]["id"]

    response = client.patch(
        sessions_url(user_id, created["id"], other_exercise), json={"notes": "x"}
    )
    assert response.status_code == 404
    assert response.json() == {
        "detail": f"workout session {created['id']} has no exercise {other_exercise}"
    }
    response = client.patch(
        sessions_url(user_id, others["id"], others["exercises"][0]["id"]), json={"notes": "x"}
    )
    assert response.status_code == 404
    assert client.get(sessions_url(other_user_id, others["id"])).json() == others


@pytest.mark.parametrize(
    "change", [{"exercise_order": 0}, {"exercise_id": 0}, {"plan_exercise_id": 0}, {"notes": ""}]
)
def test_patch_exercise_with_invalid_body_returns_422(client, user_id, make_session, change):
    created = make_session()

    response = client.patch(
        sessions_url(user_id, created["id"], created["exercises"][0]["id"]), json=change
    )

    assert response.status_code == 422


# DELETE /users/{user_id}/workout-sessions/{session_id}/exercises/{session_exercise_id}


def test_delete_exercise_returns_204_and_removes_its_sets(client, user_id, make_session):
    created = make_session()

    response = client.delete(sessions_url(user_id, created["id"], created["exercises"][0]["id"]))

    assert response.status_code == 204
    assert client.get(sessions_url(user_id, created["id"])).json()["exercises"] == []


def test_delete_exercise_of_finished_session_returns_409(client, user_id, make_session):
    created = make_session("CANCELLED")

    response = client.delete(sessions_url(user_id, created["id"], created["exercises"][0]["id"]))

    assert response.status_code == 409
    assert client.get(sessions_url(user_id, created["id"])).json() == created


def test_delete_exercise_of_another_users_session_returns_404(
    client, user_id, other_user_id, make_session
):
    others = make_session(owner=other_user_id)

    response = client.delete(sessions_url(user_id, others["id"], others["exercises"][0]["id"]))

    assert response.status_code == 404
    assert client.get(sessions_url(other_user_id, others["id"])).json() == others


# POST /users/{user_id}/workout-sessions/{session_id}/exercises/{session_exercise_id}/sets


def test_add_set_returns_201_and_the_set(client, user_id, make_session):
    created = make_session()
    session_exercise_id = created["exercises"][0]["id"]

    response = client.post(
        sets_url(user_id, created["id"], session_exercise_id),
        json={"set_number": 2, "reps": 7, "weight_kg": 50, "rpe": 9.5, "id": 1},
    )

    assert response.status_code == 201
    added = response.json()
    assert set(added) == set(WorkoutSetResponse.model_fields)
    assert {
        key: added[key]
        for key in [
            "workout_session_exercise_id",
            "set_number",
            "reps",
            "weight_kg",
            "rpe",
            "completed",
            "notes",
        ]
    } == {
        "workout_session_exercise_id": session_exercise_id,
        "set_number": 2,
        "reps": 7,
        "weight_kg": 50.0,
        "rpe": 9.5,
        "completed": True,
        "notes": None,
    }
    sets = client.get(sessions_url(user_id, created["id"])).json()["exercises"][0]["sets"]
    assert sets[1] == added


@pytest.mark.parametrize("case", ["taken set_number", "finished session"])
def test_add_set_conflicting_with_the_session_returns_409(client, user_id, make_session, case):
    created = make_session("COMPLETED" if case == "finished session" else "IN_PROGRESS")

    response = client.post(
        sets_url(user_id, created["id"], created["exercises"][0]["id"]),
        json={"set_number": 1 if case == "taken set_number" else 2, "reps": 8},
    )

    assert response.status_code == 409
    assert client.get(sessions_url(user_id, created["id"])).json() == created


def test_add_set_to_another_sessions_or_users_exercise_returns_404(
    client, user_id, other_user_id, make_session
):
    # the user's earlier session: one session is IN_PROGRESS at a time
    other = make_session("COMPLETED")
    created = make_session()
    others = make_session(owner=other_user_id)
    body = {"set_number": 2, "reps": 8}

    response = client.post(sets_url(user_id, created["id"], other["exercises"][0]["id"]), json=body)
    assert response.status_code == 404
    response = client.post(sets_url(user_id, others["id"], others["exercises"][0]["id"]), json=body)
    assert response.status_code == 404
    assert client.get(sessions_url(user_id, other["id"])).json() == other


@pytest.mark.parametrize(
    "change",
    [
        {"set_number": 0},
        {"reps": 0},
        {"reps": None},
        {"weight_kg": 0},
        {"weight_kg": -5},
        {"rpe": 0},
        {"rpe": 10.5},
        {"completed": "maybe"},
        {"notes": ""},
    ],
)
def test_add_set_with_invalid_body_returns_422(client, user_id, make_session, change):
    created = make_session()

    response = client.post(
        sets_url(user_id, created["id"], created["exercises"][0]["id"]),
        json={"set_number": 2, "reps": 8, **change},
    )

    assert response.status_code == 422


# PATCH and DELETE .../sets/{set_id}


def test_patch_set_returns_200_and_changes_only_the_supplied_fields(client, user_id, make_session):
    created = make_session()
    before = created["exercises"][0]["sets"][0]

    response = client.patch(
        sessions_url(user_id, created["id"], created["exercises"][0]["id"], before["id"]),
        json={"reps": 6, "completed": False, "rpe": 10},
    )

    assert response.status_code == 200
    after = response.json()
    assert (after["reps"], after["completed"], after["rpe"]) == (6, False, 10.0)
    unchanged = set(before) - {"reps", "completed", "rpe", "updated_at"}
    assert {key: after[key] for key in unchanged} == {key: before[key] for key in unchanged}


@pytest.mark.parametrize(
    ("status", "change", "status_code"),
    [
        ("IN_PROGRESS", {"reps": None}, 400),
        ("IN_PROGRESS", {"set_number": 2}, 409),
        ("COMPLETED", {"reps": 12}, 409),
        ("IN_PROGRESS", {"rpe": 11}, 422),
    ],
)
def test_patch_set_breaking_a_rule(client, user_id, make_session, status, change, status_code):
    created = make_session()
    url = sets_url(user_id, created["id"], created["exercises"][0]["id"])
    client.post(url, json={"set_number": 2, "reps": 7})
    if status != "IN_PROGRESS":
        client.patch(sessions_url(user_id, created["id"]), json={"status": status})
    before = client.get(sessions_url(user_id, created["id"])).json()

    response = client.patch(f"{url}/{created['exercises'][0]['sets'][0]['id']}", json=change)

    assert response.status_code == status_code
    assert client.get(sessions_url(user_id, created["id"])).json() == before


def test_set_of_another_exercise_returns_404(client, user_id, make_session, squat):
    created = make_session()
    other_exercise = client.post(
        exercises_url(user_id, created["id"]), json={"exercise_id": squat, "exercise_order": 2}
    ).json()
    set_id = created["exercises"][0]["sets"][0]["id"]
    url = sessions_url(user_id, created["id"], other_exercise["id"], set_id)

    assert client.patch(url, json={"reps": 1}).status_code == 404
    response = client.delete(url)

    assert response.status_code == 404
    assert response.json() == {
        "detail": f"session exercise {other_exercise['id']} has no set {set_id}"
    }


def test_delete_set_returns_204(client, user_id, make_session):
    created = make_session()
    session_exercise = created["exercises"][0]

    response = client.delete(
        sessions_url(
            user_id, created["id"], session_exercise["id"], session_exercise["sets"][0]["id"]
        )
    )

    assert response.status_code == 204
    assert client.get(sessions_url(user_id, created["id"])).json()["exercises"][0]["sets"] == []


@pytest.mark.parametrize("owner", ["self, finished", "other user"])
def test_delete_set_of_finished_or_another_users_session_is_refused(
    client, user_id, other_user_id, make_session, owner
):
    session_owner = other_user_id if owner == "other user" else user_id
    created = make_session("COMPLETED", owner=session_owner)
    session_exercise = created["exercises"][0]

    response = client.delete(
        sessions_url(
            user_id, created["id"], session_exercise["id"], session_exercise["sets"][0]["id"]
        )
    )

    assert response.status_code == (404 if owner == "other user" else 409)
    assert client.get(sessions_url(session_owner, created["id"])).json() == created


# a whole workout, and its history afterwards


def test_workout_from_a_plan_with_a_substitution(client, user_id, make_plan, squat):
    plan = make_plan()
    planned = plan["exercises"][0]  # a bench press
    session_id = client.post(sessions_url(user_id), json={"workout_plan_id": plan["id"]}).json()[
        "id"
    ]

    # the bench was taken, so squats instead of the planned bench press
    session_exercise = client.post(
        exercises_url(user_id, session_id),
        json={"exercise_id": squat, "exercise_order": 1, "plan_exercise_id": planned["id"]},
    ).json()
    for number, (reps, weight) in enumerate([(8, 60), (8, 60), (6, 60)], start=1):
        response = client.post(
            sets_url(user_id, session_id, session_exercise["id"]),
            json={"set_number": number, "reps": reps, "weight_kg": weight},
        )
        assert response.status_code == 201
    completed = client.patch(sessions_url(user_id, session_id), json={"status": "COMPLETED"}).json()

    assert (completed["status"], completed["workout_plan_id"]) == ("COMPLETED", plan["id"])
    (done,) = completed["exercises"]
    assert (done["exercise_id"], done["plan_exercise_id"]) == (squat, planned["id"])
    assert [(s["set_number"], s["reps"], s["weight_kg"]) for s in done["sets"]] == [
        (1, 8, 60.0),
        (2, 8, 60.0),
        (3, 6, 60.0),
    ]
    # the history is fixed now, and cancelling the plan does not change it
    url = sessions_url(user_id, session_id, done["id"], done["sets"][2]["id"])
    assert client.patch(url, json={"reps": 8}).status_code == 409
    client.patch(f"/users/{user_id}/workout-plans/{plan['id']}", json={"status": "CANCELLED"})
    assert client.get(sessions_url(user_id, session_id)).json() == completed


def test_history_stays_readable_after_its_exercise_is_retired(
    client, user_id, make_session, retirable_exercise_id, test_engine
):
    created = make_session(with_exercise=False)
    client.post(
        exercises_url(user_id, created["id"]),
        json={"exercise_id": retirable_exercise_id, "exercise_order": 1},
    )
    completed = client.patch(
        sessions_url(user_id, created["id"]), json={"status": "COMPLETED"}
    ).json()

    retire_exercise(test_engine, retirable_exercise_id)

    response = client.get(sessions_url(user_id, created["id"]))
    assert response.status_code == 200
    assert response.json() == completed


# malformed IDs


@pytest.mark.parametrize("bad_id", ["abc", "0", "-1", "2147483648"])
@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("post", "/users/{bad}/workout-sessions", {}),
        ("get", "/users/{bad}/workout-sessions", None),
        ("get", "/users/{user}/workout-sessions/{bad}", None),
        ("patch", "/users/{user}/workout-sessions/{bad}", {"notes": "x"}),
        ("delete", "/users/{user}/workout-sessions/{bad}", None),
        (
            "post",
            "/users/{user}/workout-sessions/{bad}/exercises",
            {"exercise_id": 1, "exercise_order": 1},
        ),
        ("patch", "/users/{user}/workout-sessions/{session}/exercises/{bad}", {"notes": "x"}),
        ("delete", "/users/{user}/workout-sessions/{session}/exercises/{bad}", None),
        (
            "post",
            "/users/{user}/workout-sessions/{session}/exercises/{bad}/sets",
            {"set_number": 1, "reps": 1},
        ),
        (
            "patch",
            "/users/{user}/workout-sessions/{session}/exercises/{exercise}/sets/{bad}",
            {"reps": 1},
        ),
        (
            "delete",
            "/users/{user}/workout-sessions/{session}/exercises/{exercise}/sets/{bad}",
            None,
        ),
    ],
)
def test_malformed_ids_return_422(client, user_id, make_session, method, url, body, bad_id):
    created = make_session()

    response = client.request(
        method,
        url.format(
            bad=bad_id, user=user_id, session=created["id"], exercise=created["exercises"][0]["id"]
        ),
        json=body,
    )

    assert response.status_code == 422
