"""Integration tests for the recovery summary route:
POST /users/{user_id}/workout-sessions/{session_id}/recovery-summary.

They require the local PostgreSQL container to be running. The client fixture sends every
request to the test database and empties the user, workout plan and workout session tables
before and after each test. The users, profiles and sessions are committed to the test
database directly: a session of squats and bench presses that took 55 minutes and ended an
hour ago, so a summary is the same whenever the test runs, except for hours_since_completed
(the route's clock is the real one, so that is only ever checked loosely).
"""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from itertools import islice, product

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.guidance import nutrition
from app.main import app
from app.models import (
    User,
    UserProfile,
    WorkoutSession,
    WorkoutSessionExercise,
    WorkoutSet,
)
from app.schemas import RecoverySummaryResponse
from app.schemas.recovery_summary import Allergen, BodyArea, DiscomfortKind, WarningSign
from tests.auth import bearer
from tests.integration.workout_plans import add_user, columns

SQUAT, BENCH = "Barbell Back Squat", "Barbell Bench Press"
# 3 sets of each: name, reps, weight in kg, and the rpe of each set
LIFTS = [
    (SQUAT, 5, 100.0, (7.0, 8.0, 8.5)),
    (BENCH, 8, 60.0, (7.0, 8.0, 9.0)),
]
# a distinctive text: if it comes back, the response echoed what was sent
SENTINEL = "ZQXSENTINEL"
OTHERS_NOTE = "my knee pain on the other user's session ZQXOTHERNOTE"
MISSING_USER = 2_147_483_647
MISSING_SESSION = 2_000_000_000
UNAUTHENTICATED = (401, {"detail": "not authenticated"}, "Bearer")
FULL_REQUEST = {
    "discomfort": [{"area": "KNEES", "kind": "SORENESS", "severity": 5}],
    "warning_signs": [],
    "avoid_allergens": ["PEANUTS", "MILK"],
}
ANIMAL_FOODS = {"MEAT", "POULTRY", "FISH", "SHELLFISH", "EGG"}
TOP_LEVEL = {
    "session_id",
    "completed_at",
    "hours_since_completed",
    "safety",
    "calculated",
    "estimates",
    "guidance",
    "missing_data",
    "sources",
}
ESTIMATES = {
    "post_workout_protein_g",
    "daily_protein_g",
    "daily_carbohydrate_g",
    "rapid_refuel_carbohydrate_g_per_hour",
    "active_energy_kcal",
}


def summary_url(user_id, session_id):
    return f"/users/{user_id}/workout-sessions/{session_id}/recovery-summary"


def sessions_url(user_id, session_id=None):
    url = f"/users/{user_id}/workout-sessions"
    return url if session_id is None else f"{url}/{session_id}"


def make_user(session, email):
    user = add_user(session, email)
    session.commit()
    return user.id


@pytest.fixture
def user_id(client, service_session):
    return make_user(service_session, "recovery-api@example.com")


@pytest.fixture
def other_user_id(client, service_session):
    return make_user(service_session, "recovery-api-other@example.com")


@pytest.fixture
def add_profile(service_session, profile_fields):
    def add(owner_id, **changes):
        service_session.add(UserProfile(user_id=owner_id, **{**profile_fields, **changes}))
        service_session.commit()

    return add


@pytest.fixture
def add_workout(service_session, catalog_exercise_ids):
    """Commits a session of the user: 3 x 5 squats at 100 kg and 3 x 8 bench presses at
    60 kg, 55 minutes long, ended an hour ago (not ended, unless COMPLETED). Returns its id."""

    def add(owner_id, *, status="COMPLETED", notes=None):
        ended = datetime.now(UTC) - timedelta(hours=1)
        workout = WorkoutSession(
            user_id=owner_id,
            status=status,
            started_at=ended - timedelta(minutes=55),
            completed_at=ended if status == "COMPLETED" else None,
            notes=notes,
            exercises=[
                WorkoutSessionExercise(
                    exercise_id=catalog_exercise_ids[name],
                    exercise_order=order,
                    sets=[
                        WorkoutSet(
                            set_number=number, reps=reps, weight_kg=weight, rpe=rpe, completed=True
                        )
                        for number, rpe in enumerate(rpes, start=1)
                    ],
                )
                for order, (name, reps, weight, rpes) in enumerate(LIFTS, start=1)
            ],
        )
        service_session.add(workout)
        service_session.flush()
        workout_id = workout.id
        service_session.commit()
        return workout_id

    return add


