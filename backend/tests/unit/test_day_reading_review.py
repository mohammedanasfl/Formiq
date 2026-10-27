"""The date reader against an adversarial review (Phase 2.7).

An independent review tried about 330 phrasings, 97,000 brute-force date checks and 180,000
fuzzed inputs against app.tools.schedule. The date arithmetic held (month ends, year ends, the
leap day, ISO weeks, every weekday as today). What did not: the reader took the word before a day
as where the workout goes without asking WHO is saying what, so "I can't make it Monday, how about
Tuesday" was Monday, "to Friday or Saturday" was Friday, "no wait, Sunday" lost to "tomorrow", a
weekday said in passing ("I ran on Thursday") replaced the day the user had asked for, and a
conflict between a weekday and a date was settled by the window. Each is a case below, with the
answer a person gives. No model, no database.
"""

import time
from datetime import date

import pytest

from app.tools.schedule import read_requested_day

WED = date(2026, 10, 21)  # the reviewer's today: Thursday 22 is tomorrow, Monday 26, Friday 23, Saturday 24


def read(*texts, today=WED):
    return read_requested_day(list(texts), today, 14)


def d(day):
    return date(2026, 10, day)


def single(*texts, today=WED):
    reading = read(*texts, today=today)
    assert reading.kind == "day", (texts, reading)
    return reading.dates[0]


# --- the day said of is not always the day gone to ---


@pytest.mark.parametrize(
    ("texts", "day"),
    [
        (("I can't make it Monday, how about Tuesday",), d(27)),
        (("Monday doesn't work but Tuesday does",), d(27)),
        (("I'm busy Friday, can we do Saturday?",), d(24)),
        (("I'm busy today, can we do tomorrow?",), d(22)),
        (("I can't do Monday so move it to Friday",), d(23)),
        (("Monday is out, Tuesday works",), d(27)),
        (("move it to Friday, I can't do Monday",), d(23)),
        (("Move it to Friday, next week is busy",), d(23)),
        (("move it to tomorrow, no wait, Sunday",), d(25)),
        (("move it to Monday, sorry, Tuesday",), d(27)),
        (("move it to Monday, actually make it Tuesday",), d(27)),
        (("move it to Monday", "Actually Tuesday"), d(27)),
    ],
)
def test_a_day_the_user_cannot_use_or_took_back_is_not_the_one_they_ask_for(texts, day):
    assert single(*texts) == day


@pytest.mark.parametrize(
    "text",
    [
        "I can't train tomorrow, can you move it?",
        "I'm busy on Saturday, can you move my workout?",
        "Reschedule my Saturday workout, I can't make it",
        "I did legs on Monday. What should I train tomorrow?",
        "I did it on Wednesday",
        "I ran on Thursday",
        "I haven't trained in 3 days",
        "I've done 4 workouts in 2 weeks",
        "I trained 3 times this week",
        "exams are next week",
        "I'm free Monday to Friday",
        "I have a race in 4 weeks",
    ],
)
def test_a_day_named_in_passing_asks_for_nothing(text):
    assert read(text).kind == "none", text


def test_a_message_that_takes_a_day_back_cancels_the_request_for_it():
    assert read("move it to Monday", "no, not Monday").kind == "none"
    assert read("move it to Monday", "anything but Monday").kind == "none"
    # and leaves a day it did not take back standing
    assert single("move it to Saturday", "not Monday") == d(24)


def test_what_is_left_of_a_period_after_a_day_is_taken_back_is_asked_for():
    assert single("the weekend", "not Saturday") == d(25)


def test_a_passing_day_in_a_later_message_does_not_replace_the_one_asked_for():
    assert single("move it to Saturday", "make it shorter, I ran on Thursday") == d(24)
    assert single("move it to Saturday", "I did legs on Monday, make it lighter") == d(24)


# --- two days offered are two days to ask about ---


