from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.db.database import SessionLocal

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture(scope="session")
def migrated_database():
    command.upgrade(Config(str(ALEMBIC_INI)), "head")


@pytest.fixture
def db_session(migrated_database):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


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