@pytest.fixture
def own_session(user_id, add_workout):
    """A COMPLETED session of the user."""
    return add_workout(user_id)


def table_state(engine):
    """Every table's row count, and the rows a summary reads with all their columns
    (updated_at included), read through a session of its own."""
    with Session(engine) as session:
        counts = {
            table.name: session.scalar(select(func.count()).select_from(table))
            for table in Base.metadata.sorted_tables
        }
        rows = [
            columns(row)
            for model in (User, UserProfile, WorkoutSession, WorkoutSessionExercise, WorkoutSet)
            for row in session.scalars(select(model).order_by(model.id))
        ]
    return counts, rows


@contextmanager
def recorded_statements(engine):
    """The SQL statements the engine runs inside the block."""
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def answer(response):
    return response.status_code, response.json(), response.headers.get("www-authenticate")


def summary_of(response):
    assert response.status_code == 200, response.text
    return RecoverySummaryResponse.model_validate(response.json())


def plans_of(summary):
    return {plan.muscle: plan for plan in summary.guidance.recovery.muscles}


def without_hours(body):
    """The response with the one value that depends on the real clock left out."""
    return {key: value for key, value in body.items() if key != "hours_since_completed"}


def assert_nothing_echoed(response):
    assert SENTINEL not in response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    assert all("input" not in error for error in detail)


# --- authentication ---


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer ", "Bearer not.a.token", "Basic YXV0aC1vbmVAZXhhbXBsZS5jb206cGFzc3dvcmQ="],
    ids=["no_token", "empty_bearer", "malformed_token", "basic_scheme"],
)
@pytest.mark.parametrize("body", [None, {"unexpected": SENTINEL}], ids=["no_body", "bad_body"])
def test_a_request_without_a_valid_token_is_401(
    client, user_id, add_profile, own_session, authorization, body
):
    add_profile(user_id, first_name="Asha")
    client.sign_in_path_user = False
    headers = {} if authorization is None else {"Authorization": authorization}

    response = client.post(summary_url(user_id, own_session), json=body, headers=headers)

    # authentication comes first: an anonymous caller learns nothing from the body either
    assert answer(response) == UNAUTHENTICATED
    assert "Asha" not in response.text and SENTINEL not in response.text


# --- ownership ---


@pytest.mark.parametrize(
    "request_kwargs",
    [{}, {"json": {}}, {"json": FULL_REQUEST}, {"json": {"unexpected": SENTINEL}}],
    ids=["no_body", "empty_object", "full_body", "bad_body"],
)
def test_another_path_user_is_not_found_whatever_the_body_and_nothing_changes(
    client, test_engine, user_id, other_user_id, add_profile, add_workout, request_kwargs
):
    add_profile(other_user_id, first_name="Ravi")
    others_session = add_workout(other_user_id, notes=OTHERS_NOTE)
    before = table_state(test_engine)

    responses = [
        client.post(
            summary_url(path_user, others_session), headers=bearer(user_id), **request_kwargs
        )
        for path_user in (other_user_id, MISSING_USER)
    ]

    # another user and a user that does not exist get the same answer, whatever the body
    assert [(r.status_code, r.json()) for r in responses] == [(404, {"detail": "not found"})] * 2
    for response in responses:
        assert "Ravi" not in response.text and "ZQXOTHERNOTE" not in response.text
    assert table_state(test_engine) == before


@pytest.mark.parametrize("status", ["COMPLETED", "IN_PROGRESS", "CANCELLED"])
def test_another_users_session_under_your_own_path_is_not_found(
    client, test_engine, user_id, other_user_id, add_profile, add_workout, status
):
    add_profile(other_user_id, first_name="Ravi")
    others_session = add_workout(other_user_id, status=status, notes=OTHERS_NOTE)
    before = table_state(test_engine)

    response = client.post(summary_url(user_id, others_session))

    # its status is never looked at, so an unfinished session is not a 409: whether it exists
    # is never revealed
    assert response.status_code == 404
    assert response.json() == {"detail": f"user {user_id} has no workout session {others_session}"}
    assert "Ravi" not in response.text and "ZQXOTHERNOTE" not in response.text
    assert table_state(test_engine) == before


