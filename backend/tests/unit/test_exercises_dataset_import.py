"""The importer applying exercises-dataset's records, without a database.

The real ExerciseImportService runs over in-memory repositories (transient
models, and a mock session that counts commits and rollbacks), so what is
checked is the importer's own logic with this source's mapper: what it adds, what it
skips by name, that it is idempotent, that it changes nothing that exists, and that
an external id belongs to its source. The database side (constraints, a real
transaction, the API after the import) is tested in tests/integration with the
dry-run that comes next.

As a check on the harness, the same replay of free-exercise-db's import gives the
catalog docs/exercise-fields.md describes for the development database: 71 of
Formiq's own and 863 imported exercises (13 of 876 skipped by name).
"""

from unittest.mock import Mock

import pytest

from app.catalog import exercises_dataset as ed
from app.catalog import free_exercise_db
from app.models import Equipment, Exercise, MuscleGroup
from app.schemas.exercise import Difficulty, ExerciseSource, MuscleRole
from app.services.exercise_import_service import ExerciseImportService, comparable_name
from tests.migrations import (
    ACTIVITIES_REVISION,
    LATER_SEED_REVISION,
    SEED_REVISION,
    SOURCE_REVISION,
    TREADMILL_REVISION,
    migration_module,
)
from tests.unit.test_exercises_dataset import record


class InMemoryExercises:
    def __init__(self, rows):
        self.rows = rows

    def create(self, exercise):
        exercise.id = max((row.id for row in self.rows), default=0) + 1
        self.rows.append(exercise)
        return exercise

    def find_all(self):
        return list(self.rows)


class Reference:
    def __init__(self, items):
        self.items = items

    def find(self, **_):
        return list(self.items)


def reference_data():
    groups = set(migration_module(SEED_REVISION).MUSCLE_GROUPS)
    groups |= set(migration_module(SOURCE_REVISION).MUSCLE_GROUPS)
    names = set(migration_module(SEED_REVISION).EQUIPMENT)
    for revision in (LATER_SEED_REVISION, SOURCE_REVISION):
        names |= set(migration_module(revision).EQUIPMENT)
    names.add(migration_module(TREADMILL_REVISION).NAME)
    return (
        [MuscleGroup(id=i + 1, name=name) for i, name in enumerate(sorted(groups))],
        [Equipment(id=i + 1, name=name) for i, name in enumerate(sorted(names))],
    )


def formiqs_own():
    names = [e["name"] for e in migration_module(SEED_REVISION).EXERCISES]
    names += [e["name"] for e in migration_module(LATER_SEED_REVISION).EXERCISES]
    names += [e["name"] for e in migration_module(ACTIVITIES_REVISION).NEW_ACTIVITIES]
    return [
        Exercise(
            id=index + 1,
            name=name,
            source=ExerciseSource.FORMIQ,
            difficulty="BEGINNER",
            uses=[],
            image_paths=[],
        )
        for index, name in enumerate(names)
    ]


class Catalog:
    """An in-memory catalog and the importer over it."""

    def __init__(self, rows, tmp_path):
        self.rows = rows
        self.session = Mock()
        self.images_dir = tmp_path
        self.groups, self.equipment = reference_data()

    def run(self, dataset, *, dry_run=False, records=None):
        records = dataset.load_records() if records is None else records
        service = ExerciseImportService(self.session)
        service.exercises = InMemoryExercises(self.rows)
        service.muscle_groups = Reference(self.groups)
        service.equipment = Reference(self.equipment)
        return service.import_source(
            dataset.parse_records(records),
            source=dataset.SOURCE,
            version=dataset.SOURCE_VERSION,
            discovered=len(records),
            images_dir=self.images_dir,
            dry_run=dry_run,
        )

    def of(self, source):
        return [row for row in self.rows if row.source == source]


@pytest.fixture
def catalog(tmp_path):
    return Catalog(formiqs_own(), tmp_path)


@pytest.fixture
def fresh(tmp_path):
    """An empty catalog, for a few synthetic records."""
    return Catalog([], tmp_path)


@pytest.fixture
def imported(catalog):
    """Formiq's own and free-exercise-db's exercises, as the development database holds them."""
    catalog.run(free_exercise_db)
    # what the session saw for that setup is not what the test is about
    catalog.session.reset_mock()
    return catalog


