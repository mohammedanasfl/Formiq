"""Integration tests for the exercise catalog migrations.

They require the local PostgreSQL container to be running. They upgrade and
downgrade the test database (TEST_DATABASE_URL), and leave it at head. The
schema/model consistency check (alembic check) is test_models_match_migrations
in test_users_migration.py.
"""

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select, table
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.models import Equipment, Exercise, MuscleGroup, User, UserProfile
from app.schemas import ExerciseResponse

# The Phase 2 head, before the exercise catalog.
REVISION_BEFORE_CATALOG = "4e447bdd5061"
# The revision that creates the catalog tables, before the seed data.
CATALOG_TABLES_REVISION = "0d243d0e46b1"
SEED_REVISION = "b84c61ea69bf"

TIMESTAMPTZ = "TIMESTAMP WITH TIME ZONE"
REFERENCE_COLUMNS = {
    "id": "INTEGER",
    "name": "VARCHAR(100)",
    "description": "TEXT",
    "is_active": "BOOLEAN",
    "created_at": TIMESTAMPTZ,
    "updated_at": TIMESTAMPTZ,
}

# For each catalog table: column types, nullable columns and primary key.
CATALOG_TABLES = {
    "exercises": (
        {
            "id": "INTEGER",
            "name": "VARCHAR(150)",
            "description": "TEXT",
            "difficulty": "VARCHAR(20)",
            "movement_pattern": "VARCHAR(30)",
            "is_active": "BOOLEAN",
            "created_at": TIMESTAMPTZ,
            "updated_at": TIMESTAMPTZ,
        },
        {"description"},
        ["id"],
    ),
    "muscle_groups": (REFERENCE_COLUMNS, {"description"}, ["id"]),
    "equipment": (REFERENCE_COLUMNS, {"description"}, ["id"]),
    "exercise_muscles": (
        {"exercise_id": "INTEGER", "muscle_group_id": "INTEGER", "role": "VARCHAR(20)"},
        set(),
        ["exercise_id", "muscle_group_id"],
    ),
    "exercise_equipment": (
        {"exercise_id": "INTEGER", "equipment_id": "INTEGER"},
        set(),
        ["exercise_id", "equipment_id"],
    ),
}

# (table, column, referred table, ON DELETE rule)
FOREIGN_KEYS = {
    ("exercise_muscles", "exercise_id", "exercises", "CASCADE"),
    ("exercise_muscles", "muscle_group_id", "muscle_groups", "RESTRICT"),
    ("exercise_equipment", "exercise_id", "exercises", "CASCADE"),
    ("exercise_equipment", "equipment_id", "equipment", "RESTRICT"),
}


# The muscle groups and equipment that Phase 3.1 requires in the seed.
REQUIRED_MUSCLE_GROUPS = {
    "Chest",
    "Upper Back",
    "Lats",
    "Shoulders",
    "Front Deltoid",
    "Rear Deltoid",
    "Biceps",
    "Triceps",
    "Forearms",
    "Core",
    "Obliques",
    "Glutes",
    "Quadriceps",
    "Hamstrings",
    "Calves",
}

REQUIRED_EQUIPMENT = {
    "Barbell",
    "Dumbbell",
    "Bench",
    "Cable Machine",
    "Pull-up Bar",
    "Resistance Band",
    "Kettlebell",
    "Smith Machine",
    "Leg Press Machine",
}


@pytest.fixture
def alembic_config(test_alembic_config):
    command.upgrade(test_alembic_config, "head")
    yield test_alembic_config
    command.upgrade(test_alembic_config, "head")


@pytest.fixture
def seed(alembic_config):
    """The seed migration module, with its MUSCLE_GROUPS, EQUIPMENT and EXERCISES."""
    return ScriptDirectory.from_config(alembic_config).get_revision(SEED_REVISION).module


def table_names(engine):
    return set(inspect(engine).get_table_names())


def row_counts(engine):
    with Session(engine) as session:
        return {
            name: session.scalar(select(func.count()).select_from(table(name)))
            for name in CATALOG_TABLES
        }


def test_catalog_migrations_follow_the_phase_2_head(alembic_config):
    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_revision(CATALOG_TABLES_REVISION).down_revision == REVISION_BEFORE_CATALOG
    assert script.get_revision(SEED_REVISION).down_revision == CATALOG_TABLES_REVISION
    assert script.get_current_head() == SEED_REVISION


def test_upgrade_creates_the_catalog_tables(alembic_config, test_engine):
    assert set(CATALOG_TABLES) <= table_names(test_engine)


@pytest.mark.parametrize("table_name", CATALOG_TABLES)
def test_catalog_table_has_expected_columns(alembic_config, test_engine, table_name):
    column_types, nullable, primary_key = CATALOG_TABLES[table_name]
    inspector = inspect(test_engine)
    columns = inspector.get_columns(table_name)

    assert {
        column["name"]: column["type"].compile(dialect=postgresql.dialect()) for column in columns
    } == column_types
    assert {column["name"] for column in columns if column["nullable"]} == nullable
    assert inspector.get_pk_constraint(table_name)["constrained_columns"] == primary_key
    defaults = {column["name"]: column["default"] for column in columns}
    if "is_active" in defaults:
        assert defaults["is_active"] == "true"


