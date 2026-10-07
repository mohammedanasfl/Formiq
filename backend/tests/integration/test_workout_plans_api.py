"""Integration tests for the workout plan API routes.

They require the local PostgreSQL container to be running. The client fixture
sends every request to the test database and empties the user and workout plan
tables before and after each test.
"""

import pytest

from app.schemas import WorkoutPlanExerciseResponse, WorkoutPlanResponse
from tests.integration.workout_plans import retire_exercise

DATE = "2026-10-10"


@pytest.fixture
def user_id(client):
    return client.post("/users", json={"email": "plan-api@example.com"}).json()["id"]


@pytest.fixture
def other_user_id(client):
    return client.post("/users", json={"email": "plan-api-other@example.com"}).json()["id"]


@pytest.fixture
def bench_press(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Bench Press"]


@pytest.fixture
def squat(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Back Squat"]


def exercise_body(exercise_id, exercise_order=1, **fields):
    return {
        "exercise_id": exercise_id,
        "exercise_order": exercise_order,
        "sets": 3,
        "reps": 8,
        **fields,
    }


def plans_url(user_id, plan_id=None, plan_exercise_id=None):
    url = f"/users/{user_id}/workout-plans"
    if plan_id is not None:
        url += f"/{plan_id}"
    if plan_exercise_id is not None:
        url += f"/exercises/{plan_exercise_id}"
    return url


@pytest.fixture
def make_plan(client, user_id, bench_press):
    """Creates a plan through the API in the given status, dated, with by
    default one bench press at exercise_order 1."""

    def make(status="DRAFT", *, owner=None, exercises=None, scheduled_date=DATE, name="Push Day"):
        owner = owner or user_id
        body = {
            "name": name,
            "status": "PLANNED" if status == "PLANNED" else "DRAFT",
            "scheduled_date": scheduled_date,
            "exercises": [exercise_body(bench_press)] if exercises is None else exercises,
        }
        response = client.post(plans_url(owner), json=body)
        assert response.status_code == 201, response.json()
        plan = response.json()
        if status == "CANCELLED":
            plan = client.patch(plans_url(owner, plan["id"]), json={"status": "CANCELLED"}).json()
        return plan

    return make


# POST /users/{user_id}/workout-plans


def test_create_plan_returns_201_and_the_plan(client, user_id):
    response = client.post(plans_url(user_id), json={"name": "Push Day", "status": "DRAFT"})

    assert response.status_code == 201
    plan = response.json()
    assert set(plan) == set(WorkoutPlanResponse.model_fields)
    assert {
        key: plan[key] for key in ["user_id", "name", "description", "status", "scheduled_date"]
    } == {
        "user_id": user_id,
        "name": "Push Day",
        "description": None,
        "status": "DRAFT",
        "scheduled_date": None,
    }
    assert plan["exercises"] == []
    assert client.get(plans_url(user_id, plan["id"])).json() == plan


def test_create_plan_with_exercises_returns_them_in_order(client, user_id, bench_press, squat):
    response = client.post(
        plans_url(user_id),
        json={
            "name": "Push Day",
            "description": "Chest first",
            "status": "PLANNED",
            "scheduled_date": DATE,
            "exercises": [
                exercise_body(squat, 2),
                exercise_body(
                    bench_press, 1, weight_kg=50, rest_seconds=120, notes="Controlled tempo"
                ),
            ],
        },
    )

    assert response.status_code == 201
    plan = response.json()
    assert (plan["status"], plan["scheduled_date"]) == ("PLANNED", DATE)
    assert all(
        set(item) == set(WorkoutPlanExerciseResponse.model_fields) for item in plan["exercises"]
    )
    prescription = [
        "exercise_id",
        "exercise_order",
        "sets",
        "reps",
        "weight_kg",
        "rest_seconds",
        "notes",
    ]
    assert [{key: item[key] for key in prescription} for item in plan["exercises"]] == [
        exercise_body(bench_press, 1, weight_kg=50.0, rest_seconds=120, notes="Controlled tempo"),
        exercise_body(squat, 2, weight_kg=None, rest_seconds=None, notes=None),
    ]
    assert all(item["workout_plan_id"] == plan["id"] for item in plan["exercises"])


def test_create_plan_for_missing_user_returns_404(client):
    response = client.post(plans_url(2_147_483_647), json={"name": "Push Day"})

    assert response.status_code == 404
    assert response.json() == {"detail": "user 2147483647 does not exist"}


def test_create_plan_ignores_identity_fields_in_the_body(client, user_id, other_user_id):
    response = client.post(
        plans_url(user_id),
        json={
            "name": "Push Day",
            "id": 999_999,
            "user_id": other_user_id,
            "created_at": "2000-01-01T00:00:00Z",
        },
    )

    assert response.status_code == 201
    assert response.json()["user_id"] == user_id
    assert response.json()["id"] != 999_999
    assert client.get(plans_url(other_user_id)).json() == []


@pytest.mark.parametrize(
    ("change", "exercises", "detail"),
    [
        (
            {"status": "PLANNED", "scheduled_date": None},
            "one",
            "a PLANNED workout plan needs a scheduled_date",
        ),
        ({"status": "PLANNED"}, "none", "a PLANNED workout plan needs at least one exercise"),
        ({}, "unknown", "exercise 2147483647 does not exist"),
        ({}, "same order", "each exercise_order can be used once in a workout plan: 1"),
    ],
)
def test_create_plan_breaking_a_rule_returns_400(
    client, user_id, bench_press, squat, change, exercises, detail
):
    body = {
        "name": "Push Day",
        "status": "DRAFT",
        "scheduled_date": DATE,
        "exercises": {
            "one": [exercise_body(bench_press)],
            "none": [],
            "unknown": [exercise_body(bench_press, 1), exercise_body(2_147_483_647, 2)],
            "same order": [exercise_body(bench_press, 1), exercise_body(squat, 1)],
        }[exercises],
        **change,
    }

    response = client.post(plans_url(user_id), json=body)

    assert response.status_code == 400
    assert response.json() == {"detail": detail}
    assert client.get(plans_url(user_id)).json() == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        {"name": "x" * 151},
        {"name": "Push Day", "status": "COMPLETED"},
        {"name": "Push Day", "scheduled_date": "next monday"},
        {"name": "Push Day", "exercises": [{"exercise_id": 1, "exercise_order": 1, "sets": 3}]},
        {"name": "Push Day", "exercises": [exercise_body(1, sets=0)]},
        {"name": "Push Day", "exercises": [exercise_body(1, reps=0)]},
        {"name": "Push Day", "exercises": [exercise_body(1, exercise_order=0)]},
        {"name": "Push Day", "exercises": [exercise_body(1, weight_kg=0)]},
        {"name": "Push Day", "exercises": [exercise_body(1, rest_seconds=-1)]},
    ],
)
def test_create_plan_with_invalid_body_returns_422(client, user_id, body):
    assert client.post(plans_url(user_id), json=body).status_code == 422


