"""The day a user's words ask for, resolved to dates by rules (Phase 2.7, app.tools.schedule).

Until Phase 2.7 Formiq checked only that the user had named *a* day and took the model's word
for which. The Phase 2.6 live pass found "tomorrow" resolved to the wrong date and "the weekend"
answered with a day nobody chose. The reader now resolves the user's own words against the
calendar's today, and has four answers: none (no day named), day (exactly one), ambiguous (ask)
and outside (the window is today and the 14 days after it).

Every case is a scripted sentence and a fixed today: no model, no database. Where a weekday
or a boundary is the point, the expected dates come from a brute-force walk through the
calendar, not from the rule being tested.
"""

from datetime import date, timedelta

import pytest

from app.tools.schedule import find_mentions, read_requested_day

WINDOW = 14
FRIDAY = date(2026, 10, 23)  # the day of the Phase 2.6 pass: tomorrow is Saturday the 24th
NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def read(text, today=FRIDAY, *earlier):
    return read_requested_day([*earlier, text], today, WINDOW)


def single(text, today=FRIDAY, *earlier):
    reading = read(text, today, *earlier)
    assert reading.kind == "day", (text, reading)
    (day,) = reading.dates
    return day


def first_after(today, weekday):
    """The first day strictly after today with this weekday: a walk, not a formula."""
    day = today + timedelta(days=1)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day


def in_next_week(today, weekday):
    """The day with this weekday in the calendar week (Monday to Sunday) after today's."""
    day = today + timedelta(days=1)
    while day.isocalendar()[:2] == today.isocalendar()[:2]:
        day += timedelta(days=1)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day


# every kind of date boundary: a month, a year, a leap February, and the clocks' weekends
TODAYS = [date(2026, 12, 25) + timedelta(days=n) for n in range(0, 16)]  # across the new year
TODAYS += [date(2028, 2, 22) + timedelta(days=n) for n in range(0, 10)]  # across a leap day
TODAYS += [date(2026, 10, 24) + timedelta(days=n) for n in range(0, 10)]  # across a month end


# --- 1. "tomorrow" across a boundary ---


@pytest.mark.parametrize(
    ("today", "tomorrow"),
    [
        (date(2026, 10, 22), date(2026, 10, 23)),
        (date(2026, 10, 23), date(2026, 10, 24)),
        (date(2026, 10, 31), date(2026, 11, 1)),
        (date(2026, 12, 31), date(2027, 1, 1)),
        (date(2028, 2, 28), date(2028, 2, 29)),
        (date(2028, 2, 29), date(2028, 3, 1)),
        (date(2027, 2, 28), date(2027, 3, 1)),
    ],
)
@pytest.mark.parametrize("words", ["Move it to tomorrow", "tomorrow", "do it tomorrow please", "TOMORROW"])
def test_tomorrow_is_the_next_calendar_day_of_the_given_today(today, tomorrow, words):
    assert single(words, today) == tomorrow


def test_the_same_words_are_a_different_day_for_a_user_a_day_ahead():
    """The boundary the live pass hit: at 20:30 UTC it is Friday 23rd in Kolkata (so tomorrow is
    the 24th) and still Thursday the 22nd in UTC (so it is the 23rd). The reader takes today
    from the calendar, so each user's tomorrow is their own."""
    assert single("move it to tomorrow", date(2026, 10, 23)) == date(2026, 10, 24)
    assert single("move it to tomorrow", date(2026, 10, 22)) == date(2026, 10, 23)


@pytest.mark.parametrize(
    ("words", "offset"),
    [
        ("today", 0),
        ("tonight", 0),
        ("later today", 0),
        ("this evening", 0),
        ("the day after tomorrow", 2),
        ("day after tomorrow", 2),
        ("in 3 days", 3),
        ("in a week", 7),
        ("in two weeks", 14),
        ("in 10 days", 10),
    ],
)
def test_relative_days_count_from_today(words, offset):
    assert single(words) == FRIDAY + timedelta(days=offset)


# --- 2. every weekday around a boundary ---


@pytest.mark.parametrize("today", TODAYS, ids=lambda d: d.isoformat())
@pytest.mark.parametrize("weekday", range(7), ids=NAMES)
def test_a_weekday_is_the_next_one_after_today_and_ambiguous_on_that_very_weekday(today, weekday):
    reading = read(f"move it to {NAMES[weekday]}", today)

    if today.weekday() == weekday:
        # said on a Friday: today, or a week from today? it is not for Formiq to pick
        assert reading.kind == "ambiguous"
        assert reading.dates == (today, today + timedelta(days=7))
    else:
        assert reading.kind == "day"
        assert reading.dates == (first_after(today, weekday),)
        assert reading.dates[0].weekday() == weekday


