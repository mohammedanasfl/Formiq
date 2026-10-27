"""The profile service's equipment rules, with no database: the repositories are replaced by
plain objects. What the rows themselves do (the association table, its cascades, the
replacement over a real session) is in tests/integration/test_profile_equipment.py.
"""

from unittest.mock import Mock

import pytest
from sqlalchemy.sql.functions import now

from app.models import Equipment, UserProfile
from app.schemas import UserProfileCreate, UserProfileUpdate
from app.services.exceptions import InvalidEquipmentError, InvalidProfileUpdateError
from app.services.user_profile_service import (
    NOT_NULL_UPDATE_FIELDS,
    REQUIRED_PROFILE_FIELDS,
    SavedEquipment,
    UserProfileService,
)
from tests.unit.test_user_profile_schemas import VALID_PROFILE

USER_ID = 7
DUMBBELL = Equipment(id=1, name="Dumbbell", is_active=True)
BENCH = Equipment(id=2, name="Bench", is_active=True)
BAND = Equipment(id=3, name="Resistance Band", is_active=True)
RETIRED = Equipment(id=9, name="Old Machine", is_active=False)
CATALOG = {item.id: item for item in (DUMBBELL, BENCH, BAND, RETIRED)}


class FakeEquipment:
    """The catalog's equipment: what the repository's get_by_ids finds."""

    def __init__(self):
        self.asked = []

    def get_by_ids(self, ids):
        self.asked.append(sorted(ids))
        return [CATALOG[item_id] for item_id in sorted(ids) if item_id in CATALOG]


def service(profile=None):
    """The service over fakes, with this profile (or none) as the user's."""
    session = Mock()
    result = UserProfileService(session)
    result.users = Mock()
    result.profiles = Mock()
    result.profiles.get_by_user_id.return_value = profile
    result.profiles.create.side_effect = lambda created: created
    result.equipment = FakeEquipment()
    return result


def new_profile(equipment=(), no_equipment=False):
    return UserProfile(
        id=1,
        user_id=USER_ID,
        **VALID_PROFILE,
        no_equipment=no_equipment,
        equipment=list(equipment),
    )


def create(subject, **fields):
    subject.profiles.get_by_user_id.return_value = None
    return subject.create_profile(
        USER_ID, UserProfileCreate.model_validate({**VALID_PROFILE, **fields})
    )


# --- creating ---


def test_creating_a_profile_saves_the_equipment_it_chose():
    subject = service()

    profile = create(subject, equipment_ids=[BAND.id, DUMBBELL.id])

    assert profile.equipment == [BAND, DUMBBELL]
    assert profile.no_equipment is False
    subject.session.commit.assert_called_once()
    subject.session.rollback.assert_not_called()


def test_a_repeated_id_is_one_piece_of_equipment():
    subject = service()

    profile = create(subject, equipment_ids=[DUMBBELL.id, BENCH.id, DUMBBELL.id, DUMBBELL.id])

    # each once, in the order given, and the catalog is asked for each once
    assert profile.equipment == [DUMBBELL, BENCH]
    assert subject.equipment.asked == [[DUMBBELL.id, BENCH.id]]


def test_creating_a_profile_with_no_equipment_saves_that_and_no_rows():
    subject = service()

    profile = create(subject, no_equipment=True)

    assert profile.no_equipment is True
    assert profile.equipment == []


def test_creating_a_profile_that_says_nothing_of_equipment_keeps_it_unsaid():
    subject = service()

    profile = create(subject)

    assert profile.no_equipment is False
    assert profile.equipment == []


@pytest.mark.parametrize(
    ("ids", "problem"),
    [
        ([404], "equipment 404 is not in the catalog"),
        ([DUMBBELL.id, 404, 405], "equipment 404, 405 is not in the catalog"),
        ([RETIRED.id], "equipment 9 is retired"),
        ([404, RETIRED.id], "equipment 404 is not in the catalog; equipment 9 is retired"),
    ],
)
def test_equipment_the_catalog_does_not_have_or_has_retired_is_refused_and_nothing_is_saved(
    ids, problem
):
    subject = service()
    subject.profiles.get_by_user_id.return_value = None

    with pytest.raises(InvalidEquipmentError, match=problem):
        subject.create_profile(
            USER_ID, UserProfileCreate.model_validate({**VALID_PROFILE, "equipment_ids": ids})
        )

    subject.profiles.create.assert_not_called()
    subject.session.commit.assert_not_called()
    subject.session.rollback.assert_called_once()


# --- updating ---


def update(subject, profile, **fields):
    subject.profiles.get_by_user_id.return_value = profile
    return subject.update_profile(USER_ID, UserProfileUpdate.model_validate(fields))


def test_an_update_replaces_the_previous_selection():
    profile = new_profile([DUMBBELL, BENCH])
    subject = service(profile)

    update(subject, profile, equipment_ids=[BENCH.id, BAND.id])

    assert profile.equipment == [BENCH, BAND]
    assert profile.no_equipment is False
    subject.session.commit.assert_called_once()


