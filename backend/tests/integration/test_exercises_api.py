"""Integration tests for the exercise catalog API routes.

They require the local PostgreSQL container to be running. Test data is added
with catalog_session and read by catalog_client requests in the same
transaction, which is rolled back after each test. The test database also
holds the seeded catalog.
"""

import pytest

from app.schemas import EquipmentResponse, ExerciseResponse, MuscleGroupResponse
from tests.integration.catalog import (
    add_equipment,
    add_exercise,
    add_exercises_for_each_filter,
    add_muscle_group,
)


def names(response):
    return [row["name"] for row in response.json()]


@pytest.fixture
def press(catalog_session):
    """A test exercise with two muscles and one piece of equipment."""
    chest = add_muscle_group(catalog_session, "Test Chest")
    triceps = add_muscle_group(catalog_session, "Test Triceps")
    barbell = add_equipment(catalog_session, "Test Barbell")
    exercise = add_exercise(
        catalog_session,
        "Test Press",
        primary=[chest],
        secondary=[triceps],
        equipment=[barbell],
        difficulty="INTERMEDIATE",
        movement_pattern="HORIZONTAL_PUSH",
    )
    return {"id": exercise.id, "chest": chest.id, "triceps": triceps.id, "barbell": barbell.id}


# GET /exercises


def test_list_exercises_returns_200_and_exercises_with_muscles_and_equipment(
    catalog_client, press
):
    response = catalog_client.get("/exercises")

    assert response.status_code == 200
    exercise = next(row for row in response.json() if row["id"] == press["id"])
    assert set(exercise) == set(ExerciseResponse.model_fields)
    assert {key: exercise[key] for key in set(exercise) - {"created_at", "updated_at"}} == {
        "id": press["id"],
        "name": "Test Press",
        "description": None,
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "HORIZONTAL_PUSH",
        # each muscle is its group's id and name, and its role; primary first
        "muscles": [
            {"id": press["chest"], "name": "Test Chest", "role": "PRIMARY"},
            {"id": press["triceps"], "name": "Test Triceps", "role": "SECONDARY"},
        ],
        "equipment": [{"id": press["barbell"], "name": "Test Barbell"}],
        "is_active": True,
    }


def test_list_exercises_returns_the_seeded_bench_press(catalog_client):
    equipment_ids = {row["name"]: row["id"] for row in catalog_client.get("/equipment").json()}

    response = catalog_client.get(
        "/exercises",
        params={"movement_pattern": "HORIZONTAL_PUSH", "equipment_id": equipment_ids["Barbell"]},
    )

    assert response.status_code == 200
    assert names(response) == ["Barbell Bench Press"]
    bench_press = response.json()[0]
    assert [(muscle["name"], muscle["role"]) for muscle in bench_press["muscles"]] == [
        ("Chest", "PRIMARY"),
        ("Front Deltoid", "SECONDARY"),
        ("Triceps", "SECONDARY"),
    ]
    assert [item["name"] for item in bench_press["equipment"]] == ["Barbell", "Bench"]


def test_list_exercises_returns_exercises_ordered_by_name(catalog_client, catalog_session):
    muscle_group = add_muscle_group(catalog_session, "Test Muscle")
    for name in ["Test Zeta", "Test Alpha", "Test Mu"]:
        add_exercise(catalog_session, name, primary=[muscle_group])

    response = catalog_client.get("/exercises", params={"muscle_group_id": muscle_group.id})

    assert names(response) == ["Test Alpha", "Test Mu", "Test Zeta"]


@pytest.mark.parametrize(
    ("is_active", "expected"), [("true", "Test Match"), ("false", "Test Inactive")]
)
def test_list_exercises_applies_every_query_filter(
    catalog_client, catalog_session, is_active, expected
):
    muscle_group, item = add_exercises_for_each_filter(catalog_session)

    response = catalog_client.get(
        "/exercises",
        params={
            "difficulty": "BEGINNER",
            "movement_pattern": "SQUAT",
            "muscle_group_id": muscle_group.id,
            "equipment_id": item.id,
            "is_active": is_active,
        },
    )

    assert response.status_code == 200
    assert names(response) == [expected]


