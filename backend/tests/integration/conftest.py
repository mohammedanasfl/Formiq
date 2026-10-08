import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_access_tokens
from app.core.config import settings
from app.db import database
from app.db.database import get_db
from app.main import app
from app.models import (
    Exercise,
    User,
    UserProfile,
    WorkoutPlan,
    WorkoutPlanExercise,
    WorkoutSession,
    WorkoutSessionExercise,
)
from app.schemas.workout_plan import MAX_INTEGER
from tests.auth import TEST_ACCESS_TOKENS, bearer
from tests.integration.database import check_test_database_url

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture(autouse=True)
def test_access_tokens():
    """Access tokens are signed and verified with the test-only secret, whatever
    AUTH_JWT_SECRET is set to."""
    app.dependency_overrides[get_access_tokens] = lambda: TEST_ACCESS_TOKENS
    try:
        yield TEST_ACCESS_TOKENS
    finally:
        app.dependency_overrides.pop(get_access_tokens, None)


_USER_PATH = re.compile(r"/users/(\d+)(?:/|$)")


class PathUserClient(TestClient):
    """A TestClient that signs each request under /users/{user_id} in as that
    user, unless the request sets its own Authorization header, so the tests of
    those routes test them as their owner. Other requests are sent as they are.
    With sign_in_path_user set to False, no request is signed in."""

    sign_in_path_user = True

    def request(self, method, url, *, headers=None, **kwargs):
        match = _USER_PATH.match(str(url))
        # an id no user can have, such as 0, is sent as it is: not signed in
        if (
            self.sign_in_path_user
            and match
            and 1 <= int(match[1]) <= MAX_INTEGER
            and "authorization"
            not in {
                name.lower() for name in headers or {}
            }
        ):
            headers = {**(headers or {}), **bearer(int(match[1]))}
        return super().request(method, url, headers=headers, **kwargs)


@pytest.fixture(scope="session")
def test_database_url():
    return check_test_database_url(settings.test_database_url, settings.database_url)


@pytest.fixture(scope="session")
def test_alembic_config(test_database_url):
    """Alembic configuration that migrates the test database, not DATABASE_URL."""
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = test_database_url
    return config


@pytest.fixture(scope="session")
def test_engine(test_database_url, test_alembic_config):
    command.upgrade(test_alembic_config, "head")
    engine = create_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    session = Session(test_engine)
    try:
        yield session
    finally:
        session.close()


def delete_user_rows(engine):
    with Session(engine) as session:
        # workout sessions and plans first: a user with sessions or plans cannot be
        # deleted (RESTRICT); their exercises and sets are deleted with them (CASCADE)
        session.execute(delete(WorkoutSession))
        session.execute(delete(WorkoutPlan))
        session.execute(delete(UserProfile))
        session.execute(delete(User))
        session.commit()


@pytest.fixture
def service_session(test_engine):
    """Session for service tests.

    Services commit, so rolling back is not enough: the users and user_profiles
    tables of the test database are emptied before and after each test.
    """
    delete_user_rows(test_engine)
    session = Session(test_engine)
    try:
        yield session
    finally:
        session.close()
        delete_user_rows(test_engine)


@pytest.fixture
def client(test_engine, monkeypatch):
    """TestClient whose requests use the test database, signed in as the user in
    a /users/{user_id} path (PathUserClient).

    get_db is overridden so each request gets a session on the test database,
    and the development SessionLocal raises if anything still reaches it. The
    routes commit, so the user tables are emptied before and after each test.
    """

    def get_test_db():
        session = Session(test_engine)
        try:
            yield session
        finally:
            session.close()

    def development_session_not_allowed():
        raise RuntimeError("API tests must not use the development database")

    monkeypatch.setattr(database, "SessionLocal", development_session_not_allowed)
    app.dependency_overrides[get_db] = get_test_db
    delete_user_rows(test_engine)
    try:
        yield PathUserClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        delete_user_rows(test_engine)


@pytest.fixture
def rollback_connection(test_engine):
    """Connection to the test database whose transaction is rolled back after the test."""
    with test_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


def rollback_connection_session(connection):
    """Session in the connection's transaction: its commits only release a savepoint."""
    return Session(bind=connection, join_transaction_mode="create_savepoint")


@pytest.fixture
def catalog_session(rollback_connection):
    """Session for adding the test data that catalog_client requests read.

    Nothing is committed, so the exercise catalog's seeded reference data stays
    as it is.
    """
    session = rollback_connection_session(rollback_connection)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def catalog_client(rollback_connection, monkeypatch):
    """TestClient for the read-only exercise catalog routes.

    Unlike client, it commits and deletes nothing: each request gets its own
    session in the transaction of catalog_session, so it reads the test data
    added there (once flushed), and the transaction is rolled back after the
    test. The development SessionLocal raises if anything still reaches it.
    """

    def get_test_db():
        session = rollback_connection_session(rollback_connection)
        try:
            yield session
        finally:
            session.close()

    def development_session_not_allowed():
        raise RuntimeError("API tests must not use the development database")

    monkeypatch.setattr(database, "SessionLocal", development_session_not_allowed)
    app.dependency_overrides[get_db] = get_test_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def catalog_exercise_ids(test_engine):
    """IDs of the seeded catalog exercises, by name."""
    with Session(test_engine) as session:
        return dict(session.execute(select(Exercise.name, Exercise.id)).all())


@pytest.fixture
def retirable_exercise_id(test_engine):
    """A committed, active catalog exercise that the test may retire.

    It is deleted afterwards, with the plan and session exercises that use it,
    because the catalog tests expect the catalog to hold only the seed.
    """
    with Session(test_engine) as session:
        exercise = Exercise(
            name="Test Retirable Exercise", difficulty="BEGINNER", movement_pattern="SQUAT"
        )
        session.add(exercise)
        session.commit()
        exercise_id = exercise.id
    try:
        yield exercise_id
    finally:
        with Session(test_engine) as session:
            session.execute(
                delete(WorkoutSessionExercise).where(
                    WorkoutSessionExercise.exercise_id == exercise_id
                )
            )
            session.execute(
                delete(WorkoutPlanExercise).where(WorkoutPlanExercise.exercise_id == exercise_id)
            )
            session.execute(delete(Exercise).where(Exercise.id == exercise_id))
            session.commit()


@pytest.fixture
def profile_fields():
    """Values for the required user profile fields."""
    return {
        "first_name": "Test",
        "age": 30,
        "height_cm": 175.0,
        "weight_kg": 70.0,
        "gender": "other",
        "fitness_experience": "beginner",
        "goal": "general_fitness",
        "training_frequency_per_week": 3,
        "training_location": "gym",
        "activity_level": "moderate",
        "sleep_hours": 7.5,
    }
