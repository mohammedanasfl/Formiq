"""Formiq's movement pattern for an imported record that no list names: a judgement made
by rules from what the record says (its name, force, mechanic, primary muscles and
category), the same way for every record, so it can be read, tested and corrected.

It fills the field the coach's search by movement pattern needs: until now only Formiq's own
exercises and the warm-up and cool-down activities had one, so a search for SQUAT, HINGE or
LUNGE found a few of the catalog's squats and none of the rest. A pattern is Formiq's
coarse grouping, not a biomechanical claim:

- the squat, hinge and lunge are the lower-body lifts (knee-dominant, hip-dominant and
  single-leg or alternating-leg), the push and pull are horizontal or vertical for the upper
  body, and everything with one joint doing the work (curls, raises, flyes, extensions,
  crunches, calf work) is an ISOLATION exercise;
- a carry is carried, a rotation is a twist, a chop, a halo or a hold that resists one
  (Formiq's own Bird Dog and Pallof Press are ROTATION), and the Olympic lifts are hinges
  (cleans and snatches) or vertical pushes (jerks and push presses).

Each rule is a word of the name, read first, or a fact of the record, read after. A record
that no rule fits is left without a pattern rather than given a wrong one (a medicine-ball
slam, a sprint drill, a throw from the floor: a dozen in all), and EXCEPTIONS names the few the
rules get wrong. tests/unit/test_movement_patterns.py pins the rules, and
lists what is classified and what is not.
"""

import re
from collections.abc import Sequence
from typing import Any

from app.schemas.exercise import MovementPattern, WorkoutSection

P = MovementPattern

# Records the rules would misread, by record id, with the pattern a person gives them (None:
# no pattern fits, which is the honest answer for a drill that is none of these).
EXCEPTIONS: dict[str, MovementPattern | None] = {
    # a word of the name says another pattern ("chin", "plank", "drag", "swing")
    "Lying_Close-Grip_Barbell_Triceps_Press_To_Chin": P.ISOLATION,
    "Gorilla_Chin_Crunch": P.ISOLATION,
    "Push_Up_to_Side_Plank": P.HORIZONTAL_PUSH,
    "Forward_Drag_with_Press": None,
    "Sledgehammer_Swings": P.ROTATION,
    "Flutter_Kicks": P.ISOLATION,
    "Incline_Dumbbell_Flyes_-_With_A_Twist": P.ISOLATION,
    "Hip_Flexion_with_Band": P.ISOLATION,
    # lifted from the ground to a platform, or to the shoulder: hip-dominant
    "Tire_Flip": P.HINGE,
    "Sandbag_Load": P.HINGE,
    # twists that lift or flip a load across the body
    "Standing_Cable_Lift": P.ROTATION,
    "Spell_Caster": P.ROTATION,
    "Cable_Judo_Flip": P.ROTATION,
}


def _rule(words: str, pattern: MovementPattern) -> tuple[re.Pattern[str], MovementPattern]:
    """The words, each a whole word (or its plural), as a rule for a pattern."""
    return re.compile(rf"\b(?:{words})(?:s|es)?\b", re.IGNORECASE), pattern


