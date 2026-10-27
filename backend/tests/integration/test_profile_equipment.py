"""Integration tests for the equipment a profile keeps: persisted by catalog id (or none at all),
returned with the profile, replaced by an update, and what the coach reads from it.

They require the local PostgreSQL container to be running, and migrations up to
e5b3a96c1f48 applied to the disposable test database (the fixtures upgrade it to head). The
client and service fixtures empty the user tables before and after each test; the equipment
catalog is the seed's, and is only read (apart from one retired piece, added and removed by
retired_equipment).
"""

from datetime import datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Equipment, UserProfile, user_profile_equipment
from app.schemas import UserCreate, UserProfileCreate, UserProfileUpdate
from app.services import CoachService, UserProfileService, UserService
from app.services.exceptions import InvalidEquipmentError
from app.services.user_profile_service import SavedEquipment
from tests.coach import call, fake_provider, respond_turn, sent_contents, tool_responses, tool_turn
from tests.integration.database import assert_disposable
from tests.integration.users import create_user

URL = "/users/{}/profile"


@pytest.fixture
def pieces(test_engine):
    """Three active catalog equipment (id, name), by name."""
    with Session(test_engine) as session:
        found = session.scalars(
            select(Equipment).where(Equipment.is_active).order_by(Equipment.name).limit(3)
        ).all()
        assert len(found) == 3
        return [(item.id, item.name) for item in found]


@pytest.fixture
def retired_equipment(test_engine):
    """The id of a committed catalog piece that is retired (is_active false), removed afterwards.
    Requested before client, so it goes after the user rows do."""
    with Session(test_engine) as session:
        assert_disposable(session.connection())
        item = Equipment(name="Retired Test Gear", is_active=False)
        session.add(item)
        session.commit()
        item_id = item.id
    try:
        yield item_id
    finally:
        with Session(test_engine) as session:
            assert_disposable(session.connection())
            session.execute(delete(Equipment).where(Equipment.id == item_id))
            session.commit()


@pytest.fixture
def user_id(client, test_engine):
    return create_user(test_engine, email="equipment-profile@example.com")


def stored_ids(engine, profile_id):
    """The equipment ids stored for the profile, one entry per association row."""
    with Session(engine) as session:
        return sorted(
            session.scalars(
                select(user_profile_equipment.c.equipment_id).where(
                    user_profile_equipment.c.user_profile_id == profile_id
                )
            )
        )


def create(client, user_id, profile_fields, **equipment):
    return client.post(URL.format(user_id), json={**profile_fields, **equipment})


# --- creating and reading ---


def test_creating_a_profile_persists_the_equipment_it_chose(
    client, test_engine, user_id, profile_fields, pieces
):
    (first, first_name), (second, second_name), _ = pieces

    response = create(client, user_id, profile_fields, equipment_ids=[second, first])

    assert response.status_code == 201
    body = response.json()
    assert body["no_equipment"] is False
    # by name, as the catalog lists it, each with its id
    assert body["equipment"] == [
        {"id": first, "name": first_name},
        {"id": second, "name": second_name},
    ]
    assert stored_ids(test_engine, body["id"]) == sorted([first, second])


def test_reading_the_profile_returns_the_persisted_selection(
    client, user_id, profile_fields, pieces
):
    ids = [pieces[0][0], pieces[2][0]]
    created = create(client, user_id, profile_fields, equipment_ids=ids).json()

    read = client.get(URL.format(user_id)).json()

    assert read == created
    assert [item["id"] for item in read["equipment"]] == ids
    assert read["no_equipment"] is False


def test_a_profile_made_without_equipment_says_nothing_of_it(
    client, test_engine, user_id, profile_fields
):
    response = create(client, user_id, profile_fields)

    assert response.status_code == 201
    body = response.json()
    assert (body["equipment"], body["no_equipment"]) == ([], False)
    assert stored_ids(test_engine, body["id"]) == []


