"""The import command's choice of source (python -m app.cli import-exercises
--source): free-exercise-db stays the default, exercises-dataset is chosen by
name, and the importer is given the right dataset, version and flags. No
database: the session and the importer are replaced, so nothing is opened or
written.
"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app import cli
from app.catalog import exercises_dataset, free_exercise_db
from app.catalog.free_exercise_db import ParsedSource, SourceFileError
from app.schemas.exercise import ExerciseSource
from app.services.exercise_import_service import ImportSummary


@pytest.fixture
def importer(monkeypatch):
    """The importer, recording what it was asked to import; no session is opened."""
    calls = []
    session = object()

    @contextmanager
    def session_local():
        yield session

    class RecordingImporter:
        def __init__(self, given):
            assert given is session
            self.session = given

        def import_source(self, parsed, *, source, version, discovered, images_dir, dry_run):
            calls.append(
                SimpleNamespace(
                    parsed=parsed,
                    source=source,
                    version=version,
                    discovered=discovered,
                    images_dir=images_dir,
                    dry_run=dry_run,
                )
            )
            return ImportSummary(
                source=source,
                version=version,
                dry_run=dry_run,
                discovered=discovered,
                imported=[item.source_id for item in parsed.exercises],
                rejected=[
                    (item.source_id or "?", "; ".join(item.reasons)) for item in parsed.rejected
                ],
            )

    monkeypatch.setattr(cli, "SessionLocal", session_local)
    monkeypatch.setattr(cli, "ExerciseImportService", RecordingImporter)
    return calls


def test_the_default_source_is_free_exercise_db_and_is_unchanged(importer, capsys):
    cli.main(["import-exercises", "--dry-run"])

    (call,) = importer
    assert call.source == ExerciseSource.FREE_EXERCISE_DB
    assert call.version == free_exercise_db.SOURCE_VERSION
    assert call.discovered == 876
    assert call.dry_run is True
    assert isinstance(call.parsed, ParsedSource)
    assert len(call.parsed.exercises) == 876
    assert call.images_dir == cli.settings.exercise_images_dir
    assert "DRY RUN, nothing was changed: FREE_EXERCISE_DB at f00c92c7" in capsys.readouterr().out


def test_free_exercise_db_can_also_be_named(importer):
    cli.main(["import-exercises", "--source", "free-exercise-db"])

    (call,) = importer
    assert (call.source, call.dry_run) == (ExerciseSource.FREE_EXERCISE_DB, False)


def test_exercises_dataset_is_chosen_by_name(importer, capsys):
    cli.main(["import-exercises", "--source", "exercises-dataset", "--dry-run"])

    (call,) = importer
    assert call.source == ExerciseSource.EXERCISES_DATASET
    assert call.version == exercises_dataset.SOURCE_VERSION
    assert call.discovered == 1324
    assert call.dry_run is True
    assert (len(call.parsed.exercises), len(call.parsed.rejected)) == (731, 593)
    # no image directory is read for it: nothing it imports has an image
    assert all(item.image_paths == [] for item in call.parsed.exercises)
    output = capsys.readouterr().out
    assert "DRY RUN, nothing was changed: EXERCISES_DATASET at 7455efae41b3" in output
    assert "    by reason: ambiguous equipment: 495" in output
    assert "    by reason: unmapped primary muscle: 53" in output


def test_an_unknown_source_is_refused_before_anything_is_read(importer, capsys):
    with pytest.raises(SystemExit) as stopped:
        cli.main(["import-exercises", "--source", "wger"])

    assert stopped.value.code == 2
    assert importer == []
    assert "invalid choice: 'wger'" in capsys.readouterr().err


def test_the_sources_are_the_two_datasets_and_the_default_is_the_first():
    assert cli.SOURCES == {
        "free-exercise-db": free_exercise_db,
        "exercises-dataset": exercises_dataset,
    }
    assert cli.DEFAULT_SOURCE == "free-exercise-db"
    # each has what the command reads
    for dataset in cli.SOURCES.values():
        for name in ("load_records", "parse_records", "SOURCE", "SOURCE_VERSION"):
            assert hasattr(dataset, name)


def test_a_dataset_file_that_is_not_the_pinned_one_imports_nothing(importer, monkeypatch):
    def refuse():
        raise SourceFileError("exercises.json is not the pinned dataset file")

    stub = SimpleNamespace(load_records=refuse, SOURCE=None, SOURCE_VERSION=None)
    monkeypatch.setitem(cli.SOURCES, "exercises-dataset", stub)

    with pytest.raises(SystemExit) as stopped:
        cli.main(["import-exercises", "--source", "exercises-dataset"])

    assert str(stopped.value) == "Nothing imported: exercises.json is not the pinned dataset file."
    assert importer == []


# --- the report ---


def test_rejections_are_counted_once_per_record_by_the_kind_of_reason():
    rejected = [
        ("0001", "invalid record: id; ambiguous equipment: bench"),
        ("0002", "ambiguous equipment: pole; ambiguous equipment: bar"),
        ("0003", "no colon in this one"),
    ]

    assert cli.rejected_by_reason(rejected) == [
        "    by reason: ambiguous equipment: 2",
        "    by reason: invalid record: 1",
        "    by reason: no colon in this one: 1",
    ]
    assert cli.rejected_by_reason([]) == []


def summary(rejected):
    return ImportSummary(
        source="EXERCISES_DATASET",
        version="7455efae41b3",
        dry_run=True,
        discovered=3,
        rejected=rejected,
    )


def test_a_report_with_nothing_rejected_has_no_reason_lines():
    text = cli.report(summary([]))

    assert "  rejected:   0" in text
    assert "by reason" not in text


def test_a_report_lists_the_counts_before_the_records():
    text = cli.report(summary([("0001", "ambiguous equipment: bench")])).splitlines()

    index = text.index("  rejected:   1")
    assert text[index + 1] == "    by reason: ambiguous equipment: 1"
    assert text[index + 2] == "    0001: ambiguous equipment: bench"