# GET /users/{user_id}/workout-plans


def test_list_plans_returns_only_the_users_plans_latest_date_first(
    client, user_id, other_user_id, make_plan
):
    undated = make_plan(scheduled_date=None, name="Undated")
    earlier = make_plan(scheduled_date="2026-10-09", name="Earlier")
    later = make_plan(scheduled_date="2026-10-11", name="Later")
    make_plan(owner=other_user_id, name="Not mine")

    response = client.get(plans_url(user_id))

    assert response.status_code == 200
    assert [plan["id"] for plan in response.json()] == [later["id"], earlier["id"], undated["id"]]
    assert response.json()[0] == later


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"status": "PLANNED"}, ["planned"]),
        ({"status": "DRAFT"}, ["draft"]),
        ({"scheduled_date": "2026-10-11"}, ["draft"]),
        ({"status": "DRAFT", "scheduled_date": DATE}, []),
    ],
)
def test_list_plans_applies_the_filters(client, user_id, make_plan, params, expected):
    plans = {
        "planned": make_plan("PLANNED"),
        "draft": make_plan(scheduled_date="2026-10-11"),
    }

    response = client.get(plans_url(user_id), params=params)

    assert response.status_code == 200
    assert [plan["id"] for plan in response.json()] == [plans[key]["id"] for key in expected]


def test_list_plans_of_missing_user_returns_404(client):
    response = client.get(plans_url(2_147_483_647))

    assert response.status_code == 404
    assert response.json() == {"detail": "user 2147483647 does not exist"}


@pytest.mark.parametrize("params", [{"status": "COMPLETED"}, {"scheduled_date": "tomorrow"}])
def test_list_plans_with_invalid_filter_returns_422(client, user_id, params):
    assert client.get(plans_url(user_id), params=params).status_code == 422