def test_creating_a_profile_with_no_equipment_is_kept_and_returned(
    client, test_engine, user_id, profile_fields
):
    created = create(client, user_id, profile_fields, no_equipment=True).json()

    read = client.get(URL.format(user_id)).json()

    assert (read["no_equipment"], read["equipment"]) == (True, [])
    assert read == created
    assert stored_ids(test_engine, created["id"]) == []


def test_a_repeated_id_makes_one_association(client, test_engine, user_id, profile_fields, pieces):
    piece = pieces[0][0]

    body = create(client, user_id, profile_fields, equipment_ids=[piece, piece, piece]).json()

    assert [item["id"] for item in body["equipment"]] == [piece]
    assert stored_ids(test_engine, body["id"]) == [piece]


def test_no_equipment_together_with_equipment_is_refused(
    client, test_engine, user_id, profile_fields, pieces
):
    response = create(
        client, user_id, profile_fields, no_equipment=True, equipment_ids=[pieces[0][0]]
    )

    assert response.status_code == 422
    assert client.get(URL.format(user_id)).status_code == 404


# --- invalid equipment ---


@pytest.mark.parametrize("ids", [[999_999], [1, 999_999]])
def test_an_equipment_id_the_catalog_does_not_have_is_refused_and_no_profile_is_made(
    client, user_id, profile_fields, ids
):
    response = create(client, user_id, profile_fields, equipment_ids=ids)

    assert response.status_code == 400
    assert "999999 is not in the catalog" in response.json()["detail"]
    assert client.get(URL.format(user_id)).status_code == 404


def test_retired_equipment_is_refused(client, user_id, profile_fields, retired_equipment, pieces):
    response = create(
        client, user_id, profile_fields, equipment_ids=[pieces[0][0], retired_equipment]
    )

    assert response.status_code == 400
    assert f"equipment {retired_equipment} is retired" in response.json()["detail"]
    assert client.get(URL.format(user_id)).status_code == 404


def test_an_update_naming_unusable_equipment_is_refused_and_changes_nothing(
    client, user_id, profile_fields, pieces, retired_equipment
):
    created = create(client, user_id, profile_fields, equipment_ids=[pieces[0][0]]).json()

    for ids in ([999_999], [pieces[1][0], retired_equipment]):
        response = client.patch(URL.format(user_id), json={"equipment_ids": ids, "age": 55})
        assert response.status_code == 400

    assert client.get(URL.format(user_id)).json() == created


@pytest.mark.parametrize("body", [{"equipment_ids": None}, {"no_equipment": None}])
def test_the_equipment_fields_cannot_be_nulled(client, user_id, profile_fields, pieces, body):
    created = create(client, user_id, profile_fields, equipment_ids=[pieces[0][0]]).json()

    response = client.patch(URL.format(user_id), json=body)

    assert response.status_code == 400
    assert client.get(URL.format(user_id)).json() == created


# --- updating ---


def test_an_update_replaces_the_previous_selection(
    client, test_engine, user_id, profile_fields, pieces
):
    (first, _), (second, _), (third, _) = pieces
    created = create(client, user_id, profile_fields, equipment_ids=[first, second]).json()

    response = client.patch(URL.format(user_id), json={"equipment_ids": [second, third]})

    assert response.status_code == 200
    assert sorted(item["id"] for item in response.json()["equipment"]) == sorted([second, third])
    # the row of the piece that went is gone, the one that stayed is not repeated
    assert stored_ids(test_engine, created["id"]) == sorted([second, third])
    assert client.get(URL.format(user_id)).json() == response.json()


def test_an_update_with_repeated_ids_keeps_one_association_each(
    client, test_engine, user_id, profile_fields, pieces
):
    (first, _), (second, _), _ = pieces
    created = create(client, user_id, profile_fields, equipment_ids=[first]).json()

    client.patch(URL.format(user_id), json={"equipment_ids": [second, second, first, first]})

    assert stored_ids(test_engine, created["id"]) == sorted([first, second])


def test_an_empty_list_clears_the_selection_without_saying_none(
    client, test_engine, user_id, profile_fields, pieces
):
    created = create(client, user_id, profile_fields, equipment_ids=[pieces[0][0]]).json()

    body = client.patch(URL.format(user_id), json={"equipment_ids": []}).json()

    assert (body["equipment"], body["no_equipment"]) == ([], False)
    assert stored_ids(test_engine, created["id"]) == []


