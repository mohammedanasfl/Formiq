"""Formiq's own description of the imported exercises: written by hand for a few, and
generated for the rest from what their records say.

Written by hand (DESCRIPTIONS): the easy cardio activities of the warm-up and cool-down, and
the two hidden duplicates of them.

Their records are the dataset's machine instructions ("select the desired
option from the menu", "estimate the calories burned"): nothing about the easy
pace a warm-up or cool-down needs. The record is kept as it was, in the
exercise's source_record; the description is Formiq's, and replaces its steps
wherever instructions are read (app.models.Exercise.instructions), so the menu
and the calorie estimate are never shown or relayed.

Written by hand too (MAIN_DESCRIPTIONS): three main exercises whose records have no steps at
all, so that the catalog says how to do them. They say how the movement goes, and claim
nothing for it.

Generated (generated_description): every other imported exercise, a visible one, has a
sentence saying what it is, from the facts the catalog already holds of it: its level, its
movement pattern or category, the muscles it works and the equipment it needs. It is a
summary, not a how-to: the steps are the record's own, served as they were. It never says an
exercise does something for the body, and a record with no steps says so.

The doses of the cardio descriptions are suggestions, a judgement of the same kind as the product
guardrails and not a medical rule (docs/warm-up-cool-down.md lists what is
unverified). The hidden duplicates Bicycling_Stationary and Walking_Treadmill have the
same menu and calorie estimate in their records, and a saved plan or a read by id still
shows them, so they have a description too. The other hidden duplicates need none.
"""

from collections.abc import Sequence

# The records whose own steps a description replaces wherever instructions are read
# (app.models.Exercise.instructions): the machine's menu and calorie estimate. A generated
# description never replaces steps.
REPLACES_STEPS = frozenset(
    {"Bicycling", "Bicycling_Stationary", "Jogging_Treadmill", "Recumbent_Bike", "Walking_Treadmill"}
)

DESCRIPTIONS = {
    "Bicycling": (
        "Ride on flat, quiet ground at an easy pace, with light effort and breathing that "
        "still lets you talk. Suggested dose: 3 to 5 minutes as a warm-up, or 3 to 5 minutes "
        "slowing down as a cool-down. Safety: wear a helmet outdoors and keep to safe routes; "
        "stop and rest if you feel dizzy, faint or unusually breathless."
    ),
    "Jogging_Treadmill": (
        "Start with a minute of walking, then jog on a flat treadmill at an easy pace that "
        "still lets you talk, holding the handrails only for balance. Suggested dose: 3 to 5 "
        "minutes as a warm-up. Safety: clip the safety key to your clothing, keep the pace "
        "easy, and slow to a walk if you feel dizzy, faint or unusually breathless."
    ),
    "Recumbent_Bike": (
        "Sit with your back supported and the seat set so the knee is slightly bent at the "
        "bottom of each pedal stroke, then pedal at a light resistance and an easy pace that "
        "still lets you talk. Suggested dose: 3 to 5 minutes as a warm-up, or 3 to 5 minutes "
        "slowing down as a cool-down. Safety: stop and rest if you feel dizzy, faint or "
        "unusually breathless."
    ),
    # hidden duplicates (app.catalog.classification.ACTIVITY_DUPLICATES) of the kept
    # Easy Stationary Cycling and Brisk Walk
    "Bicycling_Stationary": (
        "Pedal a stationary bike at a light resistance and an easy pace that still lets you "
        "talk. Suggested dose: 3 to 5 minutes as a warm-up, or 3 to 5 minutes slowing down as "
        "a cool-down. Safety: stop and rest if you feel dizzy, faint or unusually breathless."
    ),
    "Walking_Treadmill": (
        "Walk on a flat treadmill at an easy pace that still lets you talk, holding the "
        "handrails only for balance. Suggested dose: 3 to 5 minutes as a warm-up, or 3 to 5 "
        "minutes slowing down as a cool-down. Safety: clip the safety key to your clothing, "
        "and slow down or stop if you feel dizzy, faint or unusually breathless."
    ),
}


