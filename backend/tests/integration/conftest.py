from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import User, UserProfile
from tests.integration.database import check_test_database_url

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


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