def test_a_session_that_does_not_exist_is_not_found_the_same_way(client, user_id, own_session):
    response = client.post(summary_url(user_id, MISSING_SESSION), json={})

    assert response.status_code == 404
    assert response.json() == {"detail": f"user {user_id} has no workout session {MISSING_SESSION}"}


def test_the_users_own_session_is_found_where_anothers_is_not(
    client, user_id, other_user_id, own_session, add_workout
):
    others_session = add_workout(other_user_id)

    own = client.post(summary_url(user_id, own_session))
    others = client.post(summary_url(user_id, others_session))

    assert own.status_code == 200
    assert own.json()["session_id"] == own_session
    assert others.status_code == 404


# --- a session that is not completed ---


@pytest.mark.parametrize("status", ["IN_PROGRESS", "CANCELLED"])
@pytest.mark.parametrize(
    "request_kwargs", [{}, {"json": FULL_REQUEST}], ids=["no_body", "full_body"]
)
def test_a_session_that_is_not_completed_is_409(
    client, test_engine, user_id, add_workout, status, request_kwargs
):
    session_id = add_workout(user_id, status=status)
    before = table_state(test_engine)

    response = client.post(summary_url(user_id, session_id), **request_kwargs)

    assert response.status_code == 409
    assert response.json() == {
        "detail": f"workout session {session_id} is {status}; "
        "only COMPLETED workout sessions have a recovery summary"
    }
    assert table_state(test_engine) == before


def test_a_session_has_a_summary_once_it_is_completed(client, user_id, catalog_exercise_ids):
    # through the routes of the API alone, so the session's times are the database's
    created = client.post(sessions_url(user_id), json={})
    assert created.status_code == 201
    session_id = created.json()["id"]
    exercise = client.post(
        f"{sessions_url(user_id, session_id)}/exercises",
        json={"exercise_id": catalog_exercise_ids[BENCH], "exercise_order": 1},
    )
    assert exercise.status_code == 201
    added = client.post(
        f"{sessions_url(user_id, session_id)}/exercises/{exercise.json()['id']}/sets",
        json={"set_number": 1, "reps": 8, "weight_kg": 60, "rpe": 8},
    )
    assert added.status_code == 201

    started = client.post(summary_url(user_id, session_id))
    completed = client.patch(sessions_url(user_id, session_id), json={"status": "COMPLETED"})
    finished = client.post(summary_url(user_id, session_id))

    assert started.status_code == 409
    assert completed.status_code == 200
    summary = summary_of(finished)
    assert summary.session_id == session_id
    [bench] = summary.calculated.exercises
    assert (bench.name, bench.status, bench.completed_sets) == (BENCH, "TRAINED", 1)
    assert (bench.total_reps, bench.volume_kg, bench.average_rpe) == (8, 480.0, 8.0)
    assert "Chest" in plans_of(summary)
    # no profile was recorded
    assert [item.field for item in summary.missing_data] == ["profile"]


# --- the request ---


def discomforts(count):
    """This many reports, each of a different area and kind."""
    return [
        {"area": area.value, "kind": kind.value, "severity": 1}
        for area, kind in islice(product(BodyArea, DiscomfortKind), count)
    ]


def report(**changes):
    return {"area": "KNEES", "kind": "PAIN", "severity": 5} | changes


def raw(content, content_type="application/json"):
    return {"content": content, "headers": {"Content-Type": content_type}}