# GET /users/{user_id}/workout-plans/{plan_id}


def test_get_plan_returns_200_and_the_plan(client, user_id, make_plan):
    plan = make_plan("PLANNED")

    response = client.get(plans_url(user_id, plan["id"]))

    assert response.status_code == 200
    assert response.json() == plan


def test_get_another_users_or_a_missing_plan_returns_404(client, user_id, other_user_id, make_plan):
    plan = make_plan(owner=other_user_id)

    response = client.get(plans_url(user_id, plan["id"]))

    assert response.status_code == 404
    assert response.json() == {"detail": f"user {user_id} has no workout plan {plan['id']}"}
    assert client.get(plans_url(user_id, 2_147_483_647)).status_code == 404


# PATCH /users/{user_id}/workout-plans/{plan_id}


def test_patch_plan_changes_only_the_supplied_fields(client, user_id, make_plan):
    plan = make_plan()

    response = client.patch(
        plans_url(user_id, plan["id"]), json={"name": "Pull Day", "description": "Back"}
    )

    assert response.status_code == 200
    updated = response.json()
    assert (updated["name"], updated["description"]) == ("Pull Day", "Back")
    unchanged = set(plan) - {"name", "description", "updated_at"}
    assert {key: updated[key] for key in unchanged} == {key: plan[key] for key in unchanged}
    assert client.get(plans_url(user_id, plan["id"])).json() == updated


def test_patch_plan_ignores_identity_fields_and_exercises_in_the_body(
    client, user_id, other_user_id, make_plan
):
    plan = make_plan()

    response = client.patch(
        plans_url(user_id, plan["id"]),
        json={"name": "Pull Day", "user_id": other_user_id, "id": 999_999, "exercises": []},
    )

    assert response.status_code == 200
    updated = response.json()
    assert (updated["id"], updated["user_id"], updated["name"]) == (plan["id"], user_id, "Pull Day")
    assert updated["exercises"] == plan["exercises"]
    assert client.get(plans_url(other_user_id)).json() == []


def test_patch_draft_to_planned_returns_200(client, user_id, make_plan):
    plan = make_plan()

    response = client.patch(plans_url(user_id, plan["id"]), json={"status": "PLANNED"})

    assert response.status_code == 200
    assert response.json()["status"] == "PLANNED"


@pytest.mark.parametrize(
    ("current", "new"), [("CANCELLED", "PLANNED"), ("CANCELLED", "DRAFT"), ("PLANNED", "DRAFT")]
)
def test_patch_plan_to_a_disallowed_status_returns_409(client, user_id, make_plan, current, new):
    plan = make_plan(current)

    response = client.patch(plans_url(user_id, plan["id"]), json={"status": new})

    assert response.status_code == 409
    assert response.json() == {"detail": f"a {current} workout plan cannot become {new}"}
    assert client.get(plans_url(user_id, plan["id"])).json()["status"] == current


@pytest.mark.parametrize(
    ("status", "plan_fields", "change", "detail"),
    [
        ("DRAFT", {"scheduled_date": None}, {"status": "PLANNED"}, "needs a scheduled_date"),
        ("DRAFT", {"exercises": []}, {"status": "PLANNED"}, "needs at least one exercise"),
        ("PLANNED", {}, {"scheduled_date": None}, "needs a scheduled_date"),
        ("DRAFT", {}, {"name": None}, "these fields cannot be null: name"),
    ],
)
def test_patch_plan_breaking_a_rule_returns_400(
    client, user_id, make_plan, status, plan_fields, change, detail
):
    plan = make_plan(status, **plan_fields)

    response = client.patch(plans_url(user_id, plan["id"]), json=change)

    assert response.status_code == 400
    assert detail in response.json()["detail"]
    assert client.get(plans_url(user_id, plan["id"])).json() == plan


def test_patch_cancelled_plan_returns_409(client, user_id, make_plan):
    plan = make_plan("CANCELLED")

    response = client.patch(plans_url(user_id, plan["id"]), json={"name": "Pull Day"})

    assert response.status_code == 409
    assert response.json() == {
        "detail": f"workout plan {plan['id']} is CANCELLED and cannot be changed"
    }
    assert client.get(plans_url(user_id, plan["id"])).json() == plan