@pytest.mark.parametrize("today", TODAYS, ids=lambda d: d.isoformat())
@pytest.mark.parametrize("weekday", range(7), ids=NAMES)
def test_this_weekday_is_the_next_one_on_or_after_today(today, weekday):
    expected = today if today.weekday() == weekday else first_after(today, weekday)

    assert single(f"this {NAMES[weekday]}", today) == expected


@pytest.mark.parametrize("today", TODAYS, ids=lambda d: d.isoformat())
@pytest.mark.parametrize("weekday", range(7), ids=NAMES)
def test_a_weekday_of_next_week_is_in_the_calendar_week_after_this_one(today, weekday):
    expected = in_next_week(today, weekday)

    assert single(f"{NAMES[weekday]} next week", today) == expected
    assert single(f"next week on {NAMES[weekday]}", today) == expected
    assert single(f"{NAMES[weekday]} of next week", today) == expected
    assert expected.weekday() == weekday and 1 <= (expected - today).days <= 13


@pytest.mark.parametrize("today", TODAYS, ids=lambda d: d.isoformat())
@pytest.mark.parametrize("weekday", range(7), ids=NAMES)
def test_next_weekday_is_the_one_this_week_or_a_week_later_and_asks_when_both_could_be_meant(
    today, weekday
):
    soon = first_after(today, weekday)
    reading = read(f"next {NAMES[weekday]}", today)

    if soon.isocalendar()[:2] == today.isocalendar()[:2]:
        # said on a Wednesday of a Friday: this week's, or the one after
        assert reading.kind == "ambiguous"
        assert reading.dates == (soon, soon + timedelta(days=7))
    else:
        assert (reading.kind, reading.dates) == ("day", (soon,))


@pytest.mark.parametrize(
    "words", ["monday", "MONDAY", "Mon", "mon", "to monday", "Make it Monday's workout"]
)
def test_weekdays_are_read_in_any_case_and_short_form(words):
    assert single(words, date(2026, 10, 21)) == date(2026, 10, 26)  # from a Wednesday


@pytest.mark.parametrize("words", ["move it to sat", "for sun", "this sat", "next sun", "on sat"])
def test_sat_and_sun_are_days_only_where_a_word_points_at_one(words):
    assert find_mentions(words, FRIDAY), words


@pytest.mark.parametrize(
    "words",
    [
        "I sat down between sets",
        "the sun was out",
        "I sat",
        "sun protection",
        "money is tight",
        "a friendly coach",
        "it was monotonous",
        "my wedding is soon",  # "wed" is a weekday short form, "wedding" is not
    ],
)
def test_words_that_only_look_like_a_day_are_not_one(words):
    assert find_mentions(words, FRIDAY) == [], words


# --- 3. "this Friday" against an explicit date ---


@pytest.mark.parametrize(
    "words",
    [
        "this Friday, Oct 30",  # this Friday is the 23rd
        "this Friday the 30th of October",
        "this Friday 2026-10-30",
    ],
)
def test_a_qualified_weekday_that_is_not_the_date_beside_it_conflicts_and_asks(words):
    reading = read(words)

    assert reading.kind == "ambiguous", reading
    assert date(2026, 10, 23) in reading.dates and date(2026, 10, 30) in reading.dates


@pytest.mark.parametrize(
    "words",
    [
        "Friday, Oct 28",  # the 28th is a Wednesday
        "Monday 30 October",  # the 30th is a Friday
        "Saturday 2026-10-30",
        "Tuesday the 28th of October",
    ],
)
def test_a_weekday_that_is_not_the_day_of_the_date_beside_it_conflicts_and_asks(words):
    assert read(words).kind == "ambiguous", words


@pytest.mark.parametrize(
    ("words", "day"),
    [
        ("Friday, October 30", date(2026, 10, 30)),
        ("Friday 30 Oct", date(2026, 10, 30)),
        ("Fri, Oct 30", date(2026, 10, 30)),
        ("October 30 (Friday)", date(2026, 10, 30)),
        ("30 October, Friday", date(2026, 10, 30)),
        ("Wednesday the 28th", date(2026, 10, 28)),
        ("this Friday, Oct 23", date(2026, 10, 23)),
        ("next Friday, Oct 30", date(2026, 10, 30)),
    ],
)
def test_a_weekday_and_the_date_it_names_are_one_day(words, day):
    assert single(words) == day


