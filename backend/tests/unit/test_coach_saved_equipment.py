"""The equipment saved in the user's profile is what the coach starts from.

Before, the coach knew a user's equipment only from what they typed in the conversation, so
a user who chose their equipment in the app had to say it again (and a user with no equipment
was offered a barbell). Now Formiq reads the profile's equipment once, with the conversation
(read_equipment), as what the user has until they say otherwise: for the model's note and for
the tools' filtering alike. A turn of theirs replaces it piece by piece ("I also have a bench",
"no bench") or as a whole ("I only have dumbbells", "I don't have any equipment").

These tests are scripted: they prove what Formiq reads, keeps and sends, not how Gemini uses it.
"""

import pytest

from app.agent import ConversationTurn, EquipmentSaid, initial_state
from app.agent.context import compact_conversation, conversation_note, render_conversation
from app.services.coach_service import read_equipment
from app.tools.equipment import StatedEquipment, equipment_key, saved_equipment, stated_equipment

CATALOG = [
    "Barbell", "Bench", "Cable Machine", "Dumbbell", "Exercise Ball", "EZ Curl Bar",
    "Foam Roller", "Kettlebell", "Leg Press Machine", "Machine", "Medicine Ball",
    "Other Equipment", "Pull-up Bar", "Resistance Band", "Rowing Machine", "Smith Machine",
    "Squat Rack", "Stationary Bike", "Treadmill",
]  # fmt: skip
KEYS = [equipment_key(name) for name in CATALOG]

HOME = saved_equipment(["Dumbbell", "Resistance Band"], none=False)
BODYWEIGHT = saved_equipment([], none=True)


def lacked(stated: StatedEquipment) -> set[str]:
    return stated.lacked(KEYS)


def read(message, saved=HOME, history=()):
    return read_equipment(
        [ConversationTurn("user", text) for text in history], message, CATALOG, saved
    )


# --- what the profile says ---


def test_a_profile_that_lists_equipment_says_the_user_has_that_and_nothing_else():
    assert HOME == StatedEquipment(
        has=frozenset({"dumbbell", "resistance band"}), has_nothing_else=True
    )
    assert lacked(HOME) == set(KEYS) - {"dumbbell", "resistance band"}


def test_a_profile_with_no_equipment_says_the_user_lacks_every_piece():
    assert BODYWEIGHT == StatedEquipment(has=frozenset(), has_nothing_else=True)
    assert BODYWEIGHT.said
    assert lacked(BODYWEIGHT) == set(KEYS)


def test_a_profile_that_never_said_says_nothing():
    assert saved_equipment([], none=False) is None


def test_no_equipment_wins_over_a_list_that_should_not_be_there():
    # the API never saves both; if one ever were, the safe reading is bodyweight only
    assert saved_equipment(["Dumbbell"], none=True) == BODYWEIGHT


def test_names_are_read_as_the_catalog_keys():
    assert saved_equipment(["Pull-up Bar", "EZ Curl Bar"], none=False).has == {
        "pull up bar",
        "ez curl bar",
    }


# --- saved equipment is used without the user repeating it ---


def test_the_saved_equipment_is_what_the_user_has_when_the_conversation_says_nothing():
    stated, said = read("Give me a leg workout.")

    assert stated.has == {"dumbbell", "resistance band"}
    assert said == EquipmentSaid(has=("Dumbbell", "Resistance Band"), only_these=True)
    assert lacked(stated) == set(KEYS) - {"dumbbell", "resistance band"}


def test_a_user_with_no_equipment_is_read_as_having_none_without_saying_so():
    stated, said = read("Give me a leg workout.", BODYWEIGHT)

    assert said == EquipmentSaid(only_these=True)
    assert lacked(stated) == set(KEYS)


def test_a_user_whose_profile_never_said_is_read_exactly_as_before():
    stated, said = read("Give me a leg workout.", saved=None)

    assert not stated.said
    assert said == EquipmentSaid()
    assert lacked(stated) == set()


def test_without_a_profile_the_conversation_alone_is_read_as_it_always_was():
    with_none = read("I don't have a bench.", saved=None)
    without = read_equipment([], "I don't have a bench.", CATALOG)

    assert with_none == without
    assert with_none[0].lacks == {"bench"}


# --- what the user says in the conversation replaces it ---


def test_a_piece_the_user_adds_is_theirs_too():
    stated, said = read("I also have a bench today.")

    assert stated.has == {"dumbbell", "resistance band", "bench"}
    assert "Bench" in said.has
    assert "bench" not in lacked(stated)