INVALID_REQUESTS = {
    "unknown_field": {"json": {"unexpected": SENTINEL}},
    "user_id": {"json": {"user_id": 999}},
    "unknown_field_in_a_report": {"json": {"discomfort": [report(unexpected=SENTINEL)]}},
    "unknown_area": {"json": {"discomfort": [report(area=SENTINEL)]}},
    "unknown_kind": {"json": {"discomfort": [report(kind=SENTINEL)]}},
    "lower_case_area": {"json": {"discomfort": [report(area="knees")]}},
    "unknown_warning_sign": {"json": {"warning_signs": [SENTINEL]}},
    "unknown_allergen": {"json": {"avoid_allergens": [SENTINEL]}},
    "missing_severity": {"json": {"discomfort": [{"area": "KNEES", "kind": "PAIN"}]}},
    "missing_area": {"json": {"discomfort": [{"kind": "PAIN", "severity": 5}]}},
    "severity_text": {"json": {"discomfort": [report(severity=SENTINEL)]}},
    "severity_digit_text": {"json": {"discomfort": [report(severity="5")]}},
    "severity_fraction": {"json": {"discomfort": [report(severity=5.5)]}},
    "severity_above_10": {"json": {"discomfort": [report(severity=11)]}},
    "severity_below_0": {"json": {"discomfort": [report(severity=-1)]}},
    "severity_true": {"json": {"discomfort": [report(severity=True)]}},
    "severity_null": {"json": {"discomfort": [report(severity=None)]}},
    "severity_list": {"json": {"discomfort": [report(severity=[5])]}},
    "severity_huge": {"json": {"discomfort": [report(severity=10**30)]}},
    "duplicate_warning_signs": {"json": {"warning_signs": ["DARK_URINE", "DARK_URINE"]}},
    "duplicate_allergens": {"json": {"avoid_allergens": ["MILK", "MILK"]}},
    "duplicate_discomfort": {"json": {"discomfort": [report(severity=1), report(severity=9)]}},
    "eleven_discomforts": {"json": {"discomfort": discomforts(11)}},
    "discomfort_not_a_list": {"json": {"discomfort": SENTINEL}},
    "warning_signs_not_a_list": {"json": {"warning_signs": SENTINEL}},
    "discomfort_null": {"json": {"discomfort": None}},
    "report_not_an_object": {"json": {"discomfort": [SENTINEL]}},
    "invalid_json": raw('{"warning_signs": ["DARK_URINE", ' + SENTINEL),
    "json_array": raw("[]"),
    "json_array_of_reports": raw(json.dumps([report()])),
    "json_string": raw(json.dumps(SENTINEL)),
    "json_number": raw("5"),
    "json_true": raw("true"),
}


@pytest.mark.parametrize("request_kwargs", INVALID_REQUESTS.values(), ids=INVALID_REQUESTS)
def test_an_invalid_request_is_422_and_never_echoes_what_was_sent(
    client, test_engine, user_id, own_session, request_kwargs
):
    before = table_state(test_engine)

    response = client.post(summary_url(user_id, own_session), **request_kwargs)

    assert response.status_code == 422
    assert_nothing_echoed(response)
    assert all(error["loc"][0] == "body" for error in response.json()["detail"])
    assert table_state(test_engine) == before


@pytest.mark.parametrize("named", ["other", "own", "missing", "null"])
def test_a_body_naming_a_user_is_rejected(client, user_id, other_user_id, own_session, named):
    value = {"other": other_user_id, "own": user_id, "missing": MISSING_USER, "null": None}[named]

    response = client.post(summary_url(user_id, own_session), json={"user_id": value})

    # the body has no say over the user, not even the right one
    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert (error["loc"], error["type"]) == (["body", "user_id"], "extra_forbidden")


def test_a_request_with_the_wrong_content_type_is_422_and_not_echoed(
    client, user_id, own_session
):
    body = json.dumps({"warning_signs": ["DARK_URINE"], "unexpected": SENTINEL})

    response = client.post(summary_url(user_id, own_session), **raw(body, "text/plain"))

    assert response.status_code == 422
    assert_nothing_echoed(response)


@pytest.mark.parametrize("bad_id", ["abc", "0", "-1", "2147483648"])
def test_a_malformed_session_id_is_422(client, user_id, bad_id):
    response = client.post(summary_url(user_id, bad_id), json={}, headers=bearer(user_id))

    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [["path", "session_id"]]


@pytest.mark.parametrize("bad_id", ["abc", "0", "-1", "2147483648"])
def test_a_malformed_user_id_is_422(client, user_id, own_session, bad_id):
    response = client.post(summary_url(bad_id, own_session), json={}, headers=bearer(user_id))

    assert response.status_code == 422
    # the route and its user dependency both name the id, so it can be reported twice
    assert {tuple(error["loc"]) for error in response.json()["detail"]} == {("path", "user_id")}