def test_an_explicit_date_settles_a_weekday_said_on_that_weekday():
    """Said on Friday the 23rd, "Friday" is the 23rd or the 30th; "Friday the 30th" is the 30th."""
    assert read("Friday").kind == "ambiguous"
    assert single("Friday the 30th") == date(2026, 10, 30)


@pytest.mark.parametrize(
    ("words", "day"),
    [
        ("2026-10-30", date(2026, 10, 30)),
        ("Oct 30", date(2026, 10, 30)),
        ("october 30th", date(2026, 10, 30)),
        ("30 October", date(2026, 10, 30)),
        ("30th of oct", date(2026, 10, 30)),
        ("30/10", date(2026, 10, 30)),
        ("10/30", date(2026, 10, 30)),
        ("10/30/2026", date(2026, 10, 30)),
        ("30/10/26", date(2026, 10, 30)),
        ("on the 28th", date(2026, 10, 28)),
        ("to the 30th", date(2026, 10, 30)),
        ("Nov 1", date(2026, 11, 1)),
    ],
)
def test_calendar_dates_are_read_in_every_common_form(words, day):
    assert single(words) == day


def test_a_date_without_a_year_is_the_next_one_and_years_roll_over():
    assert single("Jan 2", date(2026, 12, 28)) == date(2027, 1, 2)
    assert single("2 January", date(2026, 12, 28)) == date(2027, 1, 2)
    assert single("on the 2nd", date(2026, 12, 28)) == date(2027, 1, 2)
    # a leap day: only a year that has it
    assert single("Feb 29", date(2028, 2, 20)) == date(2028, 2, 29)
    # no leap day within the next two years from March 2026: not a date that exists
    assert find_mentions("Feb 29", date(2026, 3, 1)) == []


@pytest.mark.parametrize("words", ["Feb 30", "31 November", "2026-02-29", "0/0", "13/13", "2026-13-01"])
def test_a_date_that_does_not_exist_is_no_day_at_all(words):
    assert read(words).kind == "none", words


@pytest.mark.parametrize("words", ["03/04", "10/12", "1/2", "12/12", "11/11/2026", "5/6", "3/4 squats"])
def test_a_slash_date_that_could_be_either_order_is_read_as_no_day(words):
    """Formiq does not guess between 3 April and 4 March: the coach asks, as it does when no day
    was named (a move is refused until it is told one). Fractions and scores are not dates."""
    assert read(words).kind == "none", words


# --- 4. "the weekend" and the other periods ---


@pytest.mark.parametrize(
    "words",
    ["move it to the weekend", "this weekend", "the weekend", "weekend", "over the weekend", "next weekend"],
)
def test_the_weekend_names_no_one_day_and_asks(words):
    reading = read(words)

    assert reading.kind == "ambiguous", words
    assert {day.weekday() for day in reading.options} == {5, 6}


def test_this_weekend_is_this_weeks_two_days_and_next_weekend_the_next_weeks():
    assert read("this weekend").options == (date(2026, 10, 24), date(2026, 10, 25))
    assert read("next weekend").options == (date(2026, 10, 31), date(2026, 11, 1))


def test_the_weekend_asks_even_when_only_one_of_its_days_is_left():
    """Said on a Sunday, only Sunday is left of this weekend: it is still two possible days to
    the person who said "the weekend", and a coach that picks one has guessed."""
    reading = read("this weekend", date(2026, 10, 25))

    assert reading.kind == "ambiguous" and reading.dates == (date(2026, 10, 25),)


@pytest.mark.parametrize(
    "words", ["next week", "this week", "next month", "this month", "push it to next week"]
)
def test_a_period_is_not_a_day_and_asks(words):
    assert read(words).kind == "ambiguous", words


def test_a_period_lists_the_days_of_it_that_fit():
    reading = read("next week")

    assert reading.dates[0] == date(2026, 10, 26) and reading.dates[-1] == date(2026, 11, 1)
    assert len(reading.dates) == 7


@pytest.mark.parametrize(
    ("texts", "day"),
    [
        # the answer to the coach's question settles it
        (["move it to the weekend", "Saturday"], date(2026, 10, 24)),
        (["move it to the weekend", "make it Sunday"], date(2026, 10, 25)),
        (["next week", "Wednesday next week"], date(2026, 10, 28)),
        # and in the same words, a day inside the period does
        (["the weekend, Saturday"], date(2026, 10, 24)),
        (["Saturday of this weekend"], date(2026, 10, 24)),
        (["next week, Wednesday"], date(2026, 10, 28)),
    ],
)
def test_the_user_establishing_the_day_settles_a_period(texts, day):
    assert single(texts[-1], FRIDAY, *texts[:-1]) == day