def test_saying_none_clears_the_selection_and_choosing_again_says_some(
    client, test_engine, user_id, profile_fields, pieces
):
    piece = pieces[0][0]
    created = create(client, user_id, profile_fields, equipment_ids=[piece]).json()

    body = client.patch(URL.format(user_id), json={"no_equipment": True}).json()
    assert (body["no_equipment"], body["equipment"]) == (True, [])
    assert stored_ids(test_engine, created["id"]) == []

    body = client.patch(URL.format(user_id), json={"equipment_ids": [piece]}).json()
    assert (body["no_equipment"], [item["id"] for item in body["equipment"]]) == (False, [piece])
    assert stored_ids(test_engine, created["id"]) == [piece]


def test_an_update_of_other_fields_leaves_the_equipment_alone(
    client, test_engine, user_id, profile_fields, pieces
):
    created = create(client, user_id, profile_fields, equipment_ids=[pieces[0][0]]).json()

    body = client.patch(URL.format(user_id), json={"weight_kg": 68.0}).json()

    assert body["weight_kg"] == 68.0
    assert body["equipment"] == created["equipment"]
    assert stored_ids(test_engine, created["id"]) == [pieces[0][0]]


def test_a_change_to_the_equipment_alone_moves_the_profiles_update_time(
    client, user_id, profile_fields, pieces
):
    created = create(client, user_id, profile_fields, equipment_ids=[pieces[0][0]]).json()

    body = client.patch(URL.format(user_id), json={"equipment_ids": [pieces[1][0]]}).json()

    assert datetime.fromisoformat(body["updated_at"]) > datetime.fromisoformat(created["updated_at"])


# --- the rest of the profile is as it was ---


def test_the_existing_profile_fields_still_round_trip(client, user_id, profile_fields):
    body = create(client, user_id, profile_fields, last_name="Rao", dietary_preference="vegan").json()

    assert {key: body[key] for key in profile_fields} == profile_fields
    assert body["last_name"] == "Rao" and body["dietary_preference"] == "vegan"
    assert client.get(URL.format(user_id)).json() == body


def test_deleting_a_profile_deletes_its_equipment_rows_and_not_the_catalog(
    service_session, test_engine, profile_fields, pieces
):
    user = UserService(service_session).create_user(UserCreate(email="delete-equipment@example.com"))
    service = UserProfileService(service_session)
    profile = service.create_profile(
        user.id, UserProfileCreate(**profile_fields, equipment_ids=[pieces[0][0], pieces[1][0]])
    )
    profile_id = profile.id

    service_session.delete(profile)
    service_session.commit()

    assert stored_ids(test_engine, profile_id) == []
    with Session(test_engine) as session:
        assert session.scalar(
            select(func.count()).select_from(Equipment).where(Equipment.id.in_([p[0] for p in pieces]))
        ) == 3


def test_a_refused_creation_leaves_no_profile_behind(service_session, test_engine, profile_fields):
    user = UserService(service_session).create_user(UserCreate(email="refused-equipment@example.com"))

    with pytest.raises(InvalidEquipmentError):
        UserProfileService(service_session).create_profile(
            user.id, UserProfileCreate(**profile_fields, equipment_ids=[999_999])
        )

    with Session(test_engine) as session:
        assert session.scalar(select(func.count()).select_from(UserProfile)) == 0


# --- what the coach reads ---


@pytest.fixture
def coach_user(service_session, profile_fields):
    def make(**equipment):
        user = UserService(service_session).create_user(UserCreate(email="coach-equipment@example.com"))
        UserProfileService(service_session).create_profile(
            user.id, UserProfileCreate(**profile_fields, **equipment)
        )
        return user

    return make


def test_the_coach_service_reads_what_the_profile_says(service_session, coach_user, pieces):
    names = [name for _, name in pieces[:2]]
    user = coach_user(equipment_ids=[pieces[0][0], pieces[1][0]])

    saved = UserProfileService(service_session).get_saved_equipment(user.id)

    assert saved == SavedEquipment(names=tuple(names), none=False)