@pytest.mark.parametrize("session_id", [1, 2_147_483_647])
def test_the_largest_and_smallest_ids_are_valid_ids_that_are_not_found(
    client, user_id, session_id
):
    response = client.post(summary_url(user_id, session_id))

    assert response.status_code == 404
    assert response.json() == {"detail": f"user {user_id} has no workout session {session_id}"}


# --- the summary ---


@pytest.fixture
def profiled(user_id, add_profile, own_session):
    add_profile(
        user_id, weight_kg=72.0, goal="build_muscle", dietary_preference="vegetarian", age=30
    )
    return own_session


@pytest.mark.parametrize(
    "request_kwargs",
    [
        {},
        {"json": {}},
        raw(b""),
        raw("{}"),
        raw(" {} \n"),
        {"json": {"discomfort": [], "warning_signs": [], "avoid_allergens": []}},
    ],
    ids=[
        "no_content",
        "empty_object",
        "empty_body_as_json",
        "raw_empty_object",
        "padded",
        "empty_lists",
    ],
)
def test_the_body_is_optional_and_an_empty_one_reports_nothing(
    client, user_id, profiled, request_kwargs
):
    baseline = client.post(summary_url(user_id, profiled), json={})
    assert baseline.status_code == 200

    response = client.post(summary_url(user_id, profiled), **request_kwargs)

    assert response.status_code == 200, response.text
    assert without_hours(response.json()) == without_hours(baseline.json())


def test_a_json_null_body_is_read_as_no_body(client, user_id, profiled):
    # an optional body: FastAPI gives a JSON null the default, as it gives no content
    baseline = client.post(summary_url(user_id, profiled))

    response = client.post(summary_url(user_id, profiled), **raw("null"))

    assert response.status_code == 200
    assert without_hours(response.json()) == without_hours(baseline.json())


def test_a_summary_has_the_shape_of_the_response_model(client, user_id, profiled):
    response = client.post(summary_url(user_id, profiled))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    summary = RecoverySummaryResponse.model_validate(body)
    assert set(body) == TOP_LEVEL == set(RecoverySummaryResponse.model_fields)
    assert summary.session_id == profiled
    assert summary.guidance.fluid_loss_measured is False
    assert body["guidance"]["fluid_loss_measured"] is False
    assert set(body["estimates"]) == ESTIMATES
    given = [estimate for estimate in body["estimates"].values() if estimate is not None]
    assert len(given) == len(ESTIMATES)
    for estimate in given:
        assert estimate["low"] <= estimate["high"]
        assert estimate["basis"] and estimate["assumptions"] and estimate["source_ids"]
    assert summary.safety.status == "OK" and summary.safety.notices == []
    # every cited source is listed, once
    cited = {
        source_id for estimate in given for source_id in estimate["source_ids"]
    }
    listed = [source.id for source in summary.sources]
    assert cited <= set(listed) and len(listed) == len(set(listed))