def test_an_answer_that_names_no_day_leaves_the_period_open():
    assert read("the first one", FRIDAY, "move it to the weekend").kind == "ambiguous"
    assert read("make it a bit harder", FRIDAY, "the weekend").kind == "ambiguous"


def test_two_days_offered_are_two_days_to_ask_about():
    assert read("tomorrow or Sunday").kind == "ambiguous"
    assert read("Saturday or Sunday").kind == "ambiguous"
    # but the same day twice is one day: tomorrow is Saturday
    assert single("tomorrow, Saturday") == date(2026, 10, 24)


# --- what a message says of the day it moves from ---


@pytest.mark.parametrize(
    ("words", "day"),
    [
        ("move my Monday workout to Wednesday", date(2026, 10, 28)),
        ("from Monday to Wednesday", date(2026, 10, 28)),
        ("instead of Monday make it Wednesday", date(2026, 10, 28)),
        ("Wednesday instead of Monday", date(2026, 10, 28)),
        ("not Monday, Wednesday", date(2026, 10, 28)),
        ("I trained on Monday; push this to Saturday", date(2026, 10, 24)),
        ("make Monday's workout harder and move it to tomorrow", date(2026, 10, 24)),
        ("put it on Sunday rather than Saturday", date(2026, 10, 25)),
    ],
)
def test_the_day_a_move_goes_to_is_not_the_day_it_comes_from(words, day):
    assert single(words) == day


def test_a_message_that_only_says_which_day_not_to_use_names_none():
    assert read("not Friday").kind == "none"
    assert read("anything but Monday, not on Monday").kind == "none"


def test_a_day_the_user_only_mentions_in_passing_is_no_request_for_it():
    """"I did it on Wednesday" says what was done, not where to go (Phase 2.7, after the adversarial
    review: a passing mention used to decide, and the model was held to a day nobody asked for)."""
    assert read("I did it on Wednesday", FRIDAY).kind == "none"
    assert read("I ran on Thursday", FRIDAY).kind == "none"
    assert read("exams are next week", FRIDAY).kind == "none"


# --- 7. out of the window ---


@pytest.mark.parametrize(
    "words",
    ["1 January 2027", "2027-01-01", "in 3 weeks", "in 15 days", "in a month", "Oct 12", "Nov 7"],
)
def test_a_day_outside_today_and_the_next_fourteen_is_outside(words):
    reading = read(words, FRIDAY)

    assert reading.kind == "outside", (words, reading)
    assert reading.dates == () and reading.options


def test_the_window_includes_today_and_the_fourteenth_day_and_nothing_else():
    assert single("Nov 6") == FRIDAY + timedelta(days=14)
    assert single("today") == FRIDAY
    assert read("Nov 7").kind == "outside"
    assert read("2026-10-22").kind == "outside"  # yesterday
    assert read("in 14 days").kind == "day" and read("in 15 days").kind == "outside"


def test_a_day_in_the_window_beside_one_outside_it_is_the_one_inside():
    assert single("not on 12 Oct, tomorrow") == date(2026, 10, 24)


# --- 5. no day, and what is not a day ---


@pytest.mark.parametrize(
    "words",
    [
        "Make it a little harder.",
        "Reschedule it",
        "do it later",
        "move it somewhere else",
        "I have 40 minutes",
        "3 sets of 10 reps",
        "8-12 reps please",
        "use 12.5 kg",
        "rest 1:30 between sets",
        "make the 3rd set easier",
        "on the 3rd set slow down",
        "I trained yesterday",
        "last Friday was hard",
        "I do legs every Friday",
        "swap squats for lunges",
        "",
    ],
)
def test_words_that_name_no_day_name_none(words):
    assert read(words).kind == "none", words


def test_with_no_words_there_is_nothing_to_read():
    assert read_requested_day([], FRIDAY, WINDOW).kind == "none"
    assert read_requested_day([""], FRIDAY, WINDOW).kind == "none"


def test_the_newest_message_that_names_a_day_decides_and_an_older_one_stands_when_it_names_none():
    assert single("Saturday", FRIDAY, "move it to Monday") == date(2026, 10, 24)
    assert single("make it harder", FRIDAY, "move it to Monday") == date(2026, 10, 26)
    assert single("make it harder", FRIDAY, "move it to Monday", "a bit shorter too") == date(2026, 10, 26)


def test_only_the_users_turns_are_given_to_the_reader():
    """The coach's own turns are the client's claim of what the coach said: the tools give the
    reader the user's turns only, so a "coach" turn naming Sunday decides nothing (the tool test
    holds that)."""
    assert read_requested_day(["make it harder"], FRIDAY, WINDOW).kind == "none"
