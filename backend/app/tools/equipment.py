"""Equipment as people name it, and as Formiq's catalog names it.

Two deterministic readings, neither of them a search for a substring:

- read_equipment_name() reads one name the model gives a tool ("dumbbells", "a
  pair of dumbbells", "cable machine", "pullup bar", "nothing") as the catalog
  equipment it means: its key (equipment_key()), NO_EQUIPMENT for none at
  all, or no match. A name that negates itself ("no dumbbells") or doubts
  itself ("maybe a kettlebell") says so, so it is never read as equipment the
  user has.
- stated_equipment() reads what the user wrote in the conversation about the
  equipment they have and lack: "I only have dumbbells and resistance bands",
  "I don't have any equipment", "no bench, just bands". A piece counts as
  theirs only when they said so ("I have", "my", "with", "only", a plain list
  of equipment answering a question): mentioning it ("what is a kettlebell
  swing?", "should I buy a kettlebell?") is not having it.

Both match whole words and known phrases only: a name is the catalog's own
(without case, hyphens or extra spaces), its plural, or an alias listed here;
anything else is no equipment, never a near match.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

# Training with no equipment at all, as read_equipment_name() returns it.
NO_EQUIPMENT = "no equipment"

# What a name for no equipment may say, as equipment_key() has it ("body only"
# is free-exercise-db's own name for it).
_NO_EQUIPMENT_NAMES = frozenset(
    {
        "body weight",
        "bodyweight",
        "body only",
        "no equipment",
        "none",
        "nothing",
        "nothing available",
        "without equipment",
        "no equipment at all",
        "equipment free",
        "bodyweight only",
        "body weight only",
        "only bodyweight",
        "only body weight",
        "just bodyweight",
        "just body weight",
        "own body weight",
        "my body weight",
        "my own body weight",
        "no gear",
    }
)

# Other names for Formiq's catalog equipment, by the key of the catalog's name.
# Each is written singular: a plural is read as its singular.
EQUIPMENT_ALIASES: Mapping[str, tuple[str, ...]] = {
    "barbell": ("bar bell", "olympic bar", "olympic barbell", "straight bar"),
    "dumbbell": ("dumb bell", "db", "adjustable dumbbell"),
    "kettlebell": ("kettle bell", "kb"),
    "bench": ("weight bench", "flat bench", "incline bench", "adjustable bench", "workout bench"),
    "squat rack": ("power rack", "squat cage", "power cage", "rack"),
    "cable machine": (
        "cable",
        "cable station",
        "cable stack",
        "cable tower",
        "cable crossover",
        "pulley",
        "pulley machine",
    ),
    "smith machine": ("smith",),
    "leg press machine": ("leg press",),
    "pull up bar": (
        "pullup bar",
        "chin up bar",
        "chinup bar",
        "doorway bar",
        "doorway pull up bar",
        "doorway pullup bar",
    ),
    "resistance band": (
        "band",
        "exercise band",
        "loop band",
        "mini band",
        "elastic band",
        "resistance tube",
        "resistance loop",
        "therapy band",
        "workout band",
    ),
    "stationary bike": (
        "exercise bike", "spin bike", "indoor bike", "bike", "cycle", "spinning bike",
    ),
    "rowing machine": ("rower", "erg", "rowing erg", "indoor rower"),
    "machine": ("weight machine", "gym machine", "resistance machine"),
    "medicine ball": ("med ball",),
    "exercise ball": ("stability ball", "swiss ball", "yoga ball", "physio ball", "gym ball"),
    "foam roller": ("foam roll",),
    "ez curl bar": ("ez bar", "e z bar", "e z curl bar", "curl bar"),
    "other equipment": ("other",),
}

# Words before a piece of equipment that do not change which piece it is: "a
# pair of dumbbells", "two heavy kettlebells", "my adjustable bench".
_LEADING_WORDS = frozenset(
    {
        "a", "an", "the", "some", "my", "our", "one", "two", "three", "four", "1", "2", "3",
        "4", "pair", "pairs", "set", "sets", "of", "couple", "few", "light", "heavy",
        "small", "big", "large", "long", "short", "fixed", "adjustable", "loop", "mini",
        "basic", "old", "new", "home", "only", "just",
    }
)  # fmt: skip

# Words that make a name say the user has no such piece, or may not have it.
_NEGATING_WORDS = frozenset(
    {
        "no", "not", "without", "lacking", "lack", "lacks", "never", "zero", "missing",
        "unavailable", "dont", "don't", "cannot", "can't", "cant", "excluding", "except",
    }
)  # fmt: skip
_DOUBTING_WORDS = frozenset(
    {
        "maybe", "perhaps", "possibly", "if", "might", "may", "optional", "optionally",
        "probably", "hopefully", "sometimes",
    }
)  # fmt: skip


def equipment_key(name: str) -> str:
    """An equipment name as it is matched: without case, and with hyphens,
    underscores and runs of spaces as one space ("Pull-up Bar" is "pull up
    bar")."""
    return " ".join(name.replace("-", " ").replace("_", " ").casefold().split())


def singular(word: str) -> str:
    """A plural noun as its singular, by the regular English endings only:
    "benches" "bench", "dumbbells" "dumbbell"; a word ending in "ss" or a
    short one is left as it is."""
    if len(word) <= 3 or word.endswith("ss"):
        return word
    if word.endswith(("ches", "shes", "xes", "zes", "sses")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("us", "is")):
        return word[:-1]
    return word


def _alias_index(catalog_keys: Iterable[str]) -> dict[str, str]:
    """Each name a piece of the catalog may be called, singular, to its key."""
    index: dict[str, str] = {}
    for key in catalog_keys:
        index.setdefault(key, key)
        index.setdefault(_singular_phrase(key), key)
        for alias in EQUIPMENT_ALIASES.get(key, ()):
            index.setdefault(_singular_phrase(alias), key)
    return index


def _singular_phrase(phrase: str) -> str:
    words = phrase.split()
    return " ".join([*words[:-1], singular(words[-1])]) if words else phrase


@dataclass(frozen=True)
class EquipmentName:
    """How one name given to a tool reads."""

    # the catalog key it names, NO_EQUIPMENT, or None when it names neither
    key: str | None
    # "no dumbbells", "without a bench": the user lacks it
    negated: bool = False
    # "maybe dumbbells", "dumbbells if available": the user may not have it
    doubtful: bool = False


def read_equipment_name(name: str, catalog_keys: Iterable[str]) -> EquipmentName:
    """The catalog equipment one name means, from the catalog's keys: the
    catalog's own name, its plural, or an alias, after the words that do not
    change it ("a pair of"); NO_EQUIPMENT for a name for none at all. Never a
    partial match: "dumbbell bench" is neither a dumbbell nor a bench."""
    key = equipment_key(name)
    if key in _NO_EQUIPMENT_NAMES:
        return EquipmentName(NO_EQUIPMENT)
    words = key.split()
    negated = doubtful = False
    # "no access to", "do not have", "if available": words around the name
    while words and (words[0] in _NEGATING_WORDS or words[0] in _DOUBTING_WORDS or words[0] in {
        "do", "have", "has", "access", "to", "any", "use", "owned",
    }):
        negated |= words[0] in _NEGATING_WORDS
        doubtful |= words[0] in _DOUBTING_WORDS
        words = words[1:]
    while words and words[-1] in {"available", "if", "possible", "maybe", "needed", "optional"}:
        doubtful |= words[-1] in {"if", "possible", "maybe", "optional"}
        words = words[:-1]
    if len(words) >= 2 and words[-2] in {"if", "when"}:
        doubtful, words = True, words[:-2]
    rest = " ".join(words)
    if rest in {"equipment", "gear"}:
        # "without equipment" is none at all; "equipment" alone names no piece
        return EquipmentName(NO_EQUIPMENT if negated else None, doubtful=doubtful)
    if rest in _NO_EQUIPMENT_NAMES:
        return EquipmentName(None if negated else NO_EQUIPMENT, doubtful=doubtful)
    while words and words[0] in _LEADING_WORDS:
        words = words[1:]
    if " ".join(words) in _NO_EQUIPMENT_NAMES:
        # "just my body weight"
        return EquipmentName(None if negated else NO_EQUIPMENT, doubtful=doubtful)
    index = _alias_index(catalog_keys)
    found = index.get(_singular_phrase(" ".join(words))) if words else None
    return EquipmentName(found, negated=negated, doubtful=doubtful)


# --- what the user said ---

# How a piece is mentioned in what the user wrote.
OWNED, LACKED, MENTIONED = "owned", "lacked", "mentioned"
# What equipment in general is said to be: none ("no equipment"), or nothing but
# the pieces the user has ("I only have dumbbells", "just bands").
NONE_AT_ALL, NOTHING_ELSE = "none at all", "nothing else"

# Single words that name a piece too loosely to read in free text: "none", "other",
# "smith" (a name), "rack", "cable" and "cycle" mean other things too.
_TEXT_EXCLUDED_ALIASES = frozenset(
    {
        "other", "other equipment", "smith", "rack", "cable", "cycle", "db", "kb", "erg",
        "machine", "pulley",
    }
)  # fmt: skip
# A piece named just before these is part of an exercise's name, not equipment:
# "dumbbell rows", "kettlebell swing", "bench press", "band pull-apart".
_EXERCISE_WORDS = frozenset(
    {
        "press", "presses", "row", "rows", "curl", "curls", "swing", "swings", "squat",
        "squats", "lunge", "lunges", "fly", "flys", "flies", "flyes", "raise", "raises",
        "pullover", "pullovers", "extension", "extensions", "deadlift", "deadlifts",
        "snatch", "snatches", "clean", "cleans", "thruster", "thrusters", "crunch",
        "crunches", "twist", "twists", "slam", "slams", "throw", "throws", "dip", "dips",
        "pull", "pulls", "pulldown", "pulldowns", "kickback", "kickbacks", "shrug", "shrugs",
        "walk", "walks", "carry", "carries", "step", "steps", "hop", "hops", "exercise",
        "exercises", "movement", "movements", "variation", "variations", "version",
        "versions", "technique", "form", "jump", "jumps", "rollout", "rollouts", "work",
    }
)  # fmt: skip
# After a piece: a workout made with it, which the user is asking to train with.
_WORKOUT_WORDS = frozenset(
    {"workout", "workouts", "routine", "routines", "session", "sessions", "circuit",
     "circuits", "program", "programme", "plan", "training", "only"}
)  # fmt: skip
# Words that end a clause: what follows says something else.
_CLAUSE_WORDS = frozenset({"but", "however", "though", "although", "whereas", "while"})
# Words that start an exception: "no equipment except dumbbells".
_EXCEPTION_WORDS = frozenset({"except", "besides", "apart", "aside", "excluding"})
# Words between a negation and the pieces it covers: "I don't have any
# dumbbells or a bench", "no access to a cable machine".
_NEGATION_FILLERS = frozenset(
    {
        "have", "has", "got", "own", "use", "any", "a", "an", "the", "my", "of", "pair",
        "pairs", "set", "access", "to", "even", "real", "proper", "heavy", "light",
        "adjustable", "or", "and", "nor", "either", "some", "at", "home", "here", "right",
        "now", "currently", "really", "enough", "do", "does", ",", "more", "much", "many",
        "single", "other", "else", "additional", "extra", "spare",
    }
)  # fmt: skip
# Words in a plain list of equipment besides the pieces: "dumbbells and a bench".
_LIST_WORDS = _NEGATION_FILLERS | {"i", "we", "just", "only"}
_NEGATIONS = frozenset(
    {
        "no", "not", "don't", "dont", "doesn't", "doesnt", "didn't", "never", "without",
        "lack", "lacking", "haven't", "havent", "hasn't", "can't", "cant", "cannot",
        "nor", "neither", "zero", "unable",
    }
)  # fmt: skip
# Words that make what follows a possibility, not what the user has.
_HYPOTHETICAL = frozenset(
    {
        "if", "maybe", "might", "whether", "perhaps", "possibly", "planning", "thinking",
        "considering", "buy", "buying", "purchase", "purchasing", "wish", "hope", "should",
        "suppose", "imagine", "pretend",
        # what the user had, not what they have
        "used", "had", "sold", "lost", "broke", "broken", "returned", "gave",
    }
)  # fmt: skip
# Words that, with the user as subject, say they have a piece.
_POSSESSION_VERBS = frozenset(
    {"have", "has", "got", "own", "use", "keep", "bring", "brought", "bought", "purchased"}
)
_FIRST_PERSON = frozenset({"i", "we", "i've", "ive", "we've", "i'll", "i'm", "im"})
# Words that say a piece is the user's, or is what they will train with,
# without a verb: "my dumbbells", "with dumbbells", "only bands".
_OWNERSHIP_WORDS = frozenset({"my", "our", "with", "using", "only", "just", "plus"})
# Words after a piece that say the user has it: "dumbbells are available".
_AFTER_OWNERSHIP = frozenset({"available", "home", "garage", "basement", "handy"})
# Words for equipment in general: "I don't have any equipment".
_GENERAL_EQUIPMENT = frozenset({"equipment", "gear", "kit"})
# Saying the user trains with their body weight only.
_BODYWEIGHT_ONLY = (
    ("bodyweight", "only"),
    ("body", "weight", "only"),
    ("only", "bodyweight"),
    ("only", "body", "weight"),
    ("just", "bodyweight"),
    ("just", "body", "weight"),
    ("just", "my", "body", "weight"),
    ("only", "my", "body", "weight"),
    ("equipment", "free"),
)
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|[.!?;:\n,]")
_BOUNDARY = frozenset({".", "!", "?", ";", ":", "\n"})


@dataclass(frozen=True)
class StatedEquipment:
    """What the user said about their equipment, by catalog key: what they
    have, what they lack, and whether they said they have nothing (but what
    they have)."""

    has: frozenset[str] = frozenset()
    lacks: frozenset[str] = frozenset()
    # they said they have no equipment (at all, or except what they have)
    has_nothing_else: bool = False
    # every piece they mentioned, had or not
    mentioned: frozenset[str] = field(default=frozenset(), compare=False)

    def lacked(self, catalog_keys: Iterable[str]) -> set[str]:
        """The catalog's pieces the user said they lack."""
        keys = set(catalog_keys)
        if self.has_nothing_else:
            return keys - self.has
        return keys & self.lacks

    @property
    def said(self) -> bool:
        """Whether the user said anything about what they have or lack."""
        return bool(self.has or self.lacks or self.has_nothing_else)


def stated_equipment(texts: Sequence[str], catalog_keys: Iterable[str]) -> StatedEquipment:
    """What the user said about their equipment in these texts, oldest first:
    a later statement about a piece replaces an earlier one."""
    index = {
        alias: key
        for alias, key in _alias_index(catalog_keys).items()
        if alias not in _TEXT_EXCLUDED_ALIASES
    }
    phrases = sorted({tuple(alias.split()) for alias in index}, key=len, reverse=True)
    has: set[str] = set()
    lacks: set[str] = set()
    mentioned: set[str] = set()
    nothing_else = False
    for text in texts:
        for clause, question, exception in _clauses(text):
            for key, stance in _mentions(clause, question, exception, index, phrases):
                if key is None:
                    # equipment in general: having none, nothing else, or some
                    nothing_else = stance in (NONE_AT_ALL, NOTHING_ELSE)
                    if stance == NONE_AT_ALL and not {"other", "else", "more"} & set(clause):
                        # "no equipment" replaces what they said they have;
                        # "no other equipment" keeps it
                        has.clear()
                    continue
                mentioned.add(key)
                if stance == OWNED:
                    has.add(key)
                    lacks.discard(key)
                elif stance == LACKED:
                    lacks.add(key)
                    has.discard(key)
    return StatedEquipment(frozenset(has), frozenset(lacks), nothing_else, frozenset(mentioned))


def _clauses(text: str) -> list[tuple[list[str], bool, bool]]:
    """The text's clauses, as words: each with whether it is a question, and
    whether it starts an exception ("except dumbbells")."""
    tokens = _TOKEN.findall(text.casefold().replace("’", "'").replace("-", " ").replace("_", " "))
    clauses: list[tuple[list[str], bool, bool]] = []
    current: list[str] = []
    exception = False
    for token in [*tokens, "."]:
        if token in _BOUNDARY or token in _CLAUSE_WORDS or token in _EXCEPTION_WORDS:
            if current:
                clauses.append((current, token == "?", exception))
            current = []
            exception = token in _EXCEPTION_WORDS
            continue
        current.append(token)
    return clauses


def _mentions(
    words: list[str],
    question: bool,
    exception: bool,
    index: Mapping[str, str],
    phrases: Sequence[tuple[str, ...]],
) -> list[tuple[str | None, str]]:
    """Each piece the clause mentions (None for equipment in general, or for
    the user's body weight only), and how: owned, lacked or only mentioned."""
    found: list[tuple[int, int, str | None]] = []
    position = 0
    while position < len(words):
        match = _phrase_at(words, position, phrases, index)
        if match is not None:
            length, key = match
            after = words[position + length] if position + length < len(words) else None
            if after not in _EXERCISE_WORDS:
                found.append((position, length, key))
            position += length
            continue
        bodyweight = next(
            (
                len(phrase)
                for phrase in _BODYWEIGHT_ONLY
                if tuple(words[position : position + len(phrase)]) == phrase
            ),
            None,
        )
        if bodyweight is not None:
            # their body weight only: no equipment, said as having it
            found.append((position, bodyweight, "*bodyweight"))
            position += bodyweight
            continue
        if words[position] in _GENERAL_EQUIPMENT:
            found.append((position, 1, None))
        position += 1

    mention_words = {
        index_: True for start, length, _ in found for index_ in range(start, start + length)
    }
    only_equipment = all(
        word in _LIST_WORDS or index_ in mention_words for index_, word in enumerate(words)
    )
    results: list[tuple[str | None, str]] = []
    for start, length, key in found:
        stance = _stance(words, start, length, question, exception, mention_words, only_equipment)
        if key == "*bodyweight":
            # "bodyweight only" is no equipment, unless it is negated or a possibility
            if stance != LACKED and not any(word in _HYPOTHETICAL for word in words[:start]):
                results.append((None, NONE_AT_ALL))
            continue
        if key is None:
            # equipment in general: "no equipment" is having none of it
            if stance == LACKED:
                results.append((None, NONE_AT_ALL))
            elif stance == OWNED:
                results.append((None, OWNED))
            continue
        results.append((key, stance))
        if stance == OWNED and (
            {"only", "just"} & set(words[:start])
            or _says_it_is_all(words[start + length:])
            or _all_i_have(words[:start])
        ):
            # "I only have dumbbells", "all I have is dumbbells": and nothing else
            results.append((None, NOTHING_ELSE))
    return results


def _phrase_at(
    words: list[str],
    position: int,
    phrases: Sequence[tuple[str, ...]],
    index: Mapping[str, str],
) -> tuple[int, str] | None:
    """The longest known name at this position (its last word may be
    plural), as its length and catalog key."""
    for phrase in phrases:
        end = position + len(phrase)
        if end > len(words):
            continue
        candidate = (*words[position:end - 1], singular(words[end - 1]))
        if candidate == phrase:
            return len(phrase), index[" ".join(phrase)]
    return None


def _stance(
    words: list[str],
    start: int,
    length: int,
    question: bool,
    exception: bool,
    mention_words: Mapping[int, bool],
    only_equipment: bool,
) -> str:
    before = words[:start]
    after = words[start + length:]
    # a negation covering it: only other pieces and filler words between them;
    # a new subject ("I don't have a bench, I have bands") starts another statement
    for position in range(len(before) - 1, -1, -1):
        word = before[position]
        if word in _NEGATIONS:
            return LACKED
        if not (word in _NEGATION_FILLERS or mention_words.get(position)):
            break
    if any(word in _HYPOTHETICAL for word in before):
        return MENTIONED
    # "I have", "we've got"; in a question ("can I use a kettlebell?") it asks
    possession = not question and any(
        word in _POSSESSION_VERBS and any(earlier in _FIRST_PERSON for earlier in before[:index])
        for index, word in enumerate(before)
    )
    owned = (
        exception
        or possession
        or any(word in _OWNERSHIP_WORDS for word in before)
        or bool(after) and after[0] in _WORKOUT_WORDS
        or any(word in _AFTER_OWNERSHIP for word in after)
        or _says_it_is_all(after)
    )
    if owned:
        return OWNED
    # a plain list of equipment, answering what they have; never a question
    if only_equipment and not question:
        return OWNED
    return MENTIONED


# "all I have is", "all I've got are", "all that we own is": what follows is all they have.
# ("not all I have is ..." says the opposite.)
_ALL_I_HAVE = re.compile(
    r"(?<!not )(?<!n't )\ball (?:that )?(?:i|we)(?:'ve)?(?: (?:have|has|got|own|use))+\b"
)


def _all_i_have(before: list[str]) -> bool:
    """ "all I have is a pair of dumbbells": the pieces named after it are all
    the user has. "all" alone says nothing of the sort ("I have all kinds of
    bands"): it must be the user's own having that is all."""
    return _ALL_I_HAVE.search(" ".join(before)) is not None


def _says_it_is_all(after: list[str]) -> bool:
    """ "dumbbells are all I have", "a bench is what I've got", and a list that
    ends so: "the dumbbells and the band are all I have"."""
    text = " ".join(after)
    return bool(re.search(r"\b(?:is|are) (?:all|what) (?:i|we)(?:'ve)? (?:have|has|got|own)", text))