@pytest.mark.parametrize(
    ("text", "days"),
    [
        ("move it to Friday or Saturday", {d(23), d(24)}),
        ("make it Friday or Saturday", {d(23), d(24)}),
        ("move it to the 24th or 25th", {d(24), d(25)}),
        ("how about Friday and Saturday", {d(23), d(24)}),
        ("Monday to Friday", {d(23), d(26)}),
        ("after tomorrow", {d(22)}),
        ("before Saturday", {d(24)}),
        ("the day before Friday", {d(23)}),
        ("by Friday", {d(23)}),
        ("Monday, Nov 10", {d(26)}),
        ("Tuesday, Nov 5", {d(27)}),
        ("Sat, Oct 28", {d(24), d(28)}),
        ("Tuesday the 28th of October", {d(27), d(28)}),
    ],
)
def test_words_that_fit_two_days_or_name_none_are_asked_about(text, days):
    reading = read(text)

    assert reading.kind == "ambiguous", (text, reading)
    assert days <= set(reading.dates) | set(reading.options)


def test_a_weekday_and_a_date_that_disagree_are_asked_about_even_when_the_window_leaves_one():
    """"Monday, Nov 10" (Nov 10 is a Tuesday): only Monday the 26th is inside the window, and that is
    not a reason to take it; the user's words disagree with themselves."""
    reading = read("Monday, Nov 10")

    assert reading.kind == "ambiguous" and reading.dates == (d(26),)


# --- days named in other ways ---


@pytest.mark.parametrize(
    ("text", "day"),
    [
        ("a week from today", d(28)),
        ("a week from tomorrow", d(29)),
        ("3 days from now", d(24)),
        ("two days from today", d(23)),
        ("a week from Friday", d(30)),
        ("starting from Monday", d(26)),
        ("the 28th", d(28)),
        ("on 28th", d(28)),
        ("let's do the 28th", d(28)),
        ("move it to 24th", d(24)),
        ("Sat", d(24)),
        ("Sun works", d(25)),
        ("let's do sat", d(24)),
        ("Sat 24th", d(24)),
        ("2026/10/25", d(25)),
        ("25.10.2026", d(25)),
        ("25-10-2026", d(25)),
        ("25-Oct", d(25)),
        ("Oct-25", d(25)),
        ("Fri. Oct. 30", d(30)),
    ],
)
def test_more_ways_of_naming_a_day_are_read(text, day):
    assert single(text) == day, text


def test_a_short_answer_that_is_only_sat_or_sun_settles_the_weekend():
    assert single("move it to the weekend", "Sat") == d(24)
    assert read("Sat or Sun?").kind == "ambiguous"


# --- what is not a date ---


@pytest.mark.parametrize(
    "text",
    [
        "I'm on the 2nd week of the program",
        "by the 4th week I want to squat 100kg",
        "on the 3rd minute switch legs",
        "I'm doing 16/8 fasting",
        "Tabata 20/10",
        "30/10 intervals",
        "24/7 gym access",
        "then march 30 seconds",
        "3 sets of 12 dec push-ups",
        "may 3 sets be enough?",
        "make a yoga flow for sun salutations",
        "Monday blues",
        "3 sets of 10 reps",
        "rest 1:30",
        "I did 12/10 reps",
        "week 3 of my programme",
        "I sat down",
        "5/3/1",
        "RPE 8/10",
        "45/15",
        "3x12-15",
    ],
)
def test_fitness_words_that_look_like_a_date_are_not_one(text):
    assert read(text).kind == "none", text


def test_a_slash_date_with_something_pointing_at_it_or_a_year_is_still_a_date():
    assert single("put it on 28/10") == d(28)
    assert single("10/28 works") == d(28)
    assert single("10/28/2026") == d(28)
    assert single("Can we do 30/10?") == d(30)


# --- the cost of reading a long message ---


@pytest.mark.parametrize(
    "text",
    ["monday" + " " * 8000 + "x", "next week" + " " * 8000, "friday," + " " * 8000, "a" * 8000, "1/" * 4000],
)
def test_a_long_message_is_read_in_linear_time(text):
    started = time.perf_counter()
    read(text)

    assert time.perf_counter() - started < 0.5
