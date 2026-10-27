"""The coach's calendar: which day it is, for whom (Phase 2.7).

The Phase 2.6 live pass found the model resolving "tomorrow" to the wrong date in two of
three first drafts: it was never told the date, and Formiq's "today" was the UTC date, which
is not the user's date for hours of every day (at 02:00 in Asia/Kolkata it is still
yesterday in UTC). The contract is now explicit and is never mixed:

- the coach's day is the user's LOCAL day, in the IANA time zone the app sends with each
  coach message (`timezone`, e.g. "Asia/Kolkata"): validated here, refused with a 422 when it
  is not one, never guessed or silently replaced;
- when a request sends none the day is the UTC day, and the calendar says so (source
  "default"): the model is told it, and the answer to "tomorrow" is then UTC's tomorrow;
- the date is worked out from Formiq's clock (ProposalTerms.clock), once per request, and
  every date the tools show, compare or refuse is in it: "today", `days_from_today`, the
  14-day window, "days ago" for the last workout (the time it was completed is read in the
  same zone) and the calendar the model is given;
- nothing in it is the user's text: the zone must be a key of the time zone database, and the
  date comes from the clock. The note to the model (app.agent.graph.date_note) is Formiq's.

The zone comes from the client, so a client can pick the date it calls "today" by up to a day
either way. That is bounded by what a user can do to their own data: it authorizes nothing and
reaches no other user's.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo

from app.schemas.timezone import zone_of

DEFAULT_TIMEZONE = "UTC"
# how many days of the calendar the model is shown: today, and the 14 a workout may be planned for
CALENDAR_DAYS = 15


@dataclass(frozen=True)
class CoachCalendar:
    """Today, as the user has it, and the zone it was worked out in."""

    today: date
    timezone: str = DEFAULT_TIMEZONE
    # "request": the app sent the zone; "default": it sent none, so the day is the UTC day
    source: str = "default"

    @property
    def zone(self) -> tzinfo:
        zone = zone_of(self.timezone)
        if zone is None:  # built by calendar_at, which checked it
            raise ValueError(f"{self.timezone!r} is not a time zone")
        return zone

    def local_date(self, moment: datetime) -> date:
        """The calendar day of a moment (a timestamp with a time zone) in the user's zone."""
        return moment.astimezone(self.zone).date()

    def upcoming(self, count: int = CALENDAR_DAYS) -> list[date]:
        """Today and the days after it."""
        return [self.today + timedelta(days=offset) for offset in range(count)]

    def label(self, day: date) -> str:
        """A day as the model is told it: "Friday 2026-10-23"."""
        return f"{day:%A} {day.isoformat()}"


def calendar_at(now: datetime, timezone: str | None = None) -> CoachCalendar:
    """The calendar at this moment (a timestamp with a time zone, Formiq's clock) for a user in
    this zone, or in UTC when none is given. ValueError for a zone the database does not have:
    the request schema refuses it first, so this is a programming error, never a fallback."""
    if now.tzinfo is None:
        raise ValueError("the clock must give a time with a time zone")
    if timezone is None:
        return CoachCalendar(today=now.astimezone(UTC).date())
    zone = zone_of(timezone)
    if zone is None:
        raise ValueError(f"{timezone!r} is not an IANA time zone")
    return CoachCalendar(today=now.astimezone(zone).date(), timezone=timezone, source="request")
