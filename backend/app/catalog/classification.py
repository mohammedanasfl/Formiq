"""Formiq's classification of the free-exercise-db exercises: the workout
sections (WARM_UP, MAIN_WORKOUT, COOL_DOWN) each one suits.

It is Formiq's judgement, not the dataset's. The upstream category is kept as
it was in the exercise's record, and nothing here changes a record. An
exercise may suit more than one section, or none: one that suits none stays
in the catalog, readable and searchable, but the coach cannot put it in a
proposed workout.

MAIN_WORKOUT: the training categories, when the record names the exercise's
equipment ("body only" included). A record without equipment (null) may still
need some, such as a bar for an inverted row, so Formiq could not check it
against what the user has; only the few in NO_EQUIPMENT_NEEDED, whose
instructions need nothing, are main exercises. EXTRA_MAIN_WORKOUT adds the
core exercises the dataset files under stretching.

WARM_UP and COOL_DOWN: only the exercises listed below, each assessed from its
instructions, level and equipment, never from its category alone. Every one
is BEGINNER (a proposal's warm-up and cool-down are light), done alone, and
needs no equipment the record leaves out. A warm-up activity raises the heart
rate or moves the joints through their range (easy cardio, circles, swings,
light activation); a cool-down activity is easy cardio or a held stretch.
Left out, though listed as stretching:

- every partner stretch (all the "expert" ones) and every intermediate one;
- stretches that need a strap, a chair or a step the record does not name
  (Hamstring_Stretch, Chair_Lower_Back_Stretch, Spinal_Stretch,
  Standing_Gastrocnemius_Calf_Stretch);
- neck stretches pulled by the hands (Chin_To_Chest_Stretch,
  Side_Neck_Stretch), foam rolling of the lower spine (Lower_Back-SMR), knee
  circles (Knee_Circles), a deep kneeling backbend (Looking_At_Ceiling),
  One_Half_Locust and One_Handed_Hang;
- strength and breathing exercises filed under stretching (Superman,
  Scissor_Kick, Toe_Touchers, Lower_Back_Curl, Stomach_Vacuum).

Faster or intermediate cardio (running, rope jumping, rowing, the elliptical,
stair machines, skating, sprints) is left out of both: the warm-up and
cool-down are light. No cardio is a main exercise, since a proposal's main
exercises are prescribed in reps.

Equipment: a record's equipment is mapped as it is, except for the few in
EQUIPMENT_NEEDED, whose record says "body only" though their instructions
hang from a bar, dip on a bench or between bars, or lean on a racked bar.
Formiq links them to that equipment; the record itself is kept as it was.

Duplicates: the few records in FORMIQ_DUPLICATES are one of Formiq's own
exercises under another name, with the same equipment. They suit no section,
so a workout never holds both; they stay in the catalog, readable by id.
"""

from app.schemas.exercise import WorkoutSection

WARM_UP = WorkoutSection.WARM_UP
MAIN_WORKOUT = WorkoutSection.MAIN_WORKOUT
COOL_DOWN = WorkoutSection.COOL_DOWN

# the upstream categories of exercises that train: main exercises
TRAINING_CATEGORIES = frozenset(
    {"strength", "powerlifting", "olympic weightlifting", "strongman", "plyometrics"}
)

# main exercises whose record names no equipment and whose instructions need none
NO_EQUIPMENT_NEEDED = frozenset(
    {
        "Alternate_Leg_Diagonal_Bound",
        "Bodyweight_Walking_Lunge",
        "Carioca_Quick_Step",
        "Mountain_Climbers",
        "Side_Standing_Long_Jump",
    }
)

# core exercises the dataset files under stretching
EXTRA_MAIN_WORKOUT = frozenset({"Lower_Back_Curl", "Scissor_Kick", "Superman", "Toe_Touchers"})

# easy cardio at a light pace: a warm-up, and a cool-down where it stays easy
WARM_UP_CARDIO = frozenset(
    {
        "Bicycling",
        "Bicycling_Stationary",
        "Jogging_Treadmill",
        "Recumbent_Bike",
        "Walking_Treadmill",
    }
)
COOL_DOWN_CARDIO = frozenset(
    {"Bicycling", "Bicycling_Stationary", "Recumbent_Bike", "Walking_Treadmill"}
)

# dynamic drills: circles, swings, light activation, and foam rolling
WARM_UP_DRILLS = frozenset(
    {
        "Ankle_Circles",
        "Arm_Circles",
        "Dynamic_Back_Stretch",
        "Dynamic_Chest_Stretch",
        "Elbow_Circles",
        "Front_Leg_Raises",
        "Hamstring-SMR",
        "Hip_Circles_prone",
        "Inchworm",
        "Latissimus_Dorsi-SMR",
        "Rear_Leg_Raises",
        "Round_The_World_Shoulder_Stretch",
        "Shoulder_Circles",
        "Shoulder_Raise",
        "Side_Leg_Raises",
        "Sit_Squats",
        "Standing_Hip_Circles",
        "Torso_Rotation",
        "Wrist_Circles",
    }
)

