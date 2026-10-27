"""The day a user's words ask for, read deterministically (Phase 2.7).

A revision of a saved plan keeps the plan's own day (Phase 2.3). It may move to another day
only when the user asked for one, and (Phase 2.7) only to THE day they asked for. Until then
Formiq checked that the user had named *a* day somewhere and then took the model's word for
which: the Phase 2.6 live pass found "tomorrow" resolved to the wrong date in two of three
first drafts, and "the weekend" answered with a day without asking. Now the user's own words
are resolved to dates here, by rules, from the calendar's today (app.tools.coach_calendar:
the user's local day), and the model's date must be one of them:

- one day, the answer is that day: today, tonight, tomorrow, the day after tomorrow, "in 3
  days", "3 days from now", "a week from Friday", a weekday, "this Friday", "next Friday",
  "Friday next week", a date ("2026-10-28", "Oct 28", "28th of October", "28-Oct", "28/10",
  "28.10.2026") and "on the 28th". A bare weekday is the next one after today; a calendar
  date without a year is the next one on or after today;
- two or more days, the answer is "ask": a period names no one day ("next week", "the
  weekend", "next month"), and neither does a word that fits two days: a weekday said on that
  very weekday (today, or in a week?), "next Friday" said earlier in the same week (this one,
  or the one a week later?), "Friday or Saturday", "Monday to Friday", "Friday, Oct 28" when
  Oct 28 is not a Friday, "this Friday, Oct 30" when this Friday is Oct 23, and a day given
  relative to another ("after Friday", "the day before Saturday"). A slash date with no
  component above 12 ("03/04") is read as no day at all: the coach asks, as it does when no
  day is named;
- a day outside the window (before today, or more than `days_ahead` after it) is outside.

What a day is said OF decides whether it is where the workout goes (Phase 2.7, after an
adversarial review): it is not when the user says where the workout WAS ("from Monday",
"instead of Friday", "not Friday", "my Saturday workout"), when they say they cannot or did
("I can't make it Monday", "I'm busy Saturday", "I did legs on Monday", "Monday doesn't work")
or when it only bounds a range; it is where it goes after "to", "for", "make it", "how about",
"can we do", "put it on", and when it corrects what came before ("no wait, Sunday"). Several days
in one message with none marked ("Friday or Saturday") are all asked about.

Only a message that is plainly a request counts: it holds a day marked as where the workout
goes or a correction, or says nothing but days and neutral move words ("Friday please"), or has
a word for moving. "I ran on Thursday" and "exams are next week" name days and ask for nothing.
The newest such message decides, so an answer to the coach's question ("Saturday") settles "the
weekend"; a message that names no day leaves the earlier one standing, unless it takes that day
back ("no, not Monday"). What the user wrote is the only input: the coach's own turns are the
client's claim, never read.

Known English words and dates only, like app.tools.muscles. It leaves out what a fitness
message says far more often than a date: "8-12 reps", "12.5 kg", "1:30 rest", "the 3rd set",
"16/8 fasting", "3/4 squats". Reading words can miss a phrasing, and then no day was named and
the workout stays on its day, or the coach asks, which are the safe ways to be wrong.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Literal

_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thurs": 3, "thur": 3, "thu": 3, "friday": 4, "fri": 4, "saturday": 5,
    "sat": 5, "sunday": 6, "sun": 6,
}  # fmt: skip
_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12,
    "dec": 12,
}  # fmt: skip
_COUNTS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}  # fmt: skip


def _alternation(words) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


_WD = _alternation(_WEEKDAYS)
_MONTH = _alternation(_MONTHS)
_COUNT = rf"\d{{1,3}}|{_alternation(_COUNTS)}"
# what makes "the 2nd" or "12 dec" not a date: the thing counted or done
_ORDINAL_NOT = (
    r"set|rep|round|exercise|time|workout|circuit|day|week|month|minute|hour|session|attempt|phase|"
    r"cycle|block|lap|interval|step|try|visit|class|serving|meal|place|floor|stage|level|"
    r"anniversary|birthday|workouts|sets|reps"
)
_MONTH_NOT = (
    r"seconds?|secs?|minutes?|mins?|hours?|reps?|sets?|kgs?|lbs?|pounds?|rounds?|x\b|push|pull|"
    r"squat|lunge|sit|crunch|burpee|jump|hold|plank|cardio|laps?|meters?|metres?|miles?|km|steps?|"
    r"calories|kcal|%"
)

# Each alternative is one way of naming a day; the first that matches at a position wins, so a
# longer form ("Friday next week", "next Friday") is tried before the weekday inside it.
_MENTION = re.compile(
    rf"""
      (?P<after>\b(?:the\s+)?day\s+after\s+tomorrow\b)
    | \b(?P<fn_count>{_COUNT})\s+(?P<fn_unit>days?|weeks?)\s+(?:from|after)\s+
        (?P<fn_base>today|now|tomorrow|{_WD})\b
    | (?P<rel>\b(?:tomorrow|tmrw|tonight|today|later\s+today|this\s+(?:morning|afternoon|evening))\b)
    | \bin\s+(?P<count>{_COUNT})\s+(?P<unit>days?|weeks?|months?)\b
    | \b(?P<wdw>{_WD})\b\s+(?:(?:of|in|on)\s+)?(?P<wdw_week>next|this)\s+week\b
    | \b(?P<wk_week>next|this)\s+week(?:['’]s)?(?:,\s*|\s+)(?:on\s+)?(?P<wk_wd>{_WD})\b
    | \b(?P<which>next|this|coming|upcoming)\s+(?P<which_wd>{_WD})\b
    | \b(?P<period_which>next|this)\s+(?P<period>week|month)\b
    | \b(?:(?P<we_which>next|this|the)\s+)?(?P<weekend>weekend)\b
    | \b(?P<iso_y>\d{{4}})[-/.](?P<iso_m>\d{{1,2}})[-/.](?P<iso_d>\d{{1,2}})\b
    | (?<![\d./-])(?P<n1>\d{{1,2}})(?P<nsep>[./-])(?P<n2>\d{{1,2}})(?P=nsep)(?P<ny>\d{{4}})(?![\d./-])
    | \b(?P<dm_d>\d{{1,2}})(?:st|nd|rd|th)?(?:\s+|[-/])(?:of\s+)?(?P<dm_m>{_MONTH})\b\.?
        (?:,?\s+(?P<dm_y>\d{{4}}))?(?!\s+(?:{_MONTH_NOT}))
    | \b(?P<md_m>{_MONTH})\b\.?(?:\s+|-)(?P<md_d>\d{{1,2}})(?:st|nd|rd|th)?\b
        (?:,?\s+(?P<md_y>\d{{4}}))?(?!\s+(?:{_MONTH_NOT}))
    | \b(?P<wd_ord_wd>{_WD})\b[,.]?\s+(?:the\s+)?(?P<wd_ord>\d{{1,2}})(?:st|nd|rd|th)\b
      (?:\s+of\s+(?P<wd_ord_m>{_MONTH})\b\.?)?(?!\s+(?:{_ORDINAL_NOT}))
    | \b(?:on|to|for|until|till|by|or|and|make\s+it|do\s+it\s+on|let['’]s\s+do|how\s+about)\s+
        (?:the\s+)?(?P<ord>\d{{1,2}})(?:st|nd|rd|th)\b(?:\s+of\s+(?P<ord_m>{_MONTH})\b\.?)?
        (?!\s+(?:{_ORDINAL_NOT}))
    | (?<![\w'’])(?:the\s+)?(?P<ord_bare>\d{{1,2}})(?:st|nd|rd|th)\b
        (?:\s+of\s+(?P<ord_bare_m>{_MONTH})\b\.?)?(?!\s+(?:{_ORDINAL_NOT}))
    | (?<![\d/.])(?P<s1>\d{{1,2}})/(?P<s2>\d{{1,2}})(?:/(?P<sy>\d{{4}}|\d{{2}}))?(?![\d/.])
    | \b(?P<wd>{_WD})\b(?!\s+(?:blues|motivation|vibes|mood|blahs))
    """,
    re.IGNORECASE | re.VERBOSE,
)

# --- what a day is said OF: the text before it (and after it) says where the workout goes ---

# said of a day it is leaving, or one to avoid
_SOURCE = re.compile(
    r"(?:\bfrom|\binstead\s+of|\brather\s+than|\bother\s+than|\bnot|\bexcept|\bthan|\bavoid|\bskip|"
    r"\bexcluding|\bapart\s+from|\bbesides|\b(?:anything|everything|any\s+day|every\s+day)\s+but)\s+"
    r"(?:(?:the|my|this|that|on|a)\s+)?$",
    re.IGNORECASE,
)
# "starting from Monday" is where it begins, not what it leaves
_STARTING = re.compile(r"\b(?:starting|beginning|going|counting)\s+from\s+(?:the\s+)?$", re.IGNORECASE)
# a day it goes to, right before the day
_TARGET = re.compile(
    r"(?:\bto|\bonto|\bfor|\bmake\s+it|\bmake\s+that|\bswitch\s+to|\bchange\s+(?:it\s+)?to|"
    r"\bpush\s+(?:it\s+)?to|\bput\s+(?:it\s+)?on|\bdo\s+it(?:\s+on)?|\blet['’]s\s+do|\bhow\s+about|"
    r"\bwhat\s+about|\b(?:can|could|shall)\s+we\s+(?:do|go|try|make\s+it)|\bgo\s+with|\bpick|"
    r"\bchoose|\bprefer|\bmove\s+it(?:\s+on)?|\bon\s+to)\s+(?:(?:the|on|a|an)\s+)?$",
    re.IGNORECASE,
)
# somewhere in the clause: a day that is gone to, said after a refusal ("I can't, how about ...")
_TARGET_ANY = re.compile(
    r"\b(?:to|onto|how\s+about|what\s+about|let['’]s|(?:can|could|shall)\s+we|make\s+it|"
    r"do\s+it\s+on|put\s+it\s+on|switch\s+to|go\s+with)\b",
    re.IGNORECASE,
)
# a day that takes back what came before: "no wait, Sunday", "actually make it Tuesday"
_CORRECTION = re.compile(
    r"(?:\bno\s*,?\s*wait|\bwait\s*,?\s*no|\bactually|\bsorry|\bi\s+mean|\bmake\s+that|"
    r"\bscratch\s+that|\brather|\bcorrection|\bon\s+second\s+thought|\bnever\s*mind|\bnvm|\boops|"
    r"\binstead)\W+(?:(?:make\s+it|do\s+it|put\s+it|let['’]s\s+do|how\s+about|to|on|the|for)\s+)*$",
    re.IGNORECASE,
)
# what a clause says that the day is NOT where it goes: a refusal, a thing that was done
_REFUSAL = re.compile(
    r"\b(?:can['’]?t|cannot|can\s+not|won['’]t|will\s+not|unable\s+to|not\s+able\s+to|don['’]t|"
    r"do\s+not|doesn['’]t|does\s+not|haven['’]t|hasn['’]t|have\s+not|hadn['’]t|didn['’]t|did\s+not|"
    r"never|busy|away|unavailable|out\s+of\s+town|did|trained|ran|worked|went|finished|completed|"
    r"hit|lifted|swam|rode|skipped|missed|done)\b"
    r"(?:\s+(?:possibly\s+)?(?:make\s+it|do\s+it|train|go|attend|come|work\s*out|workout))?",
    re.IGNORECASE,
)
# a day said of something else: "doesn't work", "is booked"
_AFTER_NEGATION = re.compile(
    r"^\s*(?:doesn['’]t|does\s+not|won['’]t|will\s+not|isn['’]t|is\s+not|is\s+out|is\s+no\s+good|"
    r"is\s+bad|is\s+busy|is\s+taken|is\s+booked|is\s+a\s+no|no\s+good|can['’]t|cannot)\b",
    re.IGNORECASE,
)
# "my Saturday workout", "Monday's session": the day the plan is on, not a day to go to
_DESCRIPTOR = re.compile(
    r"^(?:['’]s)?\s+(?:workouts?|sessions?|plans?|routines?|training|class(?:es)?)\b", re.IGNORECASE
)
# a day given relative to another, which names neither: "after Friday", "the day before Saturday"
_RELATIVE_TO = re.compile(
    r"(?:\b(?:before|after|by|until|till|prior\s+to|following)|\bday\s+(?:before|after)|"
    r"\bnight\s+before)\s+(?:the\s+)?$",
    re.IGNORECASE,
)
# a weekday that is not one to go to: "last Friday", "every Friday"
_NOT_A_DAY_AHEAD = re.compile(r"\b(?:last|previous|past|every|each)\s+$", re.IGNORECASE)
# "sat" and "sun" are everyday words: read as days only where something says they are
_SAT_SUN_AFTER = re.compile(
    r"\b(?:to|on|for|this|next|by|until|till|from|make\s+it|not|than|do|do\s+it|let['’]s\s+do|"
    r"how\s+about|what\s+about|go\s+with|pick|choose|take|prefer)\s+$",
    re.IGNORECASE,
)
_SAT_SUN_NOT = re.compile(
    r"^\s+(?:salutations?|rays?|screen|cream|block|light|shine|bed|burn|tan|hat|glasses|protection|"
    r"set|rise|down|up)\b",
    re.IGNORECASE,
)
_SAT_SUN_DATE = re.compile(
    rf"^[\s,.()\-–—]*(?:the\s+)?(?:\d{{1,2}}(?:st|nd|rd|th)?\b|(?:{_MONTH})\b)", re.IGNORECASE
)
# a message that is only "Sat", "Sun works", "Sat or Sun?": an answer to "which day?"
_SAT_SUN_ANSWER = re.compile(
    r"^\W*(?:(?:ok(?:ay)?|yes|yeah|sure|maybe|probably|let['’]s\s+do|how\s+about)\W+)*"
    r"(?:sat|sun)(?:\W+(?:or|and|/)\W+(?:sat|sun|saturday|sunday))?"
    r"(?:\W+(?:works?|please|pls|is\s+(?:fine|good|best)|then|instead))*\W*$",
    re.IGNORECASE,
)
# a weekday right before: "Friday the 30th"
_AFTER_WEEKDAY = re.compile(rf"\b(?:{_WD})\b[,.]?\s+$", re.IGNORECASE)
# before a slash date: a word that points at a day
_POINTS_AT = re.compile(
    r"\b(?:on|to|for|until|till|by|make\s+it|do\s+it\s+on|let['’]s\s+do|how\s+about|move\s+it|from)"
    r"\s+(?:the\s+)?$",
    re.IGNORECASE,
)
# between a weekday and the date it goes with: "Friday, October 30", "Friday the 30th", "(Friday)"
_JOIN = re.compile(r"^[\s,.()\-–—:]*(?:(?:the|on)\s+)?$", re.IGNORECASE)
# between two days: "Friday or Saturday", and a span, "Monday to Friday"
_OR_GAP = re.compile(r"^\s*(?:,\s*)?(?:or|and|/|&)\s+(?:on\s+|to\s+|for\s+)?$", re.IGNORECASE)
_SAME_BREATH = re.compile(r"^[^.?!;]{0,40}$")
_RANGE_GAP = re.compile(r"^\s*(?:to|through|thru|until|till|-|–|—)\s*$", re.IGNORECASE)
# the boundary of a clause, for what is said of a day: punctuation, or a word that turns the sentence
_CLAUSE_BREAK = re.compile(r"[.;!?,]|\b(?:but|so|then|however|although|though)\b", re.IGNORECASE)
# a word for moving a workout to another day
_MOVE_VERB = re.compile(
    r"\b(?:move|moving|moved|reschedul\w*|push(?:ed|ing)?|shift(?:ed|ing)?|postpone\w*|delay\w*|"
    r"switch|book|schedule[ds]?|bring\s+(?:it\s+)?forward)\b",
    re.IGNORECASE,
)

# The words a message may hold besides the days it names and still ask for nothing but a move: "Can
# you reschedule it for Friday, please?", "Just put it on Saturday instead". Anything else (swap,
# harder, add, a weight, "I have no bench", "but skip lunges", any number of sets) is a word that
# may ask for more.
_MOVE_ONLY_WORDS = frozenset(
    """
    move moving reschedule rescheduling push shift put set do make it this that the my our its to on onto for
    from instead please pls thanks thank thx ok okay hi hey hello yes yep no wait actually sorry can could you
    would will may might we i i'd id i'll ill like want need prefer rather let's lets workout workouts plan plans
    session sessions routine training day date schedule scheduled so then and just only a an also again now same
    one is be are was if possible at in by until till of mean works work fine good great better should shall
    or think guess suppose probably maybe perhaps best suits suit us me go ahead sure through thru
    over during within around about sometime whenever morning afternoon evening night noon midday am pm
    early late
    """.split()
)
# words that only say which day NOT to use, allowed in a message that is a request ("not Monday, Wednesday"),
# though not in one that is only a move: there they may be saying what else to change
_REQUEST_WORDS = frozenset(
    "not but except than anything everything any avoid before after prior following".split()
)


@dataclass(frozen=True)
class Mention:
    """One naming of a day in a message, resolved against today."""

    words: str
    # every day it could mean, in order, whatever the window
    options: tuple[date, ...]
    # a period, or days that disagree: it never names one day, however few of them fall in the window
    open: bool = False
    weekday: int | None = None
    explicit: bool = False
    # "this" or "next": the weekday says which one, so a date that disagrees is a conflict
    qualified: bool = False
    marker: Literal["", "source", "target", "correction"] = ""
    start: int = 0
    end: int = 0


@dataclass(frozen=True)
class DayReading:
    """What the user's words say of the day:

    - none: they name no day;
    - day: exactly one (dates), inside the window;
    - ambiguous: they leave it open (options inside the window, `dates`; `options` is all of
      them), so the coach asks;
    - outside: they name a day, none of it inside the window."""

    kind: Literal["none", "day", "ambiguous", "outside"]
    dates: tuple[date, ...] = ()
    words: str = ""
    options: tuple[date, ...] = ()


def _date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _next_dated(today: date, month: int, day: int, year: int | None = None) -> date | None:
    """A date: in the year given, or else the first on or after today (this year's, or next)."""
    if year is not None:
        return _date(year, month, day)
    for candidate_year in (today.year, today.year + 1):
        found = _date(candidate_year, month, day)
        if found is not None and found >= today:
            return found
    return None


def _day_of_month(today: date, day: int) -> date | None:
    """The first day on or after today that is the `day`th of its month."""
    year, month = today.year, today.month
    for _ in range(14):
        found = _date(year, month, day)
        if found is not None and found >= today:
            return found
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None


def _months_after(today: date, months: int) -> date:
    """The same day of the month `months` later, or the last day of a shorter month."""
    index = today.month - 1 + months
    year, month = today.year + index // 12, index % 12 + 1
    day = today.day
    while (found := _date(year, month, day)) is None:
        day -= 1
    return found


def _weekday_options(today: date, weekday: int, which: str) -> tuple[date, ...]:
    ahead = (weekday - today.weekday()) % 7
    on_or_after = today + timedelta(days=ahead)
    after = today + timedelta(days=ahead or 7)
    if which in ("this", "coming", "upcoming"):
        return (on_or_after,)
    if which == "next":
        # this week's, or the one a week later: two days unless this week's has passed
        same_week = after.isocalendar()[:2] == today.isocalendar()[:2]
        return (after, after + timedelta(days=7)) if same_week else (after,)
    # said alone: the next one; on that very weekday, today or in a week
    return (today, today + timedelta(days=7)) if ahead == 0 else (after,)


def _week_of(today: date, which: str) -> list[date]:
    monday = today - timedelta(days=today.weekday()) + timedelta(days=7 if which == "next" else 0)
    return [monday + timedelta(days=offset) for offset in range(7)]


def _month_of(today: date, which: str) -> list[date]:
    year, month = today.year, today.month
    if which == "next":
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    first = date(year, month, 1)
    days = []
    while first.month == month:
        days.append(first)
        first += timedelta(days=1)
    return days


def _words_of(rest: str) -> list[str]:
    return re.findall(r"[a-z]+(?:'[a-z]+)?", rest.replace("’", "'").lower())


def _neutral_outside(
    text: str, spans: Sequence[tuple[int, int]], more: frozenset[str] = frozenset()
) -> bool:
    """Whether everything outside these spans of the text is a neutral move word (_MOVE_ONLY_WORDS,
    and `more`)."""
    rest = text
    for start, end in sorted(spans, reverse=True):
        rest = rest[:start] + " " + rest[end:]
    return all(word in _MOVE_ONLY_WORDS or word in more for word in _words_of(rest))


def _sat_sun_read(found: re.Match[str], name: str, start: int, end: int) -> bool:
    """Whether "sat" or "sun" here is a day and not a word: the full names always are, the short
    ones when something points at them (to, on, this ...), a date follows ("Sat 24th") or the
    whole message is the answer ("Sat or Sun?")."""
    if name not in ("sat", "sun"):
        return True
    text = found.string
    after = text[end:]
    if _SAT_SUN_NOT.match(after):
        return False
    return bool(
        _SAT_SUN_AFTER.search(text[max(0, start - 30) : start])
        or _SAT_SUN_DATE.match(after)
        or _SAT_SUN_ANSWER.match(text)
    )


def _mention(found: re.Match[str], today: date) -> Mention | None:
    """The mention a match is, or None when it is not a day after all (an impossible date, a slash
    that could be either order or has nothing pointing at it, "last Friday", "sat down")."""
    text = found.string
    words = " ".join(found.group().split())
    base = {"words": words, "start": found.start(), "end": found.end()}
    before = text[max(0, found.start() - 30) : found.start()]
    if found["after"]:
        return Mention(options=(today + timedelta(days=2),), **base)
    if found["fn_count"]:
        raw = found["fn_count"].lower()
        count = int(raw) if raw.isdigit() else _COUNTS[raw]
        shift = timedelta(days=count * (7 if found["fn_unit"].lower().startswith("week") else 1))
        anchor = found["fn_base"].lower()
        if anchor in ("today", "now"):
            return Mention(options=(today + shift,), **base)
        if anchor == "tomorrow":
            return Mention(options=(today + timedelta(days=1) + shift,), **base)
        starts = _weekday_options(today, _WEEKDAYS[anchor], "")
        return Mention(
            options=tuple(day + shift for day in starts), open=len(starts) > 1, **base
        )
    if found["rel"]:
        lowered = found["rel"].lower()
        shift = 1 if lowered in ("tomorrow", "tmrw") else 0
        return Mention(options=(today + timedelta(days=shift),), **base)
    if found["count"]:
        raw = found["count"].lower()
        count = int(raw) if raw.isdigit() else _COUNTS[raw]
        unit = found["unit"].lower()
        if unit.startswith("month"):
            return Mention(options=(_months_after(today, count),), **base)
        weeks = unit.startswith("week")
        return Mention(options=(today + timedelta(days=count * (7 if weeks else 1)),), **base)
    if found["wdw"] or found["wk_wd"]:
        name = (found["wdw"] or found["wk_wd"]).lower()
        which = (found["wdw_week"] or found["wk_week"]).lower()
        if found["wdw"] and not _sat_sun_read(found, name, found.start(), found.end()):
            return None
        weekday = _WEEKDAYS[name]
        return Mention(
            options=(_week_of(today, which)[weekday],), weekday=weekday, qualified=True, **base
        )
    if found["which_wd"]:
        weekday = _WEEKDAYS[found["which_wd"].lower()]
        options = _weekday_options(today, weekday, found["which"].lower())
        return Mention(options=options, weekday=weekday, qualified=True, **base)
    if found["period"]:
        which, period = found["period_which"].lower(), found["period"].lower()
        days = _week_of(today, which) if period == "week" else _month_of(today, which)
        return Mention(options=tuple(days), open=True, **base)
    if found["weekend"]:
        which = (found["we_which"] or "this").lower()
        saturday = _week_of(today, "next" if which == "next" else "this")[5]
        return Mention(options=(saturday, saturday + timedelta(days=1)), open=True, **base)
    if found["iso_y"]:
        day = _date(int(found["iso_y"]), int(found["iso_m"]), int(found["iso_d"]))
        return None if day is None else Mention(options=(day,), explicit=True, **base)
    if found["n1"]:
        # 28.10.2026, 28-10-2026, 10/28/2026: the order is read only when one number cannot be a month
        first, second = int(found["n1"]), int(found["n2"])
        if first > 12 >= second >= 1:
            number, month = first, second
        elif second > 12 >= first >= 1:
            number, month = second, first
        else:
            return None
        day = _date(int(found["ny"]), month, number)
        return None if day is None else Mention(options=(day,), explicit=True, **base)
    if found["dm_m"] or found["md_m"]:
        month = _MONTHS[(found["dm_m"] or found["md_m"]).lower()]
        number = int(found["dm_d"] or found["md_d"])
        year = found["dm_y"] or found["md_y"]
        day = _next_dated(today, month, number, int(year) if year else None)
        return None if day is None else Mention(options=(day,), explicit=True, **base)
    if found["wd_ord"]:
        name = found["wd_ord_wd"].lower()
        if not _sat_sun_read(found, name, found.start(), found.start() + len(name)):
            return None
        weekday = _WEEKDAYS[name]
        if found["wd_ord_m"]:
            day = _next_dated(today, _MONTHS[found["wd_ord_m"].lower()], int(found["wd_ord"]))
        else:
            day = _day_of_month(today, int(found["wd_ord"]))
        if day is None:
            return None
        # "Friday the 30th": one day when the 30th is a Friday, else the two disagree
        agrees = day.weekday() == weekday
        options = (day,) if agrees else tuple(sorted({day, *_weekday_options(today, weekday, "")}))
        return Mention(options=options, weekday=weekday, explicit=True, open=not agrees, **base)
    if found["ord"] or found["ord_bare"]:
        if (
            found["ord_bare"]
            and not _neutral_outside(text, [(found.start(), found.end())])
            and not _AFTER_WEEKDAY.search(text[: found.start()])
        ):
            # "the 28th" with nothing pointing at it is a day only as the whole of the message, or
            # beside the weekday it goes with ("this Friday the 30th of October")
            return None
        number = int(found["ord"] or found["ord_bare"])
        month_word = found["ord_m"] or found["ord_bare_m"]
        day = (
            _next_dated(today, _MONTHS[month_word.lower()], number)
            if month_word
            else _day_of_month(today, number)
        )
        return None if day is None else Mention(options=(day,), explicit=True, **base)
    if found["s1"]:
        first, second = int(found["s1"]), int(found["s2"])
        # the order is read only when one number cannot be a month: "28/10" and "10/28"
        if first > 12 >= second >= 1:
            day_number, month = first, second
        elif second > 12 >= first >= 1:
            day_number, month = second, first
        else:
            return None
        year = found["sy"]
        # "16/8 fasting", "Tabata 20/10", "24/7": a ratio unless a year, a word that points at a day,
        # or nothing else in the message says otherwise
        spans = [(found.start(), found.end())]
        if not (year and len(year) == 4) and not (
            _POINTS_AT.search(before) or _neutral_outside(text, spans)
        ):
            return None
        full = None if year is None else (int(year) if len(year) == 4 else 2000 + int(year))
        day = _next_dated(today, month, day_number, full)
        return None if day is None else Mention(options=(day,), explicit=True, **base)
    name = found["wd"].lower()
    if _NOT_A_DAY_AHEAD.search(before) or not _sat_sun_read(found, name, found.start(), found.end()):
        return None
    weekday = _WEEKDAYS[name]
    return Mention(options=_weekday_options(today, weekday, ""), weekday=weekday, **base)


def _clause_before(text: str, start: int) -> str:
    """The words of the clause a day is in, up to the day: after the last punctuation or turning word."""
    chunk = text[max(0, start - 80) : start]
    breaks = list(_CLAUSE_BREAK.finditer(chunk))
    return chunk[breaks[-1].end() :] if breaks else chunk


def _marked(mention: Mention, text: str) -> Mention:
    """The mention with what is said of it: where the workout goes, where it was, or a correction."""
    before = text[max(0, mention.start - 40) : mention.start]
    after = text[mention.end : mention.end + 40]
    clause = _clause_before(text, mention.start)
    marker: Literal["", "source", "target", "correction"] = ""
    if _STARTING.search(before):
        marker = "target"
    elif _SOURCE.search(before):
        marker = "source"
    elif _CORRECTION.search(before):
        marker = "correction"
    elif (refusal := list(_REFUSAL.finditer(clause))) and not _TARGET_ANY.search(
        clause[refusal[-1].end() :]
    ):
        # "I can't make it Monday", "I'm busy Saturday", "I did legs on Monday"
        marker = "source"
    elif _TARGET.search(before):
        marker = "target"
    if marker == "" and (_AFTER_NEGATION.match(after) or _DESCRIPTOR.match(after)):
        # "Monday doesn't work", "my Saturday workout": the day it is on, not a day to go to
        marker = "source"
    open_ = mention.open or bool(_RELATIVE_TO.search(before))
    return replace(mention, marker=marker, open=open_)


def _merged(first: Mention, second: Mention, text: str) -> Mention | None:
    """A weekday and the date it is said with ("Friday, October 30") are one day, or a conflict
    when they disagree: the date wins only if it is a day of that name (and is the one "this"
    or "next" meant, when the weekday was qualified); a conflict is asked about, never settled by
    the window."""
    weekday, dated = (first, second) if first.weekday is not None else (second, first)
    if (
        weekday.weekday is None
        or weekday.explicit
        or not dated.explicit
        or dated.weekday is not None
        or not _JOIN.fullmatch(text[first.end : second.start])
    ):
        return None
    day = dated.options[0]
    agrees = day.weekday() == weekday.weekday and (not weekday.qualified or day in weekday.options)
    options = (day,) if agrees else tuple(sorted({day, *weekday.options}))
    return Mention(
        words=" ".join(text[first.start : second.end].split()),
        options=options,
        open=not agrees,
        weekday=weekday.weekday,
        explicit=True,
        marker=first.marker or second.marker,
        start=first.start,
        end=second.end,
    )


def find_mentions(text: str, today: date) -> list[Mention]:
    """Every day the text names, in order, resolved against today, with what is said of each: where
    the workout goes ("to Friday"), where it was or cannot be ("from Monday", "I'm busy Saturday"),
    or a correction ("no wait, Sunday")."""
    found = [
        _marked(mention, text)
        for match in _MENTION.finditer(text)
        if (mention := _mention(match, today)) is not None
    ]
    merged: list[Mention] = []
    for mention in found:
        if merged and (joined := _merged(merged[-1], mention, text)) is not None:
            merged[-1] = joined
        else:
            merged.append(mention)
    for index in range(len(merged) - 1):
        one, two = merged[index], merged[index + 1]
        gap = text[one.end : two.start]
        offered = _OR_GAP.fullmatch(gap) or (
            gap.strip() == "" and two.words.lower().startswith(("or ", "and ", "& "))
        )
        if one.marker == "" and two.marker == "target" and _RANGE_GAP.fullmatch(gap):
            # "Monday to Friday" is a span, not a day to go to
            merged[index + 1] = replace(two, marker="")
        elif one.marker in ("target", "correction") and two.marker == "" and offered:
            # "to Friday or Saturday": both are asked about
            merged[index + 1] = replace(two, marker=one.marker)
        elif one.marker == "source" and two.marker == "" and _SAME_BREATH.fullmatch(gap):
            # "Monday doesn't work but Tuesday does", "not Monday, Wednesday": the day offered instead
            merged[index + 1] = replace(two, marker="target")
    return merged


def names_a_day(text: str) -> bool:
    """Whether the text names a day: a word or date a workout could be moved to."""
    return bool(find_mentions(text, date(2026, 1, 1)))


def _decisive(text: str, mentions: Sequence[Mention], every: Sequence[Mention]) -> bool:
    """Whether a message that names days is a request about the day: a day is marked as where the
    workout goes (or a correction), or the message is only days (every one it names, the ones it
    leaves too) and neutral words, or it has a word for moving. "I ran on Thursday" and "exams are
    next week" name days and ask for nothing."""
    return (
        any(m.marker in ("target", "correction") for m in mentions)
        or _neutral_outside(text, [(m.start, m.end) for m in every], _REQUEST_WORDS)
        or _MOVE_VERB.search(text) is not None
    )


def read_requested_day(texts: Sequence[str], today: date, days_ahead: int) -> DayReading:
    """What the user's words say of the day, from their newest message that asks about one (texts
    are the user's own turns, oldest first). `days_ahead` is the window after today a workout may
    be planned for. A day an older message asked for stands unless a newer one takes it back."""
    last = today + timedelta(days=days_ahead)
    taken_back: set[date] = set()
    for text in reversed(list(texts)):
        found = find_mentions(text, today)
        mentions = [m for m in found if m.marker != "source"]
        sources = [m for m in found if m.marker == "source"]
        decisive = bool(mentions) and _decisive(text, mentions, found)
        if not decisive:
            for source in sources:
                taken_back.update(source.options)
            continue
        corrections = [m for m in mentions if m.marker == "correction"]
        targets = [m for m in mentions if m.marker == "target"]
        chosen = corrections[-1:] or (targets if len(mentions) > 1 and targets else mentions)
        closed = [m for m in chosen if not m.open]
        # a period a more specific day of the same words settles: "next week, Tuesday"
        chosen = [
            m
            for m in chosen
            if not m.open or not any(set(c.options) <= set(m.options) for c in closed)
        ]
        options = tuple(sorted({day for m in chosen for day in m.options}))
        inside = tuple(day for day in options if today <= day <= last)
        words = " / ".join(dict.fromkeys(m.words for m in chosen))
        left = tuple(day for day in inside if day not in taken_back)
        if inside and left != inside:
            # a newer message took some of these days back ("no, not Monday", "not Saturday"): what
            # is left is asked for, and when nothing is, nothing is
            if not left:
                return DayReading("none")
            return DayReading("day" if len(left) == 1 else "ambiguous", left, words, options)
        if any(m.open for m in chosen):
            return DayReading("ambiguous", inside, words, options)
        if not inside:
            return DayReading("outside", (), words, options)
        return DayReading("day" if len(inside) == 1 else "ambiguous", inside, words, options)
    return DayReading("none")


def is_date_only_request(text: str, today: date) -> bool:
    """Whether the message asks only to move a workout to another day: it names a day, and every other
    word is a neutral one for a move (_MOVE_ONLY_WORDS). Positive and conservative: any word it does not
    know means the message may ask for more (a swap, a weight, a harder version), and the proposal tool
    then does not hold the move to the saved plan's exercises, which is how a move was always treated.
    The numbers and the words of a day are not words here."""
    mentions = find_mentions(text, today)
    return bool(mentions) and _neutral_outside(text, [(m.start, m.end) for m in mentions])