def state(row):
    return (
        row.id,
        row.name,
        row.source,
        row.source_id,
        row.source_version,
        row.difficulty,
        row.description,
        row.movement_pattern,
        tuple(row.uses),
        tuple(row.image_paths),
        repr(row.source_record),
        tuple((link.muscle_group_id, link.role) for link in row.muscles),
        tuple(item.id for item in row.equipment),
    )


def test_the_replay_of_free_exercise_dbs_import_gives_the_catalog_the_docs_describe(catalog):
    summary = catalog.run(free_exercise_db)

    assert (len(summary.imported), len(summary.skipped), len(summary.rejected)) == (863, 13, 0)
    assert len(catalog.rows) == 934


def test_the_first_import_adds_what_is_new_and_skips_what_the_catalog_has(imported):
    before = len(imported.rows)

    summary = imported.run(ed)

    assert (summary.source, summary.version) == ("EXERCISES_DATASET", ed.SOURCE_VERSION)
    assert summary.discovered == 1324
    assert len(summary.imported) == 647
    assert (len(summary.updated), len(summary.unchanged)) == (0, 0)
    # the 731 the mapper accepts: 647 new, 84 the catalog already has by name
    assert len(summary.skipped) == 84
    owners = [reason.split(" exercise ")[0] for _, reason in summary.skipped]
    assert owners.count("the catalog already has Formiq's own") == 7
    assert owners.count("the catalog already has another") == 77
    assert len(summary.rejected) == 593
    assert "catalog" not in summary.unresolved
    assert len(imported.rows) == before + 647
    assert len(imported.of(ExerciseSource.EXERCISES_DATASET)) == 647
    # the images are never registered or looked for
    assert (summary.images_registered, summary.images_missing) == (0, 0)


def test_what_is_imported_is_the_provenance_and_nothing_made_up(imported):
    imported.run(ed)

    for row in imported.of(ExerciseSource.EXERCISES_DATASET):
        assert row.source_id == row.source_record["id"]
        assert row.source_version == ed.SOURCE_VERSION
        assert row.difficulty == Difficulty.UNRATED
        assert row.uses == []
        assert row.image_paths == []
        assert row.movement_pattern is None
        assert row.description is None
        assert row.is_active is not False
        assert set(row.source_record["instruction_steps"]) == {"en"}
        assert row.instructions == row.source_record["instruction_steps"]["en"] != []
        assert row.category is None


def test_the_links_are_the_tables_and_the_primary_muscle_comes_first(imported):
    imported.run(ed)
    groups = {group.id: group.name for group in imported.groups}
    rows = {row.source_id: row for row in imported.of(ExerciseSource.EXERCISES_DATASET)}

    # body weight, with nothing in its text that says otherwise
    side_bend = rows["0002"]
    assert side_bend.name == "45° Side Bend"
    assert side_bend.equipment == []
    primary = [groups[link.muscle_group_id] for link in side_bend.muscles if link.role == "PRIMARY"]
    assert primary == ["Core"]
    # each kind of equipment gets the catalog's item
    seen = {tuple(item.name for item in row.equipment) for row in rows.values()}
    assert seen == {
        (),
        ("Cable Machine",),
        ("Dumbbell",),
        ("Machine",),
        ("Barbell",),
        ("Resistance Band",),
        ("Kettlebell",),
        ("Smith Machine",),
        ("Other Equipment",),
        ("Exercise Ball",),
        ("Medicine Ball",),
        ("EZ Curl Bar",),
    }
    for row in rows.values():
        roles = [link.role for link in row.muscles]
        assert roles.count(MuscleRole.PRIMARY) == 1
        assert roles[0] == MuscleRole.PRIMARY


def test_no_name_is_in_the_catalog_twice(imported):
    imported.run(ed)

    names = [comparable_name(row.name) for row in imported.rows]
    assert len(names) == len(set(names))


def test_a_held_record_never_reaches_the_catalog(imported):
    records = ed.load_records()
    held = {item.source_id for item in ed.parse_records(records).rejected}
    assert len(held) == 593

    imported.run(ed)

    present = {row.source_id for row in imported.of(ExerciseSource.EXERCISES_DATASET)}
    assert not held & present


def test_running_it_again_changes_nothing(imported):
    first = imported.run(ed)
    after_first = [state(row) for row in imported.rows]

    second = imported.run(ed)

    assert (len(second.imported), len(second.updated), len(second.skipped)) == (0, 0, 84)
    assert len(second.unchanged) == len(first.imported) == 647
    assert [state(row) for row in imported.rows] == after_first