def test_a_realistic_summary(client, user_id, profiled):
    response = client.post(summary_url(user_id, profiled), json=FULL_REQUEST)

    summary = summary_of(response)
    assert summary.session_id == profiled
    # the session ended an hour ago: the route's clock is the real one
    assert summary.hours_since_completed == pytest.approx(1.0, abs=0.25)
    calculated = summary.calculated
    assert (calculated.duration_minutes, calculated.duration_plausible) == (55.0, True)
    assert [item.name for item in calculated.exercises] == [SQUAT, BENCH]
    assert (calculated.completed_sets, calculated.total_reps) == (6, 15 + 24)
    assert calculated.volume_kg == 100.0 * 15 + 60.0 * 24
    used = calculated.profile_values_used
    assert (used.weight_kg, used.age, used.goal_category) == (72.0, 30, "BUILD_MUSCLE")
    assert used.dietary_preference == "vegetarian"

    estimates = summary.estimates
    assert (estimates.post_workout_protein_g.low, estimates.post_workout_protein_g.high) == (18, 29)
    assert (estimates.daily_protein_g.low, estimates.daily_protein_g.high) == (115, 144)
    assert (estimates.daily_carbohydrate_g.low, estimates.daily_carbohydrate_g.high) == (216, 360)
    refuel = estimates.rapid_refuel_carbohydrate_g_per_hour
    assert (refuel.low, refuel.high) == (72, 86)
    assert (estimates.active_energy_kcal.low, estimates.active_energy_kcal.high) == (160, 330)
    assert summary.missing_data == []

    plans = plans_of(summary)
    quadriceps, chest = plans["Quadriceps"], plans["Chest"]
    assert (quadriceps.status, quadriceps.rest_hours) == ("REST", 72)
    assert quadriceps.rest_until == summary.completed_at + timedelta(hours=72)
    assert (chest.status, chest.rest_hours) == ("REST", 48)
    assert chest.rest_until == summary.completed_at + timedelta(hours=48)
    # soreness in the knees reaches the hamstrings and the calves
    assert (plans["Hamstrings"].role, plans["Hamstrings"].rest_hours) == ("SECONDARY", 72)
    assert plans["Calves"].role is None and plans["Calves"].rest_hours == 72
    assert (plans["Triceps"].status, plans["Triceps"].rest_until) == ("ALSO_WORKED", None)

    assert summary.safety.status == "CAUTION"
    foods = summary.guidance.food_suggestions
    assert (foods.preference_status, foods.dietary_pattern) == ("APPLIED", "VEGETARIAN")
    assert set(foods.allergens_excluded) == {"PEANUTS", "MILK"}
    assert foods.items
    for item in foods.items:
        assert not ANIMAL_FOODS & set(item.contains), item.name
        assert not {"PEANUTS", "MILK"} & set(item.allergens), item.name
    assert [note.text for note in summary.guidance.hydration] == [
        item.text for item in nutrition.hydration_items()
    ]
    assert summary.guidance.fluid_loss_measured is False


@pytest.mark.parametrize(
    "request_body",
    [
        {"discomfort": [report(severity=0, kind="SORENESS")]},
        {"discomfort": [report(severity=10, kind="SORENESS")]},
        {"discomfort": discomforts(10)},
        {"avoid_allergens": [allergen.value for allergen in Allergen]},
        {"warning_signs": [sign.value for sign in WarningSign]},
    ],
    ids=["severity_0", "severity_10", "ten_discomforts", "every_allergen", "every_warning_sign"],
)
def test_the_limits_of_a_valid_request_are_accepted(client, user_id, profiled, request_body):
    response = client.post(summary_url(user_id, profiled), json=request_body)

    summary_of(response)


# --- a warning sign ---


@pytest.mark.parametrize("sign", [sign.value for sign in WarningSign])
def test_a_warning_sign_gives_one_urgent_notice_and_withholds_everything_else(
    client, user_id, profiled, sign
):
    normal = client.post(summary_url(user_id, profiled), json={})
    hydration = [item.text for item in nutrition.hydration_items()]

    response = client.post(
        summary_url(user_id, profiled),
        json={
            "warning_signs": [sign],
            # none of these changes what a warning sign withholds
            "discomfort": [report(severity=8)],
            "avoid_allergens": ["MILK"],
        },
    )

    summary = summary_of(response)
    assert summary.safety.status == "SEEK_MEDICAL_CARE"
    [notice] = summary.safety.notices
    assert notice.code == "SEEK_MEDICAL_CARE"
    assert "Stop training and seek medical care now" in notice.message
    body = response.json()
    assert body["estimates"] == dict.fromkeys(ESTIMATES)
    assert body["guidance"]["hydration"] == []
    assert body["guidance"]["post_workout_carbohydrate"] == []
    assert body["guidance"]["sleep"] is None
    assert body["guidance"]["recovery"] is None
    assert body["guidance"]["food_suggestions"] is None
    assert body["guidance"]["fluid_loss_measured"] is False
    assert body["missing_data"] == []
    # the calculated facts stay, as they were
    assert body["calculated"] == normal.json()["calculated"]
    assert summary.calculated.exercises and summary.calculated.muscles_trained
    assert summary.calculated.profile_values_used is not None
    # the normal summary does carry what is withheld here
    for text in hydration:
        assert text in normal.text and text not in response.text