def test_patch_another_users_plan_returns_404_and_changes_nothing(
    client, user_id, other_user_id, make_plan
):
    plan = make_plan(owner=other_user_id)

    response = client.patch(plans_url(user_id, plan["id"]), json={"name": "Mine now"})

    assert response.status_code == 404
    assert client.get(plans_url(other_user_id, plan["id"])).json() == plan


@pytest.mark.parametrize(
    "body", [{"status": "COMPLETED"}, {"name": ""}, {"scheduled_date": "soon"}]
)
def test_patch_plan_with_invalid_body_returns_422(client, user_id, make_plan, body):
    plan = make_plan()

    assert client.patch(plans_url(user_id, plan["id"]), json=body).status_code == 422


# DELETE /users/{user_id}/workout-plans/{plan_id}


def test_delete_draft_plan_returns_204(client, user_id, make_plan):
    plan = make_plan()

    response = client.delete(plans_url(user_id, plan["id"]))

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(plans_url(user_id, plan["id"])).status_code == 404


@pytest.mark.parametrize("status", ["PLANNED", "CANCELLED"])
def test_delete_planned_or_cancelled_plan_returns_409(client, user_id, make_plan, status):
    plan = make_plan(status)

    response = client.delete(plans_url(user_id, plan["id"]))

    assert response.status_code == 409
    assert "only DRAFT workout plans can be deleted" in response.json()["detail"]
    assert client.get(plans_url(user_id, plan["id"])).json() == plan


def test_delete_another_users_plan_returns_404_and_keeps_it(
    client, user_id, other_user_id, make_plan
):
    plan = make_plan(owner=other_user_id)

    assert client.delete(plans_url(user_id, plan["id"])).status_code == 404
    assert client.get(plans_url(other_user_id, plan["id"])).json() == plan


# POST /users/{user_id}/workout-plans/{plan_id}/exercises


def test_add_exercise_returns_201_and_the_plan_exercise(client, user_id, make_plan, squat):
    plan = make_plan()
    body = exercise_body(squat, 2, weight_kg=50, rest_seconds=120, notes="Controlled tempo")

    # an id or workout_plan_id in the body is ignored
    response = client.post(
        f"{plans_url(user_id, plan['id'])}/exercises",
        json={**body, "id": 1, "workout_plan_id": 999_999},
    )

    assert response.status_code == 201
    added = response.json()
    assert set(added) == set(WorkoutPlanExerciseResponse.model_fields)
    assert {key: added[key] for key in body} == {**body, "weight_kg": 50.0}
    assert added["workout_plan_id"] == plan["id"]
    assert client.get(plans_url(user_id, plan["id"])).json()["exercises"][1] == added


@pytest.mark.parametrize(
    ("exercise_order", "unknown_exercise", "status_code", "detail"),
    [
        (2, True, 400, "exercise 2147483647 does not exist"),
        (1, False, 409, "already has an exercise at exercise_order 1"),
    ],
)
def test_add_exercise_breaking_a_rule_returns_400_or_409(
    client, user_id, make_plan, squat, exercise_order, unknown_exercise, status_code, detail
):
    plan = make_plan()
    body = exercise_body(2_147_483_647 if unknown_exercise else squat, exercise_order)

    response = client.post(f"{plans_url(user_id, plan['id'])}/exercises", json=body)

    assert response.status_code == status_code
    assert detail in response.json()["detail"]
    assert client.get(plans_url(user_id, plan["id"])).json() == plan


def test_add_exercise_to_cancelled_plan_returns_409(client, user_id, make_plan, squat):
    plan = make_plan("CANCELLED")

    response = client.post(
        f"{plans_url(user_id, plan['id'])}/exercises", json=exercise_body(squat, 2)
    )

    assert response.status_code == 409
    assert client.get(plans_url(user_id, plan["id"])).json() == plan


def test_add_exercise_to_another_users_plan_returns_404(
    client, user_id, other_user_id, make_plan, squat
):
    plan = make_plan(owner=other_user_id)

    response = client.post(
        f"{plans_url(user_id, plan['id'])}/exercises", json=exercise_body(squat, 2)
    )

    assert response.status_code == 404
    assert client.get(plans_url(other_user_id, plan["id"])).json() == plan


