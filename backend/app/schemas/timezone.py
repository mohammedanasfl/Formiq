"""IANA time zone names, validated (Phase 2.7).

The coach's calendar is the user's local day (app.tools.coach_calendar), and the zone comes
from the app with each coach message. A zone is accepted only as a key of the time zone
database ("Asia/Kolkata", "UTC"), spelled as the database spells it: never a guess, a path,
free text, or a spelling that only some platforms' file systems would find ("asia/kolkata"
opens a file on a case-insensitive disk and none on Linux, so it is refused on both). This
module has no dependencies on the rest of the application (and so loads no configuration or
data layer): the request schema and the agent-side tools both use it.
"""

import re
from datetime import UTC, tzinfo
from functools import cache
from zoneinfo import ZoneInfo, available_timezones

# an IANA key: letters, digits and _ + - / only, short
TIMEZONE_PATTERN = r"^[A-Za-z0-9_+\-/]{1,64}$"
_TIMEZONE = re.compile(TIMEZONE_PATTERN)


@cache
def _database() -> frozenset[str]:
    """The keys of the platform's time zone database, read once."""
    return frozenset(available_timezones())


def zone_of(name: str) -> tzinfo | None:
    """The time zone named by an IANA key such as "Asia/Kolkata", or None if it is not one (a
    different spelling, a path, anything outside the time zone database). "UTC" is always one, with
    or without a database: a server with no time zone data (a slim container) still has the UTC
    calendar every request without a zone uses, and every other zone is then refused, never guessed."""
    if name == "UTC":
        return UTC
    if not _TIMEZONE.fullmatch(name) or name not in _database():
        return None
    try:
        return ZoneInfo(name)
    except Exception:  # a database entry whose data cannot be read
        return None