# --- no profile ---


def test_without_a_profile_the_summary_has_no_estimate_and_says_why(
    client, user_id, own_session
):
    response = client.post(summary_url(user_id, own_session), json=FULL_REQUEST)

    summary = summary_of(response)
    body = response.json()
    assert body["estimates"] == dict.fromkeys(ESTIMATES)
    assert [item.field for item in summary.missing_data] == ["profile"]
    assert summary.missing_data[0].effect
    assert summary.calculated.profile_values_used is None
    assert summary.calculated.duration_minutes == 55.0
    # the rest of the summary does not need a profile
    plans = plans_of(summary)
    assert plans["Chest"].rest_hours == 48
    assert plans["Quadriceps"].rest_hours == 72  # the reported soreness in the knees
    assert summary.guidance.hydration
    assert summary.guidance.food_suggestions.preference_status == "NOT_SET"


# --- notes ---


def test_a_flagged_note_gives_a_notice_and_is_never_returned(
    client, user_id, add_workout, profiled
):
    note = "sharp knee pain on the last set ZQXNOTE"
    flagged = add_workout(user_id, notes=note)

    response = client.post(summary_url(user_id, flagged))

    summary = summary_of(response)
    assert [notice.code for notice in summary.safety.notices] == ["NOTES_FLAGGED"]
    assert summary.safety.status == "CAUTION"
    assert "ZQXNOTE" not in response.text and "knee pain" not in response.text


# --- nothing is written ---


def test_a_summary_writes_nothing_and_the_same_request_gives_the_same_summary(
    client, test_engine, user_id, profiled
):
    before = table_state(test_engine)
    request = {**FULL_REQUEST, "discomfort": [report(kind="SORENESS", area="CHEST", severity=8)]}

    with recorded_statements(test_engine) as statements:
        responses = [client.post(summary_url(user_id, profiled), json=request) for _ in range(2)]
        no_body = client.post(summary_url(user_id, profiled))
        refused = client.post(summary_url(user_id, profiled), json={"unexpected": 1})

    assert [r.status_code for r in responses] == [200, 200]
    assert no_body.status_code == 200 and refused.status_code == 422
    first, second = (response.json() for response in responses)
    # only the time since the workout changes between requests
    assert without_hours(first) == without_hours(second)
    assert second["hours_since_completed"] >= first["hours_since_completed"]
    assert first["safety"]["status"] == "CAUTION"
    # every row is as it was, and the requests only read: no insert, update, delete or lock
    assert table_state(test_engine) == before
    assert statements
    for statement in statements:
        assert statement.lstrip().upper().startswith("SELECT"), statement
        assert "FOR UPDATE" not in statement.upper() and "FOR SHARE" not in statement.upper()


def test_a_warning_sign_summary_writes_nothing_either(client, test_engine, user_id, profiled):
    before = table_state(test_engine)

    response = client.post(
        summary_url(user_id, profiled), json={"warning_signs": ["DARK_URINE"]}
    )

    assert response.status_code == 200
    assert table_state(test_engine) == before


# --- the API's description of the route ---

ROUTE = "/users/{user_id}/workout-sessions/{session_id}/recovery-summary"


def test_the_route_is_one_post_that_answers_with_the_response_model():
    paths = app.openapi()["paths"]

    assert set(paths[ROUTE]) == {"post"}
    operation = paths[ROUTE]["post"]
    assert operation["tags"] == ["recovery summaries"]
    # nothing is created: the success status is 200 and only 200
    assert [code for code in operation["responses"] if code.startswith("2")] == ["200"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/RecoverySummaryResponse"}
    # the body is optional and is the request model
    assert operation["requestBody"].get("required", False) is False
    assert "#/components/schemas/RecoverySummaryRequest" in json.dumps(operation["requestBody"])


def test_the_route_is_not_part_of_the_coach_or_the_approval_flow():
    recovery_paths = [path for path in app.openapi()["paths"] if "recovery" in path]

    assert recovery_paths == [ROUTE]
    for path in recovery_paths:
        assert not path.startswith("/coach")
        assert "approv" not in path and "proposal" not in path