@pytest.mark.parametrize(
    "change",
    [
        {"sets": 0},
        {"reps": 0},
        {"exercise_order": 0},
        {"weight_kg": 0},
        {"weight_kg": -1},
        {"rest_seconds": -1},
        {"exercise_id": "bench"},
        {"sets": None},
    ],
)
def test_add_exercise_with_invalid_body_returns_422(client, user_id, make_plan, squat, change):
    plan = make_plan()

    response = client.post(
        f"{plans_url(user_id, plan['id'])}/exercises", json={**exercise_body(squat, 2), **change}
    )

    assert response.status_code == 422


# PATCH /users/{user_id}/workout-plans/{plan_id}/exercises/{plan_exercise_id}


def test_patch_exercise_changes_only_the_supplied_fields(client, user_id, make_plan, squat):
    plan = make_plan()
    before = plan["exercises"][0]

    response = client.patch(
        plans_url(user_id, plan["id"], before["id"]), json={"exercise_id": squat, "weight_kg": 60}
    )

    assert response.status_code == 200
    after = response.json()
    assert (after["exercise_id"], after["weight_kg"]) == (squat, 60.0)
    unchanged = set(before) - {"exercise_id", "weight_kg", "updated_at"}
    assert {key: after[key] for key in unchanged} == {key: before[key] for key in unchanged}
    assert client.get(plans_url(user_id, plan["id"])).json()["exercises"] == [after]


@pytest.mark.parametrize(
    ("change", "status_code", "detail"),
    [
        ({"sets": None}, 400, "these fields cannot be null: sets"),
        ({"exercise_id": 2_147_483_647}, 400, "exercise 2147483647 does not exist"),
        ({"exercise_order": 2}, 409, "already has an exercise at exercise_order 2"),
    ],
)
def test_patch_exercise_breaking_a_rule_returns_400_or_409(
    client, user_id, make_plan, bench_press, squat, change, status_code, detail
):
    plan = make_plan(exercises=[exercise_body(bench_press, 1), exercise_body(squat, 2)])

    response = client.patch(plans_url(user_id, plan["id"], plan["exercises"][0]["id"]), json=change)

    assert response.status_code == status_code
    assert detail in response.json()["detail"]
    assert client.get(plans_url(user_id, plan["id"])).json() == plan


def test_patch_exercise_of_cancelled_plan_returns_409(client, user_id, make_plan):
    plan = make_plan("CANCELLED")

    response = client.patch(
        plans_url(user_id, plan["id"], plan["exercises"][0]["id"]), json={"sets": 5}
    )

    assert response.status_code == 409
    assert client.get(plans_url(user_id, plan["id"])).json() == plan


def test_patch_exercise_of_another_plan_or_user_returns_404(
    client, user_id, other_user_id, make_plan
):
    plan = make_plan()
    other_plan = make_plan()
    others_plan = make_plan(owner=other_user_id)

    # an exercise of another plan of the same user
    response = client.patch(
        plans_url(user_id, plan["id"], other_plan["exercises"][0]["id"]), json={"sets": 5}
    )
    assert response.status_code == 404
    assert response.json() == {
        "detail": f"workout plan {plan['id']} has no exercise {other_plan['exercises'][0]['id']}"
    }
    # an exercise of another user's plan
    response = client.patch(
        plans_url(user_id, others_plan["id"], others_plan["exercises"][0]["id"]), json={"sets": 5}
    )
    assert response.status_code == 404

    assert client.get(plans_url(user_id, other_plan["id"])).json() == other_plan
    assert client.get(plans_url(other_user_id, others_plan["id"])).json() == others_plan


@pytest.mark.parametrize(
    "change", [{"sets": 0}, {"reps": -1}, {"weight_kg": 0}, {"rest_seconds": -5}]
)
def test_patch_exercise_with_invalid_body_returns_422(client, user_id, make_plan, change):
    plan = make_plan()

    response = client.patch(plans_url(user_id, plan["id"], plan["exercises"][0]["id"]), json=change)

    assert response.status_code == 422


# DELETE /users/{user_id}/workout-plans/{plan_id}/exercises/{plan_exercise_id}


def test_delete_exercise_returns_204(client, user_id, make_plan, bench_press, squat):
    plan = make_plan(exercises=[exercise_body(bench_press, 1), exercise_body(squat, 2)])
    first, second = plan["exercises"]

    response = client.delete(plans_url(user_id, plan["id"], first["id"]))

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(plans_url(user_id, plan["id"])).json()["exercises"] == [second]


