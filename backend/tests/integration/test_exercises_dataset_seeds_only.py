"""Importing the pinned exercises-dataset into a catalog that holds only Formiq's seeds
(the test database as it is): a dry run changes nothing and reports exactly what the
import then does, and the catalog API serves an UNRATED exercise of the new source.

These tests are kept apart from test_exercises_dataset_catalog.py on purpose. That module
holds one open transaction with the exercises imported in it for its whole run, and
exercises.name is unique: a second connection inserting the same names waits for that
transaction to end. Run in its own module, each test here starts after it was rolled back.

Every import runs in a transaction that is rolled back (the catalog_session fixture, in
conftest.py), and requires the local PostgreSQL container to be running.
"""

import pytest
from sqlalchemy import func, select

from app.catalog import exercises_dataset as ed
from app.models import Exercise
from tests.integration.exercises_dataset_helpers import (
    SOURCE,
    dataset_exercise,
    run_dataset_import,
    table_counts,
)


@pytest.fixture(scope="module")
def dataset_records():
    """The pinned file's records: refused if it is not the pinned file (its SHA-256)."""
    return ed.load_records()


@pytest.fixture(scope="module")
def no_images(tmp_path_factory):
    """An images directory with nothing in it: the dataset has no image to register."""
    return tmp_path_factory.mktemp("no-exercise-images")


def test_a_dry_run_changes_nothing_and_reports_what_the_import_then_does(
    catalog_session, dataset_records, no_images
):
    before = table_counts(catalog_session)
    assert before["exercises"] == catalog_session.scalar(
        select(func.count()).select_from(Exercise).where(Exercise.source == "FORMIQ")
    )

    dry = run_dataset_import(catalog_session, dataset_records, no_images, dry_run=True)

    assert dry.dry_run is True
    assert table_counts(catalog_session) == before
    assert not catalog_session.scalars(select(Exercise).where(Exercise.source == SOURCE)).all()
    # without free-exercise-db in the catalog, only Formiq's own seeds can hold a name
    assert (len(dry.imported), len(dry.skipped), len(dry.rejected)) == (724, 7, 593)
    assert all("Formiq's own" in reason for _, reason in dry.skipped)

    real = run_dataset_import(catalog_session, dataset_records, no_images)

    assert real.dry_run is False
    for name in (
        "imported",
        "updated",
        "unchanged",
        "skipped",
        "rejected",
        "unresolved",
        "unknown_fields",
        "incomplete",
        "images_registered",
        "images_missing",
        "not_in_source",
        "uses",
    ):
        assert getattr(real, name) == getattr(dry, name), name
    assert table_counts(catalog_session)["exercises"] == before["exercises"] + 724


def test_the_catalog_api_serves_an_unrated_exercise_of_the_new_source(
    catalog_session, catalog_client, dataset_records, no_images
):
    # a few of the records the mapper accepts
    accepted = {item.source_id for item in ed.parse_records(dataset_records).exercises[:5]}
    subset = [record for record in dataset_records if record["id"] in accepted]
    summary = run_dataset_import(catalog_session, subset, no_images)
    assert summary.imported
    exercise = dataset_exercise(catalog_session, summary.imported[0])
    record = next(r for r in dataset_records if r["id"] == exercise.source_id)

    detail = catalog_client.get(f"/exercises/{exercise.id}")
    listed = catalog_client.get("/exercises", params={"difficulty": "UNRATED"})

    assert detail.status_code == 200
    body = detail.json()
    assert (body["source"], body["difficulty"], body["source_id"]) == (
        SOURCE,
        "UNRATED",
        exercise.source_id,
    )
    assert body["source_version"] == ed.SOURCE_VERSION
    assert body["instructions"] == record["instruction_steps"]["en"]
    assert (body["images"], body["uses"], body["category"], body["description"]) == (
        [],
        [],
        None,
        None,
    )
    assert body["movement_pattern"] is None
    assert listed.status_code == 200
    assert exercise.id in {item["id"] for item in listed.json()}
    assert {item["difficulty"] for item in listed.json()} == {"UNRATED"}
    # the seeds are still served with their own levels
    everything = catalog_client.get("/exercises")
    assert everything.status_code == 200
    assert {"BEGINNER", "UNRATED"} <= {item["difficulty"] for item in everything.json()}
