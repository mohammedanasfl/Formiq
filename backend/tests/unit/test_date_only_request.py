"""When is a message only a request to move a workout to another day? (Phase 2.7, app.tools.schedule)

A move to another day that also swaps an exercise changes a workout the user asked only to move: the
Phase 2.6 live pass saw it once ("move it to tomorrow" proposed with different exercises), and the
card showed it but the reply did not say. The proposal tool holds such a move to the saved plan's
exercises, and it needs to know when the user's words ask for nothing else. The test is positive and
conservative: the newest message must be made of day words and neutral move words ("please", "can you",
"the workout") and nothing else; any other word means it may be asking for more, and the guard is off,
which is how a move was always treated. Scripted sentences: no model, no database.
"""

from datetime import date

import pytest

from app.tools.schedule import is_date_only_request

FRIDAY = date(2026, 10, 23)


@pytest.mark.parametrize(
    "text",
    [
        "Move it to tomorrow",
        "move it to tomorrow please",
        "Can you reschedule it for Friday?",
        "Push it to Saturday.",
        "Move my workout to the 28th",
        "Friday",
        "tomorrow",
        "Could you put it on Saturday, please?",
        "Just move it to Friday",
        "Let's do it on Sunday instead",
        "Move the workout from Monday to Friday",
        "Move it to next Friday",
        "make it Saturday",
        "I'd like it on 2026-10-30 please",
        "Thanks! Can we do Saturday instead?",
        "Move the plan to Oct 28.",
        "Move it to the weekend",
    ],
)
def test_a_message_of_day_words_and_neutral_move_words_asks_for_nothing_else(text):
    assert is_date_only_request(text, FRIDAY), text


@pytest.mark.parametrize(
    "text",
    [
        "Move it to Friday and make it harder",
        "Move it to Friday, swap the squats",
        "Make it Friday and shorter",
        "Move it to Friday but skip lunges",
        "Move it to Friday, I have no bench",
        "Move it to Friday. Also add a warm-up",
        "I hurt my knee, move it to Friday",
        "Friday works, make it 4 sets",
        "Move it to tomorrow and add 5 kg",
        "Move it to tomorrow, with dumbbells only",
        "Move it to Friday and use 20 kg",
        "Move it to Friday with a different core exercise",
        "Make it a little harder.",
        "How long is it?",
        "",
        "   ",
    ],
)
def test_any_other_word_means_it_may_ask_for_more_and_the_guard_is_off(text):
    assert not is_date_only_request(text, FRIDAY), text


def test_a_message_that_names_no_day_is_not_a_move():
    assert not is_date_only_request("please", FRIDAY)
    assert not is_date_only_request("can you do it", FRIDAY)
