"""The coach's calendar: today in the user's own time zone, from Formiq's clock (Phase 2.7).

Formiq's "today" was the UTC date, which is not the user's date for hours of every day: the Phase
2.6 live pass saw "tomorrow" come out wrong, and the model was never told the date at all. The
contract (app.tools.coach_calendar): the day is the user's LOCAL day in the IANA zone the app
sends, UTC when it sends none (and the coach says which), never a mix of the two.

Scripted clocks only: no database, no model.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock

import pytest

from app.approvals import ProposalTerms
from app.schemas.timezone import zone_of
from app.services.coach_service import CoachService
from app.tools.coach_calendar import CoachCalendar, calendar_at
from app.tools import formiq_tools
from app.tools.schedule import read_requested_day


def at(*args):
    return datetime(*args, tzinfo=UTC)


def coach_tools_at(moment, timezone=None):
    service = CoachService(
        Mock(),
        Mock(),
        proposal_terms=ProposalTerms(clock=lambda: moment, ttl=timedelta(minutes=30)),
    )
    return service._tools([], timezone=timezone)


# Thursday 22 October 2026, 20:30 UTC: already the 23rd in some places, still the 22nd in others
BOUNDARY = at(2026, 10, 22, 20, 30)


@pytest.mark.parametrize(
    ("zone", "today"),
    [
        (None, date(2026, 10, 22)),
        ("UTC", date(2026, 10, 22)),
        ("Asia/Kolkata", date(2026, 10, 23)),  # 02:00 on the 23rd
        ("Asia/Calcutta", date(2026, 10, 23)),  # the same zone, by its old name
        ("America/Los_Angeles", date(2026, 10, 22)),  # 13:30
        ("America/New_York", date(2026, 10, 22)),  # 16:30
        ("Europe/London", date(2026, 10, 22)),  # 21:30 (BST ended on the 25th)
        ("Pacific/Auckland", date(2026, 10, 23)),  # UTC+13: 09:30 on the 23rd
        ("Pacific/Kiritimati", date(2026, 10, 23)),  # UTC+14, the first place to reach a date
        ("Etc/GMT+12", date(2026, 10, 22)),  # UTC-12, the last
    ],
)
def test_today_is_the_users_local_day_at_the_same_instant(zone, today):
    assert calendar_at(BOUNDARY, zone).today == today


@pytest.mark.parametrize(
    ("moment", "today"),
    [
        (at(2026, 10, 22, 18, 29, 59), date(2026, 10, 22)),  # 23:59:59 in Asia/Kolkata
        (at(2026, 10, 22, 18, 30, 0), date(2026, 10, 23)),  # midnight there
        (at(2026, 10, 22, 18, 30, 1), date(2026, 10, 23)),
        (at(2026, 12, 31, 18, 30, 0), date(2027, 1, 1)),  # the year turns there first
        (at(2028, 2, 28, 18, 30, 0), date(2028, 2, 29)),  # a leap day
    ],
)
def test_the_day_turns_at_the_users_midnight_not_at_utc_midnight(moment, today):
    assert calendar_at(moment, "Asia/Kolkata").today == today


def test_tomorrow_uses_the_calendar_users_local_date_at_a_utc_boundary():
    """The same instant has different local dates, so tomorrow must differ too."""
    india = calendar_at(BOUNDARY, "Asia/Kolkata")
    utc = calendar_at(BOUNDARY)

    india_reading = read_requested_day(["move it to tomorrow"], india.today, 14)
    utc_reading = read_requested_day(["move it to tomorrow"], utc.today, 14)

    assert india_reading.kind == utc_reading.kind == "day"
    assert india_reading.dates == (date(2026, 10, 24),)
    assert utc_reading.dates == (date(2026, 10, 23),)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (at(2026, 10, 22, 23, 59, 59), date(2026, 10, 22)),
        (at(2026, 10, 23, 0, 0, 0), date(2026, 10, 23)),
    ],
)
def test_coach_tools_use_the_captured_utc_clock_when_timezone_is_omitted(moment, expected):
    assert coach_tools_at(moment).today == expected


def test_omitted_timezone_does_not_call_a_second_wall_clock(monkeypatch):
    monkeypatch.setattr(
        formiq_tools,
        "utc_today",
        lambda: pytest.fail("the omitted-timezone path must use the captured clock"),
    )
    assert coach_tools_at(at(2026, 10, 23, 0, 0)).today == date(2026, 10, 23)


def test_coach_tools_use_the_captured_instant_for_a_supplied_timezone():
    moment = at(2026, 10, 22, 20, 30)
    assert coach_tools_at(moment, "Asia/Kolkata").today == date(2026, 10, 23)


@pytest.mark.parametrize(
    ("moment", "today"),
    [
        (at(2026, 11, 1, 5, 59), date(2026, 11, 1)),  # 01:59 EDT, just before the clocks go back
        (at(2026, 11, 1, 6, 0), date(2026, 11, 1)),  # 01:00 EST: the same hour again
        (at(2026, 11, 1, 4, 59), date(2026, 11, 1)),  # 00:59 EDT
        (at(2026, 11, 1, 3, 59), date(2026, 10, 31)),  # 23:59 EDT the evening before
        (at(2026, 3, 8, 6, 59), date(2026, 3, 8)),  # 01:59 EST, just before the clocks go forward
        (at(2026, 3, 8, 7, 0), date(2026, 3, 8)),  # 03:00 EDT: an hour skipped
    ],
)
def test_a_clock_change_never_moves_the_date(moment, today):
    assert calendar_at(moment, "America/New_York").today == today


def test_tomorrow_is_the_next_calendar_day_whatever_the_length_of_the_day():
    """Days are dates, not 24-hour spans: the day the clocks change has 23 or 25 hours."""
    for moment in (at(2026, 11, 1, 5, 30), at(2026, 3, 8, 6, 30), BOUNDARY):
        today = calendar_at(moment, "America/New_York").today
        assert today + timedelta(days=1) == (datetime.combine(today, datetime.min.time()) + timedelta(hours=36)).date()


def test_the_calendar_says_which_zone_its_day_is_in_and_where_that_came_from():
    sent = calendar_at(BOUNDARY, "Asia/Kolkata")
    default = calendar_at(BOUNDARY)

    assert (sent.timezone, sent.source) == ("Asia/Kolkata", "request")
    # nothing sent: UTC, said so, and never taken for the user's own
    assert (default.timezone, default.source) == ("UTC", "default")
    assert calendar_at(BOUNDARY, "UTC").source == "request"


def test_a_moment_is_dated_in_the_users_zone_not_in_utc():
    """The last workout's completion time is a UTC timestamp: its day is the user's day."""
    calendar = calendar_at(BOUNDARY, "Asia/Kolkata")
    done = at(2026, 10, 22, 19, 0)  # 00:30 on the 23rd in Kolkata, still the 22nd in UTC

    assert calendar.local_date(done) == date(2026, 10, 23)
    assert calendar_at(BOUNDARY).local_date(done) == date(2026, 10, 22)
    # so "days ago" agrees with today in the same zone: both on the 23rd
    assert (calendar.today - calendar.local_date(done)).days == 0


def test_the_days_the_model_is_shown_start_today_and_cover_the_window():
    calendar = CoachCalendar(today=date(2026, 10, 23))

    days = calendar.upcoming()

    assert days[0] == date(2026, 10, 23)
    assert len(days) == 15 and days[-1] == date(2026, 11, 6)
    assert calendar.label(days[1]) == "Saturday 2026-10-24"


def test_a_clock_without_a_time_zone_is_refused():
    with pytest.raises(ValueError, match="time zone"):
        calendar_at(datetime(2026, 10, 22, 20, 30), "Asia/Kolkata")


@pytest.mark.parametrize("zone", ["Mars/Base", "asia/kolkata", "../etc/passwd", "", "IST", " UTC"])
def test_a_zone_the_database_does_not_have_is_an_error_never_a_fallback(zone):
    with pytest.raises(ValueError, match="not an IANA time zone"):
        calendar_at(BOUNDARY, zone)


@pytest.mark.parametrize(
    "name",
    [
        "UTC",
        "Asia/Kolkata",
        "Asia/Calcutta",
        "America/Argentina/Buenos_Aires",
        "America/Port-au-Prince",
        "Etc/GMT+12",
        "Europe/London",
    ],
)
def test_iana_names_are_zones(name):
    assert zone_of(name) is not None


@pytest.mark.parametrize(
    "name",
    [
        "",
        "asia/kolkata",  # a case-insensitive disk would open it, Linux would not: neither does
        "ASIA/KOLKATA",
        "Asia/Kolkata ",
        "Asia/Kolkata\n",
        "Asia/Kolkata; drop table users",
        "../etc/passwd",
        "/etc/localtime",
        "Mars/Base",
        "IST",
        "A" * 65,
        "Asia\\Kolkata",
        "Asia/Kolkata\x00",
    ],
)
def test_anything_else_is_not(name):
    assert zone_of(name) is None


def test_a_platform_with_no_time_zone_data_still_has_the_utc_calendar_and_refuses_every_other_zone(
    monkeypatch,
):
    """A slim container may have no tzdata (and none may be added): the default calendar, which
    every request without a zone uses, never opens the database, and a zone is refused rather than
    guessed, so the app's retry without one (frontend/src/api/coach.ts) gets the coach working."""
    from app.schemas import timezone

    monkeypatch.setattr(timezone, "available_timezones", lambda: set())
    timezone._database.cache_clear()
    try:
        calendar = calendar_at(BOUNDARY)

        assert calendar.today == date(2026, 10, 22)
        assert calendar.local_date(at(2026, 10, 22, 19, 0)) == date(2026, 10, 22)
        assert zone_of("UTC") is not None
        assert zone_of("Asia/Kolkata") is None
        with pytest.raises(ValueError, match="not an IANA time zone"):
            calendar_at(BOUNDARY, "Asia/Kolkata")
    finally:
        timezone._database.cache_clear()
