"""The muscles the user said they want to train, read from their message.

A warm-up and cool-down search ranks the activities that suit the workout first
(app.tools.formiq_tools.most_relevant). It used to learn the workout only from the main
exercises its searches found, so a model that searched the main workout without naming a
muscle ("back and biceps day": any ten exercises) left every activity fitting equally, and the
biceps drill never came first (live QA, 2026-10-19). What the user wrote says it directly.

muscles_named() is a deterministic reading of known words only, like app.tools.equipment: the
catalog's muscle names, common names for them ("pecs", "abs", "quads", "legs"), and a few for
a part of the body or a kind of day ("arms", "upper body", "push day"). It only orders a
search's results, and never decides what a proposal may hold, so it leaves out what it cannot
read with confidence:

- a muscle named after a word that says it is not to be worked ("no legs", "without
  shoulders", "avoid my back"), or next to one that says it hurts or was worked already
  ("my shoulder hurts", "lower back pain", "legs yesterday"), is left out, and so is it from
  anything else that names it ("legs, without hamstrings"), so a muscle the user protects
  never ranks first. A "no" reaches the muscles of its list ("no legs or back"), not
  past a comma or a "but" ("chest and triceps, no legs");
- "back" is the upper back and the lats ("lower back" is the lower back, which the catalog counts
  with the core), and is nothing in "back to the gym";
- a word inside another word ("armchair") or an exercise's name ("pull-up bar") is nothing,
  and "hip" is not read at all: it is in the names of exercises far more often than it names
  the muscles the user trains ("put Standing Hip Circles in my warm-up").

"full body" names no muscle in particular, so it names none.
"""

import re
from collections.abc import Collection, Mapping

# words, and commas, which end what a negation reaches
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|,")
_BOUNDARY = re.compile(r"[.!?;:\n]")

# What a word or phrase of the user's message names, as catalog muscle group names. A
# phrase is its words in order, singular; a longer phrase is read before a shorter one that
# it contains ("lower back" before "back").
_ARMS = ("Biceps", "Triceps", "Forearms")
_LEGS = ("Quadriceps", "Hamstrings", "Glutes", "Calves")
_SHOULDERS = ("Shoulders", "Front Deltoid", "Rear Deltoid")
_BACK = ("Upper Back", "Lats")
MUSCLE_WORDS: Mapping[str, tuple[str, ...]] = {
    "chest": ("Chest",),
    "pec": ("Chest",),
    "pectoral": ("Chest",),
    "upper back": ("Upper Back",),
    "lower back": ("Lower Back",),
    "back": _BACK,
    "lat": ("Lats",),
    "shoulder": _SHOULDERS,
    "delt": _SHOULDERS,
    "deltoid": _SHOULDERS,
    "rear delt": ("Rear Deltoid",),
    "front delt": ("Front Deltoid",),
    "bicep": ("Biceps",),
    "biceps": ("Biceps",),
    "tricep": ("Triceps",),
    "triceps": ("Triceps",),
    "forearm": ("Forearms",),
    "arm": _ARMS,
    "core": ("Core", "Obliques"),
    "ab": ("Core",),
    "abs": ("Core",),
    "abdominal": ("Core",),
    "oblique": ("Obliques",),
    "glute": ("Glutes",),
    "quad": ("Quadriceps",),
    "quadricep": ("Quadriceps",),
    "quadriceps": ("Quadriceps",),
    "hamstring": ("Hamstrings",),
    "calf": ("Calves",),
    "calve": ("Calves",),
    "thigh": ("Quadriceps", "Hamstrings"),
    "adductor": ("Adductors",),
    "abductor": ("Abductors",),
    "leg": _LEGS,
    "neck": ("Neck",),
    "upper body": ("Chest", "Upper Back", "Lats", *_SHOULDERS, "Biceps", "Triceps"),
    "lower body": (*_LEGS, "Adductors", "Abductors"),
}
# "push" and "pull" name muscles only as a kind of day ("push day", "pull workout"): "pull"
# is also part of "pull-up bar".
KINDS_OF_DAY: Mapping[str, tuple[str, ...]] = {
    "push": ("Chest", "Shoulders", "Front Deltoid", "Triceps"),
    "pull": ("Upper Back", "Lats", "Rear Deltoid", "Biceps"),
}
_DAY_WORDS = frozenset({"day", "days", "workout", "workouts", "session", "sessions", "routine"})