# Main exercises whose records have no steps: how the movement goes, in Formiq's words.
MAIN_DESCRIPTIONS = {
    "Push_Press": (
        "Stand with a barbell resting on the front of the shoulders, feet about shoulder-width "
        "apart. Dip a little at the knees, then drive up through the legs and press the bar "
        "overhead to straight arms. Lower it back to the shoulders under control. A technical "
        "lift: start with a light bar, and learn it from a qualified coach if it is new to you."
    ),
    "One-Arm_Kettlebell_Swings": (
        "Stand with feet about shoulder-width apart and a kettlebell on the floor in front of "
        "you. Hinge at the hips to take it in one hand, hike it back between the legs, then "
        "drive the hips forward so the bell swings to about chest height. Let it swing back "
        "and hinge again, with a straight back; the hips do the work and the arm only guides "
        "the bell. Switch hands between sets."
    ),
    "Side_Bridge": (
        "Lie on one side with the legs straight and the forearm on the floor under the "
        "shoulder. Lift the hips so the body is in one straight line from head to feet, hold "
        "it, then lower and repeat on the other side."
    ),
}

_KINDS = {
    "SQUAT": "squat exercise",
    "HINGE": "hip-hinge exercise",
    "LUNGE": "single-leg exercise",
    "HORIZONTAL_PUSH": "horizontal pushing exercise",
    "VERTICAL_PUSH": "overhead pushing exercise",
    "HORIZONTAL_PULL": "horizontal pulling exercise",
    "VERTICAL_PULL": "vertical pulling exercise",
    "CARRY": "carrying exercise",
    "ROTATION": "trunk rotation or stability exercise",
    "ISOLATION": "single-joint exercise",
    "MOBILITY": "mobility drill",
    "STRETCH": "stretch",
    "CARDIO": "cardio exercise",
}
# what the record's own category says it is, when that says more than its pattern
_CATEGORY_KINDS = {
    "olympic weightlifting": "Olympic weightlifting exercise",
    "powerlifting": "powerlifting exercise",
    "strongman": "strongman exercise",
    "plyometrics": "plyometric exercise",
    "stretching": "stretch or mobility exercise",
}


def _names(names: Sequence[str]) -> str:
    """"the chest", "the chest and triceps", "the chest, shoulders and triceps"."""
    lower = [name.lower() for name in names]
    if len(lower) <= 1:
        return "".join(lower)
    return f"{', '.join(lower[:-1])} and {lower[-1]}"


def generated_description(
    *,
    difficulty: str,
    pattern: str | None,
    category: str | None,
    primary: Sequence[str],
    secondary: Sequence[str],
    equipment: Sequence[str],
    has_steps: bool,
) -> str:
    """One sentence on what an imported exercise is, from the catalog's own facts of it
    (see the module), then its equipment, and that its record has no steps when it has none.
    Formiq's names: its difficulty (BEGINNER...), pattern and muscle groups."""
    level = difficulty.lower()
    kind = _KINDS.get(pattern) if pattern is not None else None  # a MovementPattern's name
    # a pattern says what the movement is; the categories of the heavy lifts and jumps say more
    if category in ("olympic weightlifting", "powerlifting", "strongman", "plyometrics"):
        kind = _CATEGORY_KINDS[category]
    elif kind is None:
        kind = _CATEGORY_KINDS.get(category or "", "exercise")
    article = "An" if level[0] in "aeiou" else "A"
    sentence = f"{article} {level} {kind}"
    if primary:
        sentence += f" for the {_names(primary)}"
        if secondary:
            sentence += f", with the {_names(secondary)} helping"
    sentence += "."
    if equipment:
        sentence += f" Equipment: {', '.join(name.lower() for name in equipment)}."
    else:
        sentence += " No equipment."
    if not has_steps:
        sentence += " The source gives no steps for it."
    return sentence


def description_of(source_id: str) -> str | None:
    """Formiq's hand-written description of the upstream exercise; None when it has none
    (generated_description is then the description of a visible one)."""
    return DESCRIPTIONS.get(source_id) or MAIN_DESCRIPTIONS.get(source_id)