@pytest.mark.parametrize("table_name", ["exercises", "muscle_groups", "equipment"])
def test_catalog_names_are_unique(alembic_config, test_engine, table_name):
    unique_constraints = inspect(test_engine).get_unique_constraints(table_name)

    assert [c["column_names"] for c in unique_constraints] == [["name"]]


def test_link_tables_reference_the_catalog_with_deliberate_delete_rules(
    alembic_config, test_engine
):
    inspector = inspect(test_engine)
    foreign_keys = {
        (table_name, *key["constrained_columns"], key["referred_table"], key["options"]["ondelete"])
        for table_name in ["exercise_muscles", "exercise_equipment"]
        for key in inspector.get_foreign_keys(table_name)
        if key["referred_columns"] == ["id"]
    }

    assert foreign_keys == FOREIGN_KEYS


@pytest.mark.parametrize(
    ("table_name", "column"),
    [("exercise_muscles", "muscle_group_id"), ("exercise_equipment", "equipment_id")],
)
def test_link_tables_index_the_second_key_column(alembic_config, test_engine, table_name, column):
    # the primary key index starts with exercise_id; this one finds the
    # exercises for a muscle group or a piece of equipment
    indexes = inspect(test_engine).get_indexes(table_name)

    assert [(index["column_names"], index["unique"]) for index in indexes] == [([column], False)]


def test_seed_adds_the_reference_data(alembic_config, seed, db_session):
    muscle_groups = db_session.scalars(select(MuscleGroup)).all()
    equipment = db_session.scalars(select(Equipment)).all()
    exercises = db_session.scalars(select(Exercise)).all()

    # the catalog tests never commit, so the test database holds only the seed
    assert {row.name: row.description for row in muscle_groups} == seed.MUSCLE_GROUPS
    assert {row.name: row.description for row in equipment} == seed.EQUIPMENT
    assert {
        row.name: {
            "name": row.name,
            "description": row.description,
            "difficulty": row.difficulty,
            "movement_pattern": row.movement_pattern,
            "muscles": {link.muscle_group.name: link.role for link in row.muscles},
            "equipment": sorted(item.name for item in row.equipment),
        }
        for row in exercises
    } == {
        exercise["name"]: {**exercise, "equipment": sorted(exercise["equipment"])}
        for exercise in seed.EXERCISES
    }
    assert all(row.is_active for row in [*muscle_groups, *equipment, *exercises])


def test_seed_includes_the_required_reference_data(alembic_config, db_session):
    assert REQUIRED_MUSCLE_GROUPS <= set(db_session.scalars(select(MuscleGroup.name)))
    assert REQUIRED_EQUIPMENT <= set(db_session.scalars(select(Equipment.name)))


def test_seeded_exercises_are_valid_catalog_entries(alembic_config, db_session):
    exercises = db_session.scalars(select(Exercise)).all()

    assert exercises
    for exercise in exercises:
        response = ExerciseResponse.model_validate(exercise)  # values within the enums
        assert "PRIMARY" in [muscle.role for muscle in response.muscles], exercise.name


def test_running_the_seed_again_adds_no_duplicates(alembic_config, test_engine):
    before = row_counts(test_engine)

    # mark the seed as not applied while its rows are still there, then run it again
    command.stamp(alembic_config, CATALOG_TABLES_REVISION)
    command.upgrade(alembic_config, "head")

    assert row_counts(test_engine) == before


def test_seed_downgrade_removes_the_reference_data_and_upgrade_restores_it(
    alembic_config, test_engine
):
    before = row_counts(test_engine)

    command.downgrade(alembic_config, CATALOG_TABLES_REVISION)
    assert row_counts(test_engine) == dict.fromkeys(CATALOG_TABLES, 0)

    command.upgrade(alembic_config, "head")
    assert row_counts(test_engine) == before


def test_downgrade_to_phase_2_keeps_users_and_upgrade_recreates_the_catalog(
    alembic_config, test_engine, service_session, profile_fields
):
    user = User(email="catalog-migration@example.com")
    service_session.add(UserProfile(user=user, **profile_fields))
    service_session.flush()
    user_id = user.id
    service_session.commit()
    seeded = row_counts(test_engine)

    command.downgrade(alembic_config, REVISION_BEFORE_CATALOG)
    assert not set(CATALOG_TABLES) & table_names(test_engine)
    with Session(test_engine) as session:
        assert session.get(User, user_id).profile.first_name == profile_fields["first_name"]

    command.upgrade(alembic_config, "head")
    assert set(CATALOG_TABLES) <= table_names(test_engine)
    assert row_counts(test_engine) == seeded
    with Session(test_engine) as session:
        assert session.get(User, user_id).profile.first_name == profile_fields["first_name"]
