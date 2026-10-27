"""The words that let a revision move a saved workout to another day: only a day the
user named (app.tools.schedule). Known words, English only; a miss leaves the workout
on its day."""

import pytest

from app.tools.schedule import names_a_day


@pytest.mark.parametrize(
    "text",
    [
        "Move it to tomorrow",
        "do it today instead",
        "can I do this tonight?",
        "the day after tomorrow please",
        "Reschedule for Friday",
        "move it to sat",
        "make it Wednesday's workout",
        "next week would be better",
        "this weekend",
        "push it to next Monday",
        "in 3 days",
        "in a week",
        "in two days",
        "on 2026-10-28",
        "put it on 28/10",
        "10/28 works",
        "10/28/2026",
        "Oct 28",
        "october 28th",
        "28 October",
        "28th of oct",
        "on the 28th",
        "SATURDAY",
    ],
)
def test_a_message_that_names_a_day_is_read_as_one(text):
    assert names_a_day(text)


@pytest.mark.parametrize(
    "text",
    [
        "Make it a little harder.",
        "Keep same duration",
        "Use no equipment",
        "Reschedule it",
        "do it later",
        "move it somewhere else",
        "I have 40 minutes",
        "3 sets of 10 reps",
        "8-12 reps please",
        "3-4 sets",
        "10-12 reps",
        "a 25-minute upper-body workout",
        "I can't tell what day suits me",
        "swap the squats for lunges",
        "it was monotonous",
        "I may be tired, make it easier",
        "rest 1:30 between sets",
        "use 12.5 kg",
        "a 4:3 tempo",
        "3/4 squats",
        "make the 3rd set easier",
        "on the 3rd set slow down",
        "",
    ],
)
def test_a_message_that_names_no_day_is_not(text):
    assert not names_a_day(text)


def test_a_word_inside_another_word_is_not_a_day():
    # "mon" in money, "sat" in satisfied, "fri" in friendly, "sun" in sunscreen
    for text in ("money is tight", "I am satisfied", "a friendly coach", "sunscreen"):
        assert not names_a_day(text), text