# held stretches, and foam rolling
COOL_DOWN_STRETCHES = frozenset(
    {
        "90_90_Hamstring",
        "Ankle_On_The_Knee",
        "Calf_Stretch_Elbows_Against_Wall",
        "Calf_Stretch_Hands_Against_Wall",
        "Cat_Stretch",
        "Chair_Leg_Extended_Stretch",
        "Chair_Upper_Body_Stretch",
        "Chest_And_Front_Of_Shoulder_Stretch",
        "Chest_Stretch_on_Stability_Ball",
        "Childs_Pose",
        "Dancers_Stretch",
        "Elbows_Back",
        "Hamstring-SMR",
        "Hug_A_Ball",
        "Hug_Knees_To_Chest",
        "Knee_Across_The_Body",
        "Kneeling_Forearm_Stretch",
        "Kneeling_Hip_Flexor",
        "Latissimus_Dorsi-SMR",
        "Leg-Up_Hamstring_Stretch",
        "Middle_Back_Stretch",
        "On-Your-Back_Quad_Stretch",
        "On_Your_Side_Quad_Stretch",
        "One_Arm_Against_Wall",
        "One_Knee_To_Chest",
        "Overhead_Stretch",
        "Pyramid",
        "Runners_Stretch",
        "Seated_Calf_Stretch",
        "Seated_Floor_Hamstring_Stretch",
        "Seated_Overhead_Stretch",
        "Shoulder_Stretch",
        "Side-Lying_Floor_Stretch",
        "Side_Lying_Groin_Stretch",
        "Side_Wrist_Pull",
        "Standing_Biceps_Stretch",
        "Standing_Elevated_Quad_Stretch",
        "Standing_Hamstring_and_Calf_Stretch",
        "Standing_Hip_Flexors",
        "Standing_Lateral_Stretch",
        "Standing_Pelvic_Tilt",
        "Standing_Soleus_And_Achilles_Stretch",
        "Standing_Toe_Touches",
        "The_Straddle",
        "Tricep_Side_Stretch",
        "Triceps_Stretch",
        "Upper_Back-Leg_Grab",
        "Upper_Back_Stretch",
        "Upward_Stretch",
    }
)

WARM_UP_IDS = WARM_UP_CARDIO | WARM_UP_DRILLS
COOL_DOWN_IDS = COOL_DOWN_CARDIO | COOL_DOWN_STRETCHES

# Formiq's equipment for records that say "body only" but need some, by its
# instructions: a pull-up bar to hang from, a bench or parallel bars to dip on
# ("other", as Dips_-_Chest_Version's record names them), a bar in a rack.
EQUIPMENT_NEEDED = {
    "Chin-Up": ("Pull-up Bar",),
    "Gorilla_Chin_Crunch": ("Pull-up Bar",),
    "Hanging_Leg_Raise": ("Pull-up Bar",),
    "Hanging_Pike": ("Pull-up Bar",),
    "Pullups": ("Pull-up Bar",),
    # a V-bar handle hung on the pull-up bar
    "V-Bar_Pullup": ("Pull-up Bar", "Other Equipment"),
    "Wide-Grip_Rear_Pull-Up": ("Pull-up Bar",),
    "Wind_Sprints": ("Pull-up Bar",),
    "Bench_Dips": ("Bench",),
    "Dips_-_Triceps_Version": ("Other Equipment",),
    "Body_Tricep_Press": ("Barbell", "Squat Rack"),
}

# Records that are one of Formiq's own exercises (by its name) under another
# name, done with the same equipment
FORMIQ_DUPLICATES = {
    "Bodyweight_Walking_Lunge": "Walking Lunge",
    "Pushups": "Push-Up",
    "Seated_Cable_Rows": "Seated Cable Row",
    "Standing_Cable_Wood_Chop": "Cable Woodchop",
    "Triceps_Pushdown": "Cable Triceps Pushdown",
}


def uses_of(source_id: str, category: str, equipment: str | None) -> list[WorkoutSection]:
    """The sections the upstream exercise suits, in workout order. category
    and equipment are the record's own values."""
    if source_id in FORMIQ_DUPLICATES:
        return []
    uses = set()
    if source_id in WARM_UP_IDS:
        uses.add(WARM_UP)
    if source_id in EXTRA_MAIN_WORKOUT or (
        category in TRAINING_CATEGORIES
        and (equipment is not None or source_id in NO_EQUIPMENT_NEEDED)
    ):
        uses.add(MAIN_WORKOUT)
    if source_id in COOL_DOWN_IDS:
        uses.add(COOL_DOWN)
    return [section for section in WorkoutSection if section in uses]
