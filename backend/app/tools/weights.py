"""Whether the user stated a weight, read from their messages: the one thing that lets a
proposal give an exercise a weight, or take a saved one away.

A saved plan may carry a weight on an exercise (workout_plan_exercises.weight_kg), and a
revision keeps it: a proposal that does not say otherwise carries the plan's weight on
(app.tools.formiq_tools). The model never chooses a load, because it cannot know one
(Phase 2.5, after the Phase 2.4 live pass: a proposal could not carry a weight, so every
revision silently dropped the plan's). It may set one only when the user gave it:

- a figure of theirs in kg or lb, within rounding ("20 kg", "12.5kg", "45 lbs": a pound
  figure is converted, and the model may round it), or the plan's own weight moved by a
  figure they gave ("add 5 kg": 15 kg becomes 20 kg). A weight resting on neither is
  refused, so "make it heavier" gets a question, never a number;
- the removal of a weight only when they asked for none ("no weights", "without the
  weight", "remove the weight", "bodyweight").

It is a deterministic reading of known words only, like app.tools.schedule: English only,
digits only ("twenty kilos" is not read), and it cannot tell which exercise a figure is
for. The proposal's card shows the user each weight before and after, and only their
approval saves it. Reading words can miss a phrasing, and then the weight stays as the
plan has it, which is the safe way to be wrong.
"""

import re
from collections.abc import Iterable
from typing import NamedTuple

POUND_IN_KG = 0.45359237
# how far a weight may be from a figure the user gave: exact for kilograms, and for pounds
# the rounding of a conversion
KG_TOLERANCE = 0.01
LB_TOLERANCE = 0.5

_KG = r"kgs?|kilos?|kilograms?"
_LB = r"lbs?|pounds?"
_STATED = re.compile(
    rf"(?<![\d.,])(?P<number>\d{{1,3}}(?:[.,]\d{{1,2}})?)\s*-?\s*(?:(?P<kg>{_KG})|(?P<lb>{_LB}))\b",
    re.IGNORECASE,
)
_NO_WEIGHT = re.compile(
    r"\b(?:no|without|zero|remove|ditch|skip|take\s+off)\s+"
    r"(?:the\s+|any\s+|all\s+|that\s+|this\s+|extra\s+)*(?:weights?|load|loads)\b"
    r"|\bunweighted\b|\bweightless\b"
    r"|(?<![\d.,])0\s*(?:kgs?|kilos?|kilograms?)\b",
    re.IGNORECASE,
)
# "make it bodyweight", but not "my body weight is 70 kg": the user's own weight is no
# request for an exercise without one
_BODYWEIGHT = re.compile(r"\bbody[- ]?weight\b(?!\s+(?:is|was|of|are)\b)", re.IGNORECASE)
_THEIR_OWN = re.compile(r"\b(?:my|our|your|current|goal|target|starting)\s+$", re.IGNORECASE)


class Stated(NamedTuple):
    """A weight the user gave, in kilograms, and how far a weight may be from it."""

    kg: float
    tolerance: float


def stated_weights(texts: Iterable[str]) -> list[Stated]:
    """The weights the user gave in these messages, in kilograms."""
    found = []
    for text in texts:
        for match in _STATED.finditer(text):
            number = float(match["number"].replace(",", "."))
            if number <= 0:
                continue
            if match["lb"]:
                found.append(Stated(number * POUND_IN_KG, LB_TOLERANCE))
            else:
                found.append(Stated(number, KG_TOLERANCE))
    return found


def asks_for_no_weight(texts: Iterable[str]) -> bool:
    """Whether the user asked for no weight, in any of these messages."""
    for text in texts:
        if _NO_WEIGHT.search(text):
            return True
        for match in _BODYWEIGHT.finditer(text):
            if not _THEIR_OWN.search(text[max(0, match.start() - 10) : match.start()]):
                return True
    return False


def same_weight(first: float | None, second: float | None) -> bool:
    """Whether two saved weights are the same (none is the same as none)."""
    if first is None or second is None:
        return first is second
    return abs(float(first) - float(second)) < KG_TOLERANCE


def rests_on_the_user(weight: float, saved: float | None, stated: Iterable[Stated]) -> bool:
    """Whether a weight the model gives is the user's: a figure they gave, or the
    plan's own weight (saved) moved by a figure they gave."""
    for given in stated:
        if abs(weight - given.kg) <= given.tolerance:
            return True
        if saved is not None and abs(abs(weight - float(saved)) - given.kg) <= given.tolerance:
            return True
    return False
