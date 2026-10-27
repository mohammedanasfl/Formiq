"""The equipment a profile carries: chosen by catalog id, or none at all, never both.

The three states a profile can be in are told apart by the request alone: some ids
(the user chose these pieces), no_equipment (bodyweight only), or neither (the user
never said: every profile made before equipment was kept, and anyone who skipped the
step).
"""

import pytest
from pydantic import ValidationError

from app.schemas import UserProfileCreate, UserProfileUpdate
from app.schemas.user_profile import NO_EQUIPMENT_WITH_EQUIPMENT
from tests.unit.test_user_profile_schemas import VALID_PROFILE


def create(**equipment):
    return UserProfileCreate.model_validate({**VALID_PROFILE, **equipment})


def test_a_profile_without_equipment_says_nothing_of_it():
    profile = create()

    assert profile.equipment_ids == []
    assert profile.no_equipment is False


def test_a_profile_may_choose_catalog_equipment_by_id():
    assert create(equipment_ids=[3, 1, 7]).equipment_ids == [3, 1, 7]


def test_a_profile_may_say_it_has_no_equipment():
    profile = create(no_equipment=True)

    assert profile.no_equipment is True
    assert profile.equipment_ids == []


def test_no_equipment_and_equipment_together_are_refused():
    with pytest.raises(ValidationError, match=NO_EQUIPMENT_WITH_EQUIPMENT):
        create(no_equipment=True, equipment_ids=[1])


def test_choosing_equipment_and_saying_not_none_is_fine():
    assert create(no_equipment=False, equipment_ids=[1]).equipment_ids == [1]


@pytest.mark.parametrize("bad", [[0], [-1], ["dumbbell"], [1.5], "1", 1])
def test_equipment_ids_must_be_a_list_of_positive_ids(bad):
    with pytest.raises(ValidationError):
        create(equipment_ids=bad)


def test_equipment_names_are_not_ids():
    # the catalog's names are for people: what is saved is the id
    with pytest.raises(ValidationError):
        create(equipment_ids=["Dumbbell"])


def test_the_list_is_bounded_but_repeats_are_the_service_s_to_collapse():
    assert create(equipment_ids=[2] * 100).equipment_ids == [2] * 100
    with pytest.raises(ValidationError):
        create(equipment_ids=[2] * 101)


def test_an_update_that_says_nothing_of_equipment_changes_none_of_it():
    update = UserProfileUpdate.model_validate({"weight_kg": 70.0})

    assert update.model_dump(exclude_unset=True) == {"weight_kg": 70.0}


def test_an_update_may_replace_the_equipment_or_say_none():
    assert UserProfileUpdate(equipment_ids=[4]).model_dump(exclude_unset=True) == {
        "equipment_ids": [4]
    }
    assert UserProfileUpdate(no_equipment=True).model_dump(exclude_unset=True) == {
        "no_equipment": True
    }
    # an empty list says the user chose nothing: it is told apart from leaving it out
    assert UserProfileUpdate(equipment_ids=[]).model_dump(exclude_unset=True) == {
        "equipment_ids": []
    }


def test_an_update_refuses_no_equipment_with_equipment_too():
    with pytest.raises(ValidationError, match=NO_EQUIPMENT_WITH_EQUIPMENT):
        UserProfileUpdate(no_equipment=True, equipment_ids=[1])
    # leaving the list empty with it is the same as leaving it out
    assert UserProfileUpdate(no_equipment=True, equipment_ids=[]).no_equipment is True


def test_an_update_carries_a_null_to_the_service_which_refuses_it():
    # the schema reads nulls for every field; the service says which cannot be null
    changes = UserProfileUpdate.model_validate({"equipment_ids": None}).model_dump(
        exclude_unset=True
    )

    assert changes == {"equipment_ids": None}