def test_an_update_that_repeats_an_id_keeps_one_piece_of_it():
    profile = new_profile([DUMBBELL])
    subject = service(profile)

    update(subject, profile, equipment_ids=[BAND.id, BAND.id, BAND.id])

    assert profile.equipment == [BAND]


def test_an_empty_list_clears_what_was_chosen_without_saying_the_user_has_none():
    profile = new_profile([DUMBBELL, BENCH])
    subject = service(profile)

    update(subject, profile, equipment_ids=[])

    assert profile.equipment == []
    assert profile.no_equipment is False


def test_saying_none_leaves_nothing_listed():
    profile = new_profile([DUMBBELL, BENCH])
    subject = service(profile)

    update(subject, profile, no_equipment=True)

    assert profile.no_equipment is True
    assert profile.equipment == []


def test_choosing_equipment_after_saying_none_says_the_user_has_some():
    profile = new_profile(no_equipment=True)
    subject = service(profile)

    update(subject, profile, equipment_ids=[DUMBBELL.id])

    assert profile.no_equipment is False
    assert profile.equipment == [DUMBBELL]


def test_an_update_of_something_else_leaves_the_equipment_alone():
    profile = new_profile([DUMBBELL, BENCH])
    subject = service(profile)

    update(subject, profile, weight_kg=70.0)

    assert profile.weight_kg == 70.0
    assert profile.equipment == [DUMBBELL, BENCH]
    assert subject.equipment.asked == []


def test_an_update_of_something_else_does_not_say_the_user_has_equipment_or_none():
    profile = new_profile(no_equipment=True)
    subject = service(profile)

    update(subject, profile, goal="build_muscle")

    assert profile.no_equipment is True
    assert profile.equipment == []


def test_a_change_of_the_list_alone_updates_the_profile_s_time():
    profile = new_profile([DUMBBELL])
    profile.updated_at = None
    subject = service(profile)

    update(subject, profile, equipment_ids=[BENCH.id])

    # a change to the association rows touches no column of the row: the time is set
    assert str(profile.updated_at) == str(now())


def test_the_same_selection_changes_nothing_at_all():
    profile = new_profile([DUMBBELL, BENCH])
    profile.updated_at = None
    subject = service(profile)

    update(subject, profile, equipment_ids=[BENCH.id, DUMBBELL.id])

    assert profile.equipment == [DUMBBELL, BENCH]
    assert profile.updated_at is None


@pytest.mark.parametrize("ids", [[404], [RETIRED.id], [DUMBBELL.id, 404]])
def test_an_update_naming_unusable_equipment_is_refused_and_changes_nothing(ids):
    profile = new_profile([BENCH])
    subject = service(profile)

    with pytest.raises(InvalidEquipmentError):
        update(subject, profile, equipment_ids=ids, weight_kg=99.0)

    assert profile.equipment == [BENCH]
    assert profile.weight_kg == VALID_PROFILE["weight_kg"]
    subject.session.commit.assert_not_called()
    subject.session.rollback.assert_called_once()


@pytest.mark.parametrize("field", ["equipment_ids", "no_equipment"])
def test_the_equipment_fields_cannot_be_set_to_null(field):
    profile = new_profile([DUMBBELL])
    subject = service(profile)

    with pytest.raises(InvalidProfileUpdateError, match=field):
        update(subject, profile, **{field: None})

    assert profile.equipment == [DUMBBELL]
    subject.session.rollback.assert_called_once()


def test_the_null_checks_cover_the_equipment_fields():
    assert "no_equipment" in REQUIRED_PROFILE_FIELDS
    assert NOT_NULL_UPDATE_FIELDS == REQUIRED_PROFILE_FIELDS | {"equipment_ids"}


# --- what the coach reads ---


def saved(profile):
    return service(profile).get_saved_equipment(USER_ID)


def test_a_user_without_a_profile_has_said_nothing_of_their_equipment():
    assert saved(None) is None


def test_a_profile_that_never_said_has_said_nothing():
    assert saved(new_profile()) is None


def test_a_profile_that_lists_equipment_gives_its_names():
    assert saved(new_profile([DUMBBELL, BENCH])) == SavedEquipment(
        names=("Dumbbell", "Bench"), none=False
    )


def test_a_profile_with_no_equipment_says_so():
    assert saved(new_profile(no_equipment=True)) == SavedEquipment(names=(), none=True)


def test_equipment_retired_since_is_not_offered_to_the_coach():
    assert saved(new_profile([DUMBBELL, RETIRED])) == SavedEquipment(
        names=("Dumbbell",), none=False
    )


def test_a_profile_whose_every_piece_was_retired_has_said_nothing_now():
    # not "none": the user never said they have none
    assert saved(new_profile([RETIRED])) is None