def test_list_exercises_excludes_inactive_exercises_by_default(catalog_client, catalog_session):
    add_exercise(catalog_session, "Test Active")
    add_exercise(catalog_session, "Test Inactive", is_active=False)

    found = names(catalog_client.get("/exercises"))

    assert "Test Active" in found
    assert "Test Inactive" not in found


@pytest.mark.parametrize("filter_name", ["muscle_group_id", "equipment_id"])
def test_list_exercises_for_unknown_muscle_group_or_equipment_returns_empty_list(
    catalog_client, filter_name
):
    response = catalog_client.get("/exercises", params={filter_name: 2_147_483_647})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "params",
    [
        {"difficulty": "EXPERT"},
        {"difficulty": "beginner"},
        {"movement_pattern": "PUSH"},
        {"muscle_group_id": "abc"},
        {"muscle_group_id": 0},
        {"muscle_group_id": 2_147_483_648},
        {"equipment_id": -1},
        {"equipment_id": 2_147_483_648},
        {"is_active": "maybe"},
    ],
)
def test_list_exercises_with_invalid_filter_returns_422(catalog_client, params):
    response = catalog_client.get("/exercises", params=params)

    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [["query", *params]]


# GET /exercises/{exercise_id}


def test_get_exercise_returns_200_and_the_exercise(catalog_client, press):
    response = catalog_client.get(f"/exercises/{press['id']}")

    assert response.status_code == 200
    listed = catalog_client.get("/exercises").json()
    assert response.json() == next(row for row in listed if row["id"] == press["id"])


def test_get_inactive_exercise_returns_200(catalog_client, catalog_session):
    exercise_id = add_exercise(catalog_session, "Test Inactive", is_active=False).id

    response = catalog_client.get(f"/exercises/{exercise_id}")

    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_get_missing_exercise_returns_404(catalog_client):
    response = catalog_client.get("/exercises/2147483647")

    assert response.status_code == 404
    assert response.json() == {"detail": "exercise 2147483647 does not exist"}


@pytest.mark.parametrize("exercise_id", ["abc", "0", "-1", "2147483648"])
def test_get_exercise_with_invalid_id_returns_422(catalog_client, exercise_id):
    assert catalog_client.get(f"/exercises/{exercise_id}").status_code == 422


# GET /muscle-groups and GET /equipment

REFERENCE_DATA = [
    ("/muscle-groups", add_muscle_group, MuscleGroupResponse, "Chest"),
    ("/equipment", add_equipment, EquipmentResponse, "Barbell"),
]


@pytest.mark.parametrize(("path", "add", "schema", "seeded"), REFERENCE_DATA)
def test_list_reference_data_returns_the_active_seeded_rows(
    catalog_client, catalog_session, path, add, schema, seeded
):
    add(catalog_session, "Test Inactive", is_active=False)

    response = catalog_client.get(path)

    assert response.status_code == 200
    rows = response.json()
    assert all(set(row) == set(schema.model_fields) for row in rows)
    assert seeded in names(response)
    assert "Test Inactive" not in names(response)
    assert all(row["is_active"] for row in rows)


@pytest.mark.parametrize(("path", "add", "schema", "seeded"), REFERENCE_DATA)
def test_list_reference_data_filters_inactive_rows_ordered_by_name(
    catalog_client, catalog_session, path, add, schema, seeded
):
    add(catalog_session, "Test B", is_active=False)
    add(catalog_session, "Test A", is_active=False)

    response = catalog_client.get(path, params={"is_active": "false"})

    assert response.status_code == 200
    assert names(response) == ["Test A", "Test B"]


@pytest.mark.parametrize("path", ["/muscle-groups", "/equipment"])
def test_list_reference_data_with_invalid_is_active_returns_422(catalog_client, path):
    assert catalog_client.get(path, params={"is_active": "maybe"}).status_code == 422
