"""Exercise names as people say them: a search by name (search_exercises' name).

name_matches() is deterministic and never a near match: every word of the query must start a
word of the exercise's name (a short word, of up to three letters, must be one: "up" is not
the start of "cup" or "upright"; a plural is read as its singular, and case, hyphens and
spacing do not count), or the query as one word ("pushups") must be inside the name written
as one ("push-up"). "hip circle" finds "Hip Circles", "cat cow" finds "Cat-Cow", "pushups" finds
"Push-Up"; "standing hip circles" does not find "Hip Circles", which has no "standing" in it:
the catalog keeps that name under a hidden duplicate's name (app.catalog.classification.
DUPLICATE_OF), and the search resolves it.
"""

import re

from app.tools.equipment import singular

# Words that say nothing about which exercise is meant.
_FILLER = frozenset(
    {"a", "an", "the", "of", "for", "with", "and", "on", "in", "at", "to", "exercise", "drill", "move"}
)
# A word of up to this many letters must be a whole word of the name, not the start of one.
_SHORT_WORD = 3
# A query written as one word is looked for inside the name written as one word only
# when it is long enough not to be part of another word.
_MIN_JOINED_LENGTH = 5

_WORD = re.compile(r"[a-z0-9]+")


def _singular(word: str) -> str:
    """equipment.singular(), and a plural of three letters too: "ups" "up", "abs" "ab"."""
    if len(word) == _SHORT_WORD and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return singular(word)


def name_words(text: str) -> list[str]:
    """The words of a name or a query, lower case and singular, without filler words."""
    words = [_singular(word) for word in _WORD.findall(text.casefold())]
    return [word for word in words if word not in _FILLER]


def name_matches(name: str, query: str) -> bool:
    """Whether the exercise name has every word of the query (see the module)."""
    wanted = name_words(query)
    if not wanted:
        return False
    words = name_words(name)
    joined = "".join(words)
    return all(
        any(word == item if len(item) <= _SHORT_WORD else word.startswith(item) for word in words)
        or (len(item) >= _MIN_JOINED_LENGTH and item in joined)
        for item in wanted
    )