def test_the_coach_service_reads_no_equipment(service_session, coach_user):
    user = coach_user(no_equipment=True)

    assert UserProfileService(service_session).get_saved_equipment(user.id) == SavedEquipment(
        names=(), none=True
    )


def test_the_coach_service_reads_nothing_for_a_profile_that_never_said(service_session, coach_user):
    assert UserProfileService(service_session).get_saved_equipment(coach_user().id) is None


def answer(service_session, user, message, *turns):
    provider = fake_provider(*turns)
    CoachService(service_session, provider).reply(user.id, message)
    return provider


def tool_outputs(provider):
    """What the tools gave the model in its second request, by tool name."""
    return {
        response.name: response.response["output"]
        for response in tool_responses(sent_contents(provider, 1)[-1])
    }


def test_the_model_is_told_the_saved_equipment_without_the_user_repeating_it(
    service_session, coach_user, pieces
):
    user = coach_user(equipment_ids=[pieces[0][0], pieces[1][0]])

    provider = answer(
        service_session,
        user,
        "Give me a workout today.",
        tool_turn(call("get_user_profile")),
        respond_turn("Your profile lists your equipment."),
    )

    equipment = tool_outputs(provider)["get_user_profile"]["equipment"]
    assert equipment == {"status": "LISTED", "equipment": sorted(name for _, name in pieces[:2])}


def test_a_user_with_no_equipment_is_offered_only_bodyweight_exercises(service_session, coach_user):
    user = coach_user(no_equipment=True)

    provider = answer(
        service_session,
        user,
        "Give me a workout.",
        tool_turn(
            call("get_user_profile"),
            call("search_exercises", use="MAIN_WORKOUT"),
        ),
        respond_turn("I looked at your profile and the catalog."),
    )

    outputs = tool_outputs(provider)
    assert outputs["get_user_profile"]["equipment"]["status"] == "NONE"
    results = outputs["search_exercises"]
    assert all(exercise["equipment"] == [] for exercise in results["exercises"])
    # every piece of the catalog was left out
    assert results["excluded_equipment"]


def test_what_the_user_says_in_the_conversation_beats_the_profile_for_that_workout(
    service_session, coach_user
):
    user = coach_user(no_equipment=True)

    def dumbbell_exercises(message):
        provider = answer(
            service_session,
            user,
            message,
            tool_turn(call("search_exercises", use="MAIN_WORKOUT", equipment="Dumbbell")),
            respond_turn("I searched the catalog."),
        )
        return tool_outputs(provider)["search_exercises"]["exercises"]

    # the profile says none: nothing that needs dumbbells is offered
    assert dumbbell_exercises("Give me a workout.") == []
    # today they say otherwise: what dumbbells alone need is
    offered = dumbbell_exercises("I have dumbbells at the gym today. Give me a workout.")
    assert offered and all(exercise["equipment"] == ["Dumbbell"] for exercise in offered)


def test_the_profile_is_not_changed_by_what_the_user_says(service_session, test_engine, coach_user):
    user = coach_user(no_equipment=True)

    answer(
        service_session,
        user,
        "Give me a workout. I only have a barbell and I don't have a bench.",
        tool_turn(call("get_user_profile")),
        respond_turn("Noted for this conversation."),
    )

    saved = UserProfileService(service_session).get_saved_equipment(user.id)
    assert saved == SavedEquipment(names=(), none=True)
    with Session(test_engine) as session:
        assert session.scalar(select(func.count()).select_from(user_profile_equipment)) == 0


def test_an_update_of_the_profile_is_what_the_next_conversation_starts_from(
    service_session, coach_user, pieces
):
    user = coach_user(no_equipment=True)
    service = UserProfileService(service_session)

    service.update_profile(user.id, UserProfileUpdate(equipment_ids=[pieces[2][0]]))

    assert service.get_saved_equipment(user.id) == SavedEquipment(
        names=(pieces[2][1],), none=False
    )