# Words of a name, in the order they are tried: the first rule that fits decides.
_NAME_RULES = (
    # carried loads, and the strongman wheel that is walked
    _rule(r"farmer'?|yoke|carry|carries|suitcase|conan'?s wheel", P.CARRY),
    # the shoulder's own turning is one joint
    _rule(r"(?:internal|external) rotation", P.ISOLATION),
    # holds and twists: the core resisting or making a turn
    _rule(
        r"twist|woodchop|wood chop|chop|windmill|pallof|rotational|bird dog|superman|dead bug|"
        r"halo|landmine 180'?|side bridge|plank|torso rotation",
        P.ROTATION,
    ),
    # hip-dominant lifts that a later word would take for something else
    _rule(r"glute-ham|glute ham|back extension|hyperextension|reverse hyper", P.HINGE),
    # a single leg: the lunge, before the one-joint words ("step-up with knee raise")
    _rule(
        r"lunge|split squat|split jump|scissors jump|bulgarian|step-up|step up|stepup|pistol|stride|"
        r"(?:one|single)[- ]leg\b[\w ]*squat",
        P.LUNGE,
    ),
    # one joint: flyes, raises, curls, extensions, squeezes
    _rule(r"fl(?:y|ye|yes)|cross over|crossover|raise|curl|extension|squeeze|kickback", P.ISOLATION),
    # pulling up or down: vertical
    _rule(
        r"pull-up|pullup|pull up|chin|chin-up|chinup|chin up|pulldown|pull-down|muscle-up|"
        r"muscle up|rope climb|climb|upright[\w -]*row|high pull|pullover",
        P.VERTICAL_PULL,
    ),
    # pulling toward the body: horizontal
    _rule(r"row|face pull|pull-apart|pull apart", P.HORIZONTAL_PULL),
    # one leg after the other: the sled's drive, and the mountain climber
    _rule(r"sled|drag|mountain climber", P.LUNGE),
    # knee-dominant lifts
    _rule(r"squat|leg press|hack|wall sit|snatch balance", P.SQUAT),
    # hip-dominant lifts
    _rule(
        r"deadlift|good morning|swing|hip thrust|hip lift|glute bridge|hip bridge|butt lift|pull through|"
        r"pull-through|clean|snatch|rack pull|romanian|stiff-leg|stiff leg|stiff legs",
        P.HINGE,
    ),
    # pushing overhead
    _rule(
        r"overhead press|shoulder press|military press|push press|jerk|arnold press|handstand|"
        r"pike push|behind the neck press|dip|log lift|thruster",
        P.VERTICAL_PUSH,
    ),
    # pushing forward
    _rule(
        r"bench press|push-up|pushup|push up|chest press|floor press|board press|decline press|"
        r"incline press",
        P.HORIZONTAL_PUSH,
    ),
)

# The records no section uses (they are not main exercises, nor listed warm-up and cool-down
# activities), each read by a person: a held stretch, foam rolling or a dynamic drill, or the
# exercise it is. None: a sprint drill or a hold that is none of the patterns.
OTHER_PATTERNS: dict[str, MovementPattern | None] = {
    # held stretches
    **dict.fromkeys(
        (
            "Adductor_Groin", "All_Fours_Quad_Stretch", "Behind_Head_Chest_Stretch",
            "Chair_Lower_Back_Stretch", "Chin_To_Chest_Stretch", "Groin_and_Back_Stretch",
            "Hamstring_Stretch", "IT_Band_and_Glute_Stretch", "Intermediate_Groin_Stretch",
            "Intermediate_Hip_Flexor_and_Quad_Stretch", "Iron_Crosses_stretch",
            "Looking_At_Ceiling", "Lying_Bent_Leg_Groin", "Lying_Crossover", "Lying_Glute",
            "Lying_Hamstring", "Lying_Prone_Quadriceps", "One_Half_Locust", "One_Handed_Hang",
            "Overhead_Lat", "Overhead_Triceps", "Peroneals_Stretch",
            "Posterior_Tibialis_Stretch", "Quad_Stretch", "Seated_Biceps", "Seated_Front_Deltoid",
            "Seated_Glute", "Seated_Hamstring", "Seated_Hamstring_and_Calf_Stretch",
            "Side_Neck_Stretch", "Spinal_Stretch", "Standing_Gastrocnemius_Calf_Stretch",
        ),
        P.STRETCH,
    ),
    # foam rolling ("-SMR": self-myofascial release), as in classification.py, and drills
    **dict.fromkeys(
        (
            "Adductor", "Anterior_Tibialis-SMR", "Brachialis-SMR", "Calves-SMR", "Foot-SMR",
            "Iliotibial_Tract-SMR", "Lower_Back-SMR", "Neck-SMR", "Peroneals-SMR",
            "Piriformis-SMR", "Quadriceps-SMR", "Rhomboids-SMR", "Windmills", "Knee_Circles",
            "Kneeling_Arm_Drill", "Groiners", "Pelvic_Tilt_Into_Bridge",
        ),
        P.MOBILITY,
    ),
    # strength and plyometric records that are exercises in their own right
    "Decline_Push-Up": P.HORIZONTAL_PUSH,
    "Inverted_Row": P.HORIZONTAL_PULL,
    "Floor_Glute-Ham_Raise": P.HINGE,
    "Crossover_Reverse_Lunge": P.LUNGE,
    "Split_Squats": P.LUNGE,
    "Scapular_Pull-Up": P.ISOLATION,
    "Prone_Manual_Hamstring": P.ISOLATION,
    "Frog_Hops": None,
    "Linear_3-Part_Start_Technique": None,
    "Linear_Acceleration_Wall_Drill": None,
    "Moving_Claw_Series": None,
    "Stomach_Vacuum": None,
}