def test_delete_last_exercise_of_planned_plan_returns_400(client, user_id, make_plan):
    plan = make_plan("PLANNED")

    response = client.delete(plans_url(user_id, plan["id"], plan["exercises"][0]["id"]))

    assert response.status_code == 400
    assert response.json() == {"detail": "a PLANNED workout plan needs at least one exercise"}
    assert client.get(plans_url(user_id, plan["id"])).json() == plan


def test_delete_exercise_of_cancelled_plan_returns_409(client, user_id, make_plan):
    plan = make_plan("CANCELLED")

    response = client.delete(plans_url(user_id, plan["id"], plan["exercises"][0]["id"]))

    assert response.status_code == 409
    assert client.get(plans_url(user_id, plan["id"])).json() == plan


def test_delete_exercise_of_another_users_plan_returns_404(
    client, user_id, other_user_id, make_plan
):
    plan = make_plan(owner=other_user_id)

    response = client.delete(plans_url(user_id, plan["id"], plan["exercises"][0]["id"]))

    assert response.status_code == 404
    assert client.get(plans_url(other_user_id, plan["id"])).json() == plan


# malformed IDs


@pytest.mark.parametrize("bad_id", ["abc", "0", "-1", "2147483648"])
@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("post", "/users/{bad}/workout-plans", {"name": "Push Day"}),
        ("get", "/users/{bad}/workout-plans", None),
        ("get", "/users/{user}/workout-plans/{bad}", None),
        ("patch", "/users/{user}/workout-plans/{bad}", {"name": "Pull Day"}),
        ("delete", "/users/{user}/workout-plans/{bad}", None),
        ("post", "/users/{user}/workout-plans/{bad}/exercises", exercise_body(1)),
        ("patch", "/users/{user}/workout-plans/{plan}/exercises/{bad}", {"sets": 5}),
        ("delete", "/users/{user}/workout-plans/{plan}/exercises/{bad}", None),
    ],
)
def test_malformed_ids_return_422(client, user_id, make_plan, method, url, body, bad_id):
    plan = make_plan()

    response = client.request(
        method, url.format(bad=bad_id, user=user_id, plan=plan["id"]), json=body
    )

    assert response.status_code == 422


# inactive (retired) exercises


def test_add_inactive_exercise_returns_400(
    client, user_id, make_plan, retirable_exercise_id, test_engine
):
    plan = make_plan()
    retire_exercise(test_engine, retirable_exercise_id)

    response = client.post(
        f"{plans_url(user_id, plan['id'])}/exercises", json=exercise_body(retirable_exercise_id, 2)
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            f"exercise {retirable_exercise_id} is inactive and cannot be added to a workout plan"
        )
    }
    assert client.get(plans_url(user_id, plan["id"])).json() == plan


def test_create_plan_with_an_inactive_exercise_returns_400_and_saves_nothing(
    client, user_id, bench_press, retirable_exercise_id, test_engine
):
    retire_exercise(test_engine, retirable_exercise_id)
    body = {
        "name": "Push Day",
        "exercises": [exercise_body(bench_press, 1), exercise_body(retirable_exercise_id, 2)],
    }

    response = client.post(plans_url(user_id), json=body)

    assert response.status_code == 400
    assert "is inactive" in response.json()["detail"]
    assert client.get(plans_url(user_id)).json() == []


def test_patch_exercise_to_an_inactive_exercise_returns_400(
    client, user_id, make_plan, retirable_exercise_id, test_engine
):
    plan = make_plan()
    retire_exercise(test_engine, retirable_exercise_id)

    response = client.patch(
        plans_url(user_id, plan["id"], plan["exercises"][0]["id"]),
        json={"exercise_id": retirable_exercise_id},
    )

    assert response.status_code == 400
    assert client.get(plans_url(user_id, plan["id"])).json() == plan


def test_plan_with_an_exercise_retired_later_is_still_returned(
    client, user_id, make_plan, retirable_exercise_id, test_engine
):
    plan = make_plan(exercises=[exercise_body(retirable_exercise_id)])

    retire_exercise(test_engine, retirable_exercise_id)

    response = client.get(plans_url(user_id, plan["id"]))
    assert response.status_code == 200
    assert response.json() == plan
    assert client.get(plans_url(user_id)).json() == [plan]