def test_nothing_that_exists_is_changed(imported):
    before = [state(row) for row in imported.rows]

    imported.run(ed)

    # every earlier exercise, Formiq's own and free-exercise-db's, is as it was, with its id
    assert [state(row) for row in imported.rows[: len(before)]] == before
    assert [row.id for row in imported.rows] == list(range(1, len(imported.rows) + 1))


def test_a_dry_run_reports_what_the_import_would_do_and_commits_nothing(imported):
    summary = imported.run(ed, dry_run=True)

    assert (len(summary.imported), len(summary.skipped), len(summary.rejected)) == (647, 84, 593)
    assert summary.dry_run is True
    imported.session.rollback.assert_called_once_with()
    imported.session.commit.assert_not_called()


def test_a_real_import_commits_once(imported):
    imported.run(ed)

    imported.session.commit.assert_called_once_with()
    imported.session.rollback.assert_not_called()


def test_a_failure_rolls_back_and_is_raised(imported):
    imported.groups = []  # the catalog lacks every muscle group: every record is rejected
    summary = imported.run(ed, dry_run=True)
    assert len(summary.imported) == 0
    assert summary.unresolved["catalog"]

    class Failing(InMemoryExercises):
        def create(self, exercise):
            raise RuntimeError("the database is gone")

    imported.groups, _ = reference_data()
    service = ExerciseImportService(imported.session)
    service.exercises = Failing(imported.rows)
    service.muscle_groups = Reference(imported.groups)
    service.equipment = Reference(imported.equipment)
    imported.session.reset_mock()
    with pytest.raises(RuntimeError, match="the database is gone"):
        service.import_source(
            ed.parse_records(ed.load_records()),
            source=ed.SOURCE,
            version=ed.SOURCE_VERSION,
            discovered=1324,
            images_dir=imported.images_dir,
            dry_run=False,
        )
    imported.session.rollback.assert_called_once_with()
    imported.session.commit.assert_not_called()


def test_a_name_formiq_already_has_is_skipped_and_the_existing_exercise_is_kept(fresh):
    own = Exercise(
        id=1, name="Air Squat", source=ExerciseSource.FORMIQ, difficulty="BEGINNER",
        uses=["MAIN_WORKOUT"], image_paths=[], description="Formiq's own",
    )  # fmt: skip
    fresh.rows.append(own)

    summary = fresh.run(ed, records=[record(name="air  squat")])

    assert summary.imported == []
    assert summary.skipped == [
        ("0001", "the catalog already has Formiq's own exercise 'Air Squat' (id 1)")
    ]
    assert fresh.rows == [own]
    assert (own.description, own.uses) == ("Formiq's own", ["MAIN_WORKOUT"])


def test_an_external_id_belongs_to_its_source(fresh):
    # free-exercise-db's ids are names; one that equals this source's id is another exercise
    other = Exercise(
        id=1, name="Old Thing", source=ExerciseSource.FREE_EXERCISE_DB, source_id="0001",
        difficulty="BEGINNER", uses=[], image_paths=[], source_record={"instructions": ["Old."]},
    )  # fmt: skip
    fresh.rows.append(other)
    before = state(other)

    summary = fresh.run(ed, records=[record(id="0001", name="air squat")])

    assert summary.imported == ["0001"]
    assert state(other) == before
    (new,) = fresh.of(ExerciseSource.EXERCISES_DATASET)
    assert (new.id, new.source_id, new.name) == (2, "0001", "Air Squat")
    # and each reads its own steps
    assert other.instructions == ["Old."]
    assert new.instructions == record()["instruction_steps"]["en"]


def test_a_record_that_changed_is_updated_in_place_and_keeps_its_id(fresh):
    fresh.run(ed, records=[record()])
    (row,) = fresh.rows
    original_id = row.id

    summary = fresh.run(ed, records=[record(secondary_muscles=["glutes"])])

    assert summary.updated == ["0001"]
    assert fresh.rows == [row]
    assert row.id == original_id
    assert row.source_record["secondary_muscles"] == ["glutes"]
    assert len(row.muscles) == 2  # the primary and one secondary


def test_a_record_no_longer_in_the_source_is_reported_and_kept(fresh):
    fresh.run(ed, records=[record(), record(id="0002", name="push up on the floor")])

    summary = fresh.run(ed, records=[record()])

    assert summary.not_in_source == ["0002"]
    assert {row.source_id for row in fresh.rows} == {"0001", "0002"}
