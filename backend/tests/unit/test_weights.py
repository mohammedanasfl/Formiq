"""Which weights a proposal may carry: only the user's (Phase 2.5).

A saved plan's weights are carried on by a revision, and the model never chooses a load:
it may set one only when the user gave it (a figure in kg or lb, or the plan's own weight
moved by one), and take one off only when they asked for none. app.tools.weights reads the
user's words; no model and no database.
"""

import pytest

from app.tools.weights import (
    LB_TOLERANCE,
    asks_for_no_weight,
    rests_on_the_user,
    same_weight,
    stated_weights,
)


def kilograms(*texts):
    return [round(item.kg, 2) for item in stated_weights(texts)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("make the woodchop 20 kg", [20.0]),
        ("20kg please", [20.0]),
        ("12.5 kg", [12.5]),
        ("12,5 kilos", [12.5]),
        ("use 15 KGs", [15.0]),
        ("2 sets with 22.5 kilograms", [22.5]),
        ("45 lbs", [20.41]),
        ("a 50 pound dumbbell", [22.68]),
        ("20-kg kettlebell", [20.0]),
        ("2x20kg", [20.0]),
        ("20 kg and 10 kg", [20.0, 10.0]),
    ],
)
def test_a_weight_the_user_gave_is_read_in_kilograms(text, expected):
    assert kilograms(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "8-12 reps",
        "3 sets of 10",
        "1:30 rest",
        "make it heavier",
        "I weigh 70 on the scale",
        "the 3rd set",
        "in 20 minutes",
        "0 kg",
        "",
    ],
)
def test_what_a_fitness_message_says_far_more_often_is_no_weight(text):
    assert kilograms(text) == []


def test_pounds_allow_the_rounding_of_a_conversion_and_kilograms_do_not():
    (pounds,) = stated_weights(["45 lbs"])
    (kilos,) = stated_weights(["20 kg"])

    assert pounds.tolerance == LB_TOLERANCE
    assert rests_on_the_user(20.0, None, [pounds])
    assert rests_on_the_user(20.5, None, [pounds])
    assert not rests_on_the_user(21.0, None, [pounds])
    assert rests_on_the_user(20.0, None, [kilos])
    assert not rests_on_the_user(20.5, None, [kilos])


def test_a_weight_rests_on_the_user_when_it_is_a_figure_or_the_plans_moved_by_one():
    given = stated_weights(["make it 20 kg", "and add 5 kg more to the third one"])

    assert rests_on_the_user(20.0, None, given)
    # the plan's 15 kg plus a stated 5, or the plan's 25 kg minus it
    assert rests_on_the_user(20.0, 15.0, stated_weights(["add 5 kg"]))
    assert rests_on_the_user(20.0, 25.0, stated_weights(["take off 5 kg"]))
    assert rests_on_the_user(5.0, None, given)
    # nothing the user said explains this one
    assert not rests_on_the_user(40.0, 15.0, given)
    assert not rests_on_the_user(20.0, 15.0, [])
    assert not rests_on_the_user(20.0, None, stated_weights(["make it heavier"]))


@pytest.mark.parametrize(
    "text",
    [
        "no weights",
        "No weight please",
        "without the weight",
        "without any weights",
        "remove the weight",
        "take off the weight",
        "ditch the extra weight",
        "make it bodyweight",
        "body weight only",
        "do it unweighted",
        "0 kg",
    ],
)
def test_a_request_for_no_weight_is_read(text):
    assert asks_for_no_weight([text])


@pytest.mark.parametrize(
    "text",
    [
        "make it heavier",
        "I want to lose weight",
        "my body weight is 70 kg",
        "my bodyweight is 70",
        "what is my goal weight",
        "add some weight",
        "drop the weight a bit",
        "weights are fine",
        "20 kg",
        "",
    ],
)
def test_what_is_not_a_request_for_no_weight_is_not_read_as_one(text):
    assert not asks_for_no_weight([text])


def test_a_request_in_any_of_the_users_messages_counts():
    assert asks_for_no_weight(["make it harder", "actually, no weights"])
    assert not asks_for_no_weight(["make it harder", "ok"])


def test_saved_weights_are_the_same_within_a_hundredth_of_a_kilogram_and_none_is_none():
    assert same_weight(15.0, 15.0)
    assert same_weight(15.0, 15.004)
    assert not same_weight(15.0, 15.5)
    assert same_weight(None, None)
    assert not same_weight(None, 15.0)
    assert not same_weight(15.0, None)