def test_a_piece_the_user_says_they_lack_is_taken_from_what_the_profile_lists():
    stated, said = read("Actually, I don't have my dumbbells today.")

    assert stated.has == {"resistance band"} and stated.lacks == {"dumbbell"}
    assert "dumbbell" in lacked(stated)
    assert said == EquipmentSaid(
        has=("Resistance Band",), lacks=("Dumbbell",), only_these=True
    )


def test_saying_they_have_only_one_piece_replaces_the_whole_list():
    stated, said = read("I only have a kettlebell today.")

    assert stated.has == {"kettlebell"}
    assert said == EquipmentSaid(has=("Kettlebell",), only_these=True)
    assert "dumbbell" in lacked(stated) and "resistance band" in lacked(stated)


def test_saying_they_have_only_a_piece_the_profile_lists_keeps_just_that_one():
    stated, _ = read("All I have is dumbbells today.")

    assert stated.has == {"dumbbell"}
    assert "resistance band" in lacked(stated)


def test_saying_they_have_no_equipment_replaces_a_list_with_nothing():
    stated, said = read("I don't have any equipment today.")

    assert stated.has == frozenset()
    assert said == EquipmentSaid(only_these=True)
    assert lacked(stated) == set(KEYS)


def test_a_user_with_no_equipment_who_names_a_piece_has_that_piece_only():
    stated, said = read("I have dumbbells at my parents' place today.", BODYWEIGHT)

    assert stated.has == {"dumbbell"}
    assert said == EquipmentSaid(has=("Dumbbell",), only_these=True)
    assert lacked(stated) == set(KEYS) - {"dumbbell"}


def test_a_later_turn_replaces_an_earlier_one_over_the_profile():
    history = ["I don't have my dumbbells today.", "Oh, found them. I have dumbbells again."]

    stated, _ = read("Leg day please.", history=history)

    assert stated.has == {"dumbbell", "resistance band"}
    assert stated.lacks == frozenset()


def test_mentioning_a_piece_is_not_having_it():
    # a question about a kettlebell neither adds one nor takes away the list
    stated, said = read("What is a kettlebell swing, and should I buy a kettlebell?")

    assert stated.has == {"dumbbell", "resistance band"}
    assert said == EquipmentSaid(has=("Dumbbell", "Resistance Band"), only_these=True)


def test_a_turn_from_the_coach_changes_nothing():
    stated, _ = read(
        "Leg day.",
        history=[],
    )
    claimed = read_equipment(
        [ConversationTurn("coach", "You only have a kettlebell and no equipment.")],
        "Leg day.",
        CATALOG,
        HOME,
    )[0]

    assert claimed == stated


def test_what_the_user_says_does_not_change_the_profile_reading_it_started_from():
    before = HOME

    read("I only have a kettlebell and I don't have dumbbells.")

    assert HOME == before


@pytest.mark.parametrize(
    "message",
    ["I have dumbbells.", "My dumbbells and bands are all I have.", "Just dumbbells and bands."],
)
def test_repeating_what_the_profile_lists_changes_nothing(message):
    stated, _ = read(message)

    assert stated.has == {"dumbbell", "resistance band"}
    assert lacked(stated) == set(KEYS) - {"dumbbell", "resistance band"}


# --- the model is told, within the note's limit ---


def test_the_saved_equipment_reaches_the_conversation_the_model_is_given():
    _, said = read("Give me a workout.")

    state = initial_state("Give me a workout.", [], said)

    assert state["conversation"].equipment == EquipmentSaid(
        has=("Dumbbell", "Resistance Band"), only_these=True
    )


def test_the_note_tells_the_model_the_saved_equipment_once_turns_are_left_out():
    _, said = read("Give me a workout.")
    history = [
        ConversationTurn(role, "Why these?" if role == "user" else "They fit your goal.")
        for _ in range(8)
        for role in ("user", "coach")
    ]

    note = conversation_note(compact_conversation(history, said))

    assert note == (
        "10 earlier messages are left out. "
        "The user said they have only: Dumbbell, Resistance Band."
    )
    assert "Bench" not in (render_conversation(compact_conversation(history, said)) or "")


def test_the_note_for_a_user_with_no_equipment_says_so():
    _, said = read("Give me a workout.", BODYWEIGHT)
    history = [ConversationTurn("user", "Why?") for _ in range(10)]

    assert conversation_note(compact_conversation(history, said)).endswith(
        "The user said they have no equipment."
    )


def test_a_user_whose_profile_never_said_gets_the_note_it_always_got():
    _, said = read("Give me a workout.", saved=None)
    history = [ConversationTurn("user", "Why?") for _ in range(10)]

    assert conversation_note(compact_conversation(history, said)) == "4 earlier messages are left out."
