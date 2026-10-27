"""Pure tests for the model-selected scheduled date boundary.

The user words are resolved by app.tools.schedule; FormiqTools._checked_day then holds the
model's selected date to that result. These tests use fixed dates and mocked services only.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.tools import FormiqTools, ToolError, ToolErrorCode
from app.tools.schedule import read_requested_day

TODAY = date(2026, 10, 23)  # Friday
MONDAY = date(2026, 10, 26)
SATURDAY = date(2026, 10, 24)
SUNDAY = date(2026, 10, 25)


def tools_for(*user_messages: str) -> FormiqTools:
    return FormiqTools(
        users=Mock(),
        profiles=Mock(),
        plans=Mock(),
        sessions=Mock(),
        catalog=Mock(),
        end_read=Mock(),
        today=TODAY,
        conversation=[("user", message) for message in user_messages],
    )


def saved_plan(day: date = MONDAY):
    return SimpleNamespace(id=41, scheduled_date=day)


@pytest.mark.parametrize(
    ("message", "selected", "original", "moving"),
    [
        ("Move it to tomorrow", SUNDAY, saved_plan(), True),
        ("Schedule the workout for tomorrow", SUNDAY, None, False),
        ("Move it to 2026-10-30", SATURDAY, saved_plan(), True),
    ],
    ids=["moved-tomorrow", "new-tomorrow", "explicit-date"],
)
def test_a_model_selected_date_that_disagrees_with_the_users_words_is_rejected(
    message, selected, original, moving
):
    tools = tools_for(message)

    with pytest.raises(ToolError) as raised:
        tools._checked_day(7, original, selected, moving=moving)

    assert raised.value.code == ToolErrorCode.INVALID_INPUT
    assert "not" in raised.value.message or "asked" in raised.value.message


def test_a_model_selected_date_that_matches_tomorrow_is_accepted():
    tools_for("Move it to tomorrow")._checked_day(7, saved_plan(), SATURDAY, moving=True)


def test_an_ambiguous_weekend_is_rejected_instead_of_picking_saturday_or_sunday():
    tools = tools_for("Move it to the weekend")

    with pytest.raises(ToolError, match="(?i)do not choose a day") as raised:
        tools._checked_day(7, saved_plan(), SATURDAY, moving=True)

    assert raised.value.code == ToolErrorCode.INVALID_INPUT
    assert "Saturday" in raised.value.message and "Sunday" in raised.value.message


def test_a_correction_supersedes_the_old_date_without_creating_another_date():
    tools = tools_for("Move it to Monday and make it harder", "No wait, Wednesday")

    reading = tools._requested_day()

    assert reading.kind == "day"
    assert reading.dates == (date(2026, 10, 28),)
    assert reading.words == "Wednesday"
    # Date interpretation does not rewrite the unrelated workout request.
    assert tools.user_words == ["Move it to Monday and make it harder", "No wait, Wednesday"]


def test_weekday_and_explicit_date_are_distinguished_when_they_conflict():
    reading = read_requested_day(["Move it to Friday, October 28"], TODAY, 14)

    assert reading.kind == "ambiguous"
    assert set(reading.dates) == {
        date(2026, 10, 23),  # the bare Friday's first possible occurrence
        date(2026, 10, 28),  # the explicit date
        date(2026, 10, 30),  # the bare Friday's later possible occurrence
    }