# Words before a muscle that say it is not to be worked or is a problem.
_BEFORE = frozenset(
    {
        "no", "not", "without", "avoid", "avoiding", "skip", "skipping", "except", "excluding",
        "never", "don't", "dont", "can't", "cant", "cannot", "won't", "wont", "bad", "sore",
        "injured", "strained", "tweaked", "torn", "recovering", "yesterday", "already", "hurt",
        "hurting",
    }
)  # fmt: skip
# Words after a muscle that say it hurts or was worked already.
_AFTER = frozenset(
    {
        "hurt", "hurts", "hurting", "pain", "painful", "sore", "injury", "injured", "strain",
        "strained", "bothering", "bothers", "aching", "aches", "yesterday", "already",
        "tweaked", "torn",
    }
)  # fmt: skip
_WINDOW = 3
# Words, and the comma, that end what a word before a muscle reaches.
_ENDS_REACH = frozenset({",", "but", "then", "though", "however", "so", "while"})
# "back" is nothing beside these: "back to the gym", "I'm back", "come back".
_NOT_A_BACK_BEFORE = frozenset(
    {"come", "coming", "came", "get", "getting", "got", "go", "going", "went", "am", "i'm",
     "im", "is", "are", "was", "were", "bring", "take", "took", "right"}
)  # fmt: skip
_NOT_A_BACK_AFTER = frozenset({"to", "at", "from", "in", "on", "after", "here", "soon", "again"})


def _singular(word: str) -> str:
    """A plural as its singular for the words of MUSCLE_WORDS ("quads" "quad", "legs"
    "leg", "calves" "calve"); "biceps", "triceps" and "abs" are their own."""
    if word in MUSCLE_WORDS or len(word) <= 3:
        return word
    if word.endswith("ves"):
        return word[:-3] + "ve"
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def muscles_named(text: str, known: Collection[str]) -> frozenset[str]:
    """The catalog muscle groups (names in known) that the text says the user wants to
    train: see the module."""
    wanted: set[str] = set()
    protected: set[str] = set()
    for sentence in _BOUNDARY.split(text.casefold()):
        words = [_singular(word) for word in _TOKEN.findall(sentence.replace("-", " "))]
        index = 0
        while index < len(words):
            found = _named_at(words, index)
            if found is None:
                index += 1
                continue
            names, length = found
            (protected if _cued(words, index, index + length) else wanted).update(
                name for name in names if name in known
            )
            index += length
    return frozenset(wanted - protected)


def _named_at(words: list[str], index: int) -> tuple[tuple[str, ...], int] | None:
    """The muscles the words name at index, and how many words name them (the longest
    phrase), or None."""
    word = words[index]
    following = words[index + 1] if index + 1 < len(words) else ""
    if word in KINDS_OF_DAY:
        return (KINDS_OF_DAY[word], 2) if following in _DAY_WORDS else None
    if (phrase := f"{word} {following}") in MUSCLE_WORDS:
        return MUSCLE_WORDS[phrase], 2
    if word not in MUSCLE_WORDS:
        return None
    if word == "back" and (
        following in _NOT_A_BACK_AFTER or (index and words[index - 1] in _NOT_A_BACK_BEFORE)
    ):
        return None
    return MUSCLE_WORDS[word], 1


def _cued(words: list[str], start: int, end: int) -> bool:
    """Whether the muscle named by words[start:end] is not to be worked or is a problem:
    a word of _BEFORE reaching it, or one of _AFTER next to it."""
    for word in reversed(words[max(0, start - _WINDOW) : start]):
        if word in _ENDS_REACH:
            break
        if word in _BEFORE:
            return True
    for word in words[end : end + _WINDOW]:
        if word in _ENDS_REACH:
            break
        if word in _AFTER:
            return True
    return False