_LEGS = frozenset({"quadriceps", "hamstrings", "glutes", "adductors", "abductors"})
_SHOULDERS = frozenset({"shoulders"})
_PUSHERS = frozenset({"chest", "triceps"})
_PULLERS = frozenset({"lats", "middle back", "traps", "biceps", "forearms"})
_VERTICAL_PULLERS = frozenset({"lats"})
_CORE = frozenset({"abdominals"})
_JUMP = re.compile(r"\bjump|\bleap", re.IGNORECASE)
# trunk exercises that bend or turn one joint: the crunch family
_CORE_ISOLATION = re.compile(
    r"crunch|sit-up|sit up|situp|curl-up|leg raise|knee raise|hip raise|pull-in|roll-?out|"
    r"ab roller|jackknife|bottoms up|butt-up|cocoon|elbow to knee|otis-up|knee tuck|"
    r"flutter|scissor|v-up|toe touch|hanging pike|air bike|bicycle",
    re.IGNORECASE,
)


def main_pattern_of(source_id: str, record: dict[str, Any]) -> MovementPattern | None:
    """The movement pattern of an exercise record that suits the main workout, or None."""
    if source_id in EXCEPTIONS:
        return EXCEPTIONS[source_id]
    name = str(record.get("name", ""))
    primary = {str(item).lower() for item in record.get("primaryMuscles") or []}
    if primary == {"calves"}:
        return P.ISOLATION
    for rule, pattern in _NAME_RULES:
        if rule.search(name):
            return pattern
    force = record.get("force")
    mechanic = record.get("mechanic")
    category = record.get("category")
    if mechanic == "isolation":
        return P.ISOLATION
    if primary & _CORE:
        # a hold resists a movement; the crunch family bends one joint; the rest is no pattern
        if force == "static":
            return P.ROTATION
        return P.ISOLATION if _CORE_ISOLATION.search(name) else None
    if primary and primary <= _LEGS | {"calves"}:
        if primary <= {"adductors", "abductors"}:
            # lateral bounds and hops are done on one leg at a time
            return P.LUNGE if category == "plyometrics" else P.ISOLATION
        if category == "plyometrics":
            # two-footed jumps are squat-like; hops, bounds, skips, kicks and sprints are done
            # one leg after the other
            return P.SQUAT if _JUMP.search(name) else P.LUNGE
        if force == "static":
            return P.SQUAT
        if "quadriceps" in primary:
            return P.SQUAT
        return P.HINGE if force == "pull" else None
    if primary == {"lower back"}:
        return P.HINGE
    if force == "push":
        if primary & _SHOULDERS:
            return P.VERTICAL_PUSH
        if primary & _PUSHERS:
            return P.HORIZONTAL_PUSH
    if force == "pull":
        if primary & _VERTICAL_PULLERS:
            return P.VERTICAL_PULL
        if primary & _PULLERS:
            return P.HORIZONTAL_PULL
    return None


def pattern_of(
    source_id: str, record: dict[str, Any], uses: Sequence[WorkoutSection]
) -> MovementPattern | None:
    """The movement pattern Formiq gives an imported record that is neither cardio nor a
    listed warm-up or cool-down activity (classification.movement_pattern_of): by rules for a
    main exercise, by hand (OTHER_PATTERNS) for a record no section uses, none otherwise."""
    if WorkoutSection.MAIN_WORKOUT in uses:
        return main_pattern_of(source_id, record)
    return OTHER_PATTERNS.get(source_id)
