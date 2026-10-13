"""seed more exercises and warm-up and cool-down activities

Revision ID: 14d543e636a8
Revises: c062e4afd0b0
Create Date: 2026-10-13 12:05:00.000000

The first seed (b84c61ea69bf) has one or two exercises per movement pattern and
nothing to warm up or cool down with. This adds, with the same rules:

- exercises for the movement patterns with little or no equipment, and for the
  equipment the first seed listed but no exercise used (kettlebell, Smith
  machine, leg press, resistance band);
- light warm-up and cool-down activities: MOBILITY drills, STRETCH holds and
  easy CARDIO, each tagged with the muscles it prepares or stretches;
- two pieces of cardio equipment, for the easy cycling and rowing.

Rows that already exist, by name, are left as they are, so running it again
adds no duplicates and changes nothing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert


# revision identifiers, used by Alembic.
revision: str = '14d543e636a8'
down_revision: Union[str, Sequence[str], None] = 'c062e4afd0b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The tables as they are at this revision. The application models are not
# imported, so later model changes do not change this migration.
muscle_groups = sa.table(
    "muscle_groups",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
)
equipment = sa.table(
    "equipment",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
)
exercises = sa.table(
    "exercises",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
    sa.column("difficulty", sa.String),
    sa.column("movement_pattern", sa.String),
)
exercise_muscles = sa.table(
    "exercise_muscles",
    sa.column("exercise_id", sa.Integer),
    sa.column("muscle_group_id", sa.Integer),
    sa.column("role", sa.String),
)
exercise_equipment = sa.table(
    "exercise_equipment",
    sa.column("exercise_id", sa.Integer),
    sa.column("equipment_id", sa.Integer),
)

EQUIPMENT = {
    "Stationary Bike": "An indoor exercise bike with adjustable resistance.",
    "Rowing Machine": "An indoor rower with a sliding seat and a handle on a chain or strap.",
}

# The muscle groups and the other equipment are the first seed's.
STRENGTH_EXERCISES = [
    {
        "name": "Bodyweight Squat",
        "description": "Stand with feet shoulder-width apart, sit the hips back and down, "
        "and stand back up.",
        "difficulty": "BEGINNER",
        "movement_pattern": "SQUAT",
        "muscles": {
            "Quadriceps": "PRIMARY",
            "Glutes": "PRIMARY",
            "Hamstrings": "SECONDARY",
            "Core": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Goblet Squat",
        "description": "Hold one dumbbell at the chest, squat down between the knees and "
        "stand back up.",
        "difficulty": "BEGINNER",
        "movement_pattern": "SQUAT",
        "muscles": {
            "Quadriceps": "PRIMARY",
            "Glutes": "PRIMARY",
            "Core": "SECONDARY",
            "Upper Back": "SECONDARY",
        },
        "equipment": ["Dumbbell"],
    },
    {
        "name": "Leg Press",
        "description": "Sit in the leg press, push the platform away with both feet and "
        "lower it under control.",
        "difficulty": "BEGINNER",
        "movement_pattern": "SQUAT",
        "muscles": {"Quadriceps": "PRIMARY", "Glutes": "PRIMARY", "Hamstrings": "SECONDARY"},
        "equipment": ["Leg Press Machine"],
    },
    {
        "name": "Smith Machine Squat",
        "description": "With the Smith machine bar across the upper back, squat down and "
        "stand back up.",
        "difficulty": "BEGINNER",
        "movement_pattern": "SQUAT",
        "muscles": {"Quadriceps": "PRIMARY", "Glutes": "PRIMARY", "Hamstrings": "SECONDARY"},
        "equipment": ["Smith Machine"],
    },
    {
        "name": "Glute Bridge",
        "description": "Lie on your back with the knees bent and lift the hips until the "
        "body is straight from knees to shoulders.",
        "difficulty": "BEGINNER",
        "movement_pattern": "HINGE",
        "muscles": {"Glutes": "PRIMARY", "Hamstrings": "SECONDARY", "Core": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Dumbbell Romanian Deadlift",
        "description": "Holding a dumbbell in each hand, hinge at the hips with soft knees "
        "and stand back up.",
        "difficulty": "BEGINNER",
        "movement_pattern": "HINGE",
        "muscles": {
            "Hamstrings": "PRIMARY",
            "Glutes": "PRIMARY",
            "Lower Back": "SECONDARY",
            "Forearms": "SECONDARY",
        },
        "equipment": ["Dumbbell"],
    },
    {
        "name": "Kettlebell Swing",
        "description": "Hinge at the hips and drive them forward to swing a kettlebell to "
        "chest height.",
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "HINGE",
        "muscles": {
            "Glutes": "PRIMARY",
            "Hamstrings": "PRIMARY",
            "Lower Back": "SECONDARY",
            "Core": "SECONDARY",
            "Forearms": "SECONDARY",
        },
        "equipment": ["Kettlebell"],
    },
    {
        "name": "Dumbbell Bench Press",
        "description": "Lie on a bench and press two dumbbells from the chest to straight arms.",
        "difficulty": "BEGINNER",
        "movement_pattern": "HORIZONTAL_PUSH",
        "muscles": {"Chest": "PRIMARY", "Front Deltoid": "SECONDARY", "Triceps": "SECONDARY"},
        "equipment": ["Dumbbell", "Bench"],
    },
    {
        "name": "Pike Push-Up",
        "description": "From a pike position with the hips high, bend the elbows to lower "
        "the head toward the floor and push back up.",
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "VERTICAL_PUSH",
        "muscles": {"Shoulders": "PRIMARY", "Triceps": "SECONDARY", "Core": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "One-Arm Dumbbell Row",
        "description": "With one hand on a bench or a sturdy surface, pull a dumbbell to the "
        "hip and lower it under control.",
        "difficulty": "BEGINNER",
        "movement_pattern": "HORIZONTAL_PULL",
        "muscles": {
            "Upper Back": "PRIMARY",
            "Lats": "PRIMARY",
            "Rear Deltoid": "SECONDARY",
            "Biceps": "SECONDARY",
        },
        "equipment": ["Dumbbell"],
    },
    {
        "name": "Resistance Band Row",
        "description": "Anchor a band in front of you and pull the handles to the torso, "
        "squeezing the shoulder blades together.",
        "difficulty": "BEGINNER",
        "movement_pattern": "HORIZONTAL_PULL",
        "muscles": {
            "Upper Back": "PRIMARY",
            "Lats": "SECONDARY",
            "Rear Deltoid": "SECONDARY",
            "Biceps": "SECONDARY",
        },
        "equipment": ["Resistance Band"],
    },
    {
        "name": "Lat Pulldown",
        "description": "Sit at a cable station and pull a wide bar down to the upper chest.",
        "difficulty": "BEGINNER",
        "movement_pattern": "VERTICAL_PULL",
        "muscles": {"Lats": "PRIMARY", "Upper Back": "SECONDARY", "Biceps": "SECONDARY"},
        "equipment": ["Cable Machine"],
    },
    {
        "name": "Cable Triceps Pushdown",
        "description": "Push a cable bar or rope down until the elbows are straight, keeping "
        "the elbows at the sides.",
        "difficulty": "BEGINNER",
        "movement_pattern": "ISOLATION",
        "muscles": {"Triceps": "PRIMARY"},
        "equipment": ["Cable Machine"],
    },
    {
        "name": "Standing Calf Raise",
        "description": "Rise onto the balls of the feet, then lower the heels under control.",
        "difficulty": "BEGINNER",
        "movement_pattern": "ISOLATION",
        "muscles": {"Calves": "PRIMARY"},
        "equipment": [],
    },
    {
        "name": "Bird Dog",
        "description": "On hands and knees, reach one arm forward and the opposite leg back, "
        "hold, and return; alternate sides.",
        "difficulty": "BEGINNER",
        "movement_pattern": "ROTATION",
        "muscles": {"Core": "PRIMARY", "Lower Back": "SECONDARY", "Glutes": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Band Pallof Press",
        "description": "Stand side-on to an anchored band and press it straight out from the "
        "chest, resisting the pull to rotate.",
        "difficulty": "BEGINNER",
        "movement_pattern": "ROTATION",
        "muscles": {"Core": "PRIMARY", "Obliques": "PRIMARY"},
        "equipment": ["Resistance Band"],
    },
]

# Light activities to warm up (MOBILITY, CARDIO) and cool down (STRETCH,
# MOBILITY, CARDIO). All BEGINNER; the muscles are those the activity prepares
# or stretches.
ACTIVITIES = [
    {
        "name": "Arm Circles",
        "description": "Hold the arms out to the sides and draw small, then larger, circles "
        "forward and backward.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "muscles": {
            "Shoulders": "PRIMARY",
            "Front Deltoid": "SECONDARY",
            "Rear Deltoid": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Band Pull-Apart",
        "description": "Hold a light band at shoulder height with straight arms and pull it "
        "apart until it touches the chest.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "muscles": {"Rear Deltoid": "PRIMARY", "Upper Back": "PRIMARY"},
        "equipment": ["Resistance Band"],
    },
    {
        "name": "Cat-Cow",
        "description": "On hands and knees, slowly round the back up, then let it sag as the "
        "chest lifts; move with the breath.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "muscles": {"Lower Back": "PRIMARY", "Upper Back": "SECONDARY", "Core": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Leg Swings",
        "description": "Holding a support, swing one leg forward and back in a relaxed, "
        "controlled arc; then the other leg.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "muscles": {"Hamstrings": "PRIMARY", "Glutes": "SECONDARY", "Quadriceps": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Hip Circles",
        "description": "Hands on the hips, draw slow, wide circles with the hips in each "
        "direction.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "muscles": {"Glutes": "PRIMARY", "Lower Back": "SECONDARY", "Core": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Inchworm",
        "description": "From standing, walk the hands out to a high plank and back, keeping "
        "the legs as straight as is comfortable.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "muscles": {"Hamstrings": "PRIMARY", "Shoulders": "SECONDARY", "Core": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "World's Greatest Stretch",
        "description": "Step into a long lunge, place both hands inside the front foot, then "
        "rotate the chest and reach one arm up; alternate sides.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "muscles": {
            "Glutes": "PRIMARY",
            "Hamstrings": "SECONDARY",
            "Quadriceps": "SECONDARY",
            "Upper Back": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Thoracic Open Book",
        "description": "Lying on your side with the knees bent, open the top arm across the "
        "body to rotate the upper back, then return.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "muscles": {"Upper Back": "PRIMARY", "Chest": "SECONDARY", "Obliques": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Brisk Walk",
        "description": "Walk at a pace that raises your breathing but still lets you talk, "
        "outdoors or on a treadmill.",
        "difficulty": "BEGINNER",
        "movement_pattern": "CARDIO",
        "muscles": {
            "Calves": "PRIMARY",
            "Quadriceps": "SECONDARY",
            "Glutes": "SECONDARY",
            "Hamstrings": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Marching in Place",
        "description": "March on the spot at an easy pace, lifting the knees and swinging the "
        "arms.",
        "difficulty": "BEGINNER",
        "movement_pattern": "CARDIO",
        "muscles": {"Quadriceps": "PRIMARY", "Calves": "SECONDARY", "Core": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Jumping Jacks",
        "description": "Jump the feet out while raising the arms overhead, then jump back; "
        "keep it light.",
        "difficulty": "BEGINNER",
        "movement_pattern": "CARDIO",
        "muscles": {
            "Calves": "PRIMARY",
            "Shoulders": "SECONDARY",
            "Quadriceps": "SECONDARY",
            "Glutes": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Easy Stationary Cycling",
        "description": "Pedal at a light resistance and an easy, steady pace.",
        "difficulty": "BEGINNER",
        "movement_pattern": "CARDIO",
        "muscles": {
            "Quadriceps": "PRIMARY",
            "Glutes": "SECONDARY",
            "Hamstrings": "SECONDARY",
            "Calves": "SECONDARY",
        },
        "equipment": ["Stationary Bike"],
    },
    {
        "name": "Easy Rowing",
        "description": "Row at a light, steady pace: push with the legs, then pull the "
        "handle to the lower ribs.",
        "difficulty": "BEGINNER",
        "movement_pattern": "CARDIO",
        "muscles": {
            "Upper Back": "PRIMARY",
            "Quadriceps": "PRIMARY",
            "Lats": "SECONDARY",
            "Glutes": "SECONDARY",
            "Biceps": "SECONDARY",
        },
        "equipment": ["Rowing Machine"],
    },
    {
        "name": "Standing Quad Stretch",
        "description": "Standing on one leg, hold the other foot behind you and draw the heel "
        "toward the glutes; hold, then switch.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "muscles": {"Quadriceps": "PRIMARY"},
        "equipment": [],
    },
    {
        "name": "Standing Hamstring Stretch",
        "description": "Place one heel forward with the leg straight and hinge at the hips "
        "until you feel the back of the thigh; hold, then switch.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "muscles": {"Hamstrings": "PRIMARY", "Calves": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Figure-Four Glute Stretch",
        "description": "Lying on your back, cross one ankle over the opposite knee and draw "
        "both legs toward the chest; hold, then switch.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "muscles": {"Glutes": "PRIMARY"},
        "equipment": [],
    },
    {
        "name": "Kneeling Hip Flexor Stretch",
        "description": "Kneel on one knee, tuck the pelvis under and shift forward until you "
        "feel the front of the hip; hold, then switch.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "muscles": {"Quadriceps": "PRIMARY"},
        "equipment": [],
    },
    {
        "name": "Standing Calf Stretch",
        "description": "With the hands on a wall, step one foot back and press the heel "
        "down; hold, then switch.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "muscles": {"Calves": "PRIMARY"},
        "equipment": [],
    },
    {
        "name": "Doorway Chest Stretch",
        "description": "Place a forearm on a door frame at shoulder height and turn gently "
        "away until you feel the chest; hold, then switch.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "muscles": {"Chest": "PRIMARY", "Front Deltoid": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Cross-Body Shoulder Stretch",
        "description": "Bring one straight arm across the chest and hold it there with the "
        "other arm; hold, then switch.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "muscles": {
            "Rear Deltoid": "PRIMARY",
            "Shoulders": "SECONDARY",
            "Upper Back": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Overhead Triceps Stretch",
        "description": "Reach one hand down the upper back and gently press that elbow with "
        "the other hand; hold, then switch.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "muscles": {"Triceps": "PRIMARY", "Lats": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Child's Pose",
        "description": "Kneel, sit the hips back toward the heels and reach the arms forward "
        "on the floor; breathe slowly.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "muscles": {"Lats": "PRIMARY", "Lower Back": "SECONDARY", "Upper Back": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Supine Spinal Twist",
        "description": "Lying on your back, let both bent knees fall to one side while the "
        "shoulders stay down; hold, then switch.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "muscles": {"Lower Back": "PRIMARY", "Obliques": "SECONDARY", "Glutes": "SECONDARY"},
        "equipment": [],
    },
]

EXERCISES = STRENGTH_EXERCISES + ACTIVITIES


def id_of(table, name):
    """The id of the row with this name, or NULL (a NOT NULL violation) if there is none."""
    return sa.select(table.c.id).where(table.c.name == name).scalar_subquery()


def upgrade() -> None:
    """Insert the reference data. Rows that already exist are left as they are,
    so running the inserts again adds no duplicates."""
    op.execute(
        insert(equipment)
        .values([{"name": name, "description": text} for name, text in EQUIPMENT.items()])
        .on_conflict_do_nothing(index_elements=["name"])
    )
    op.execute(
        insert(exercises)
        .values(
            [
                {
                    key: exercise[key]
                    for key in ("name", "description", "difficulty", "movement_pattern")
                }
                for exercise in EXERCISES
            ]
        )
        .on_conflict_do_nothing(index_elements=["name"])
    )
    op.execute(
        insert(exercise_muscles)
        .values(
            [
                {
                    "exercise_id": id_of(exercises, exercise["name"]),
                    "muscle_group_id": id_of(muscle_groups, muscle),
                    "role": role,
                }
                for exercise in EXERCISES
                for muscle, role in exercise["muscles"].items()
            ]
        )
        .on_conflict_do_nothing()
    )
    op.execute(
        insert(exercise_equipment)
        .values(
            [
                {
                    "exercise_id": id_of(exercises, exercise["name"]),
                    "equipment_id": id_of(equipment, item),
                }
                for exercise in EXERCISES
                for item in exercise["equipment"]
            ]
        )
        .on_conflict_do_nothing()
    )


def downgrade() -> None:
    """Delete this seed's exercises (and with them their muscle and equipment
    links) and equipment. An exercise a workout plan or session uses, or
    equipment another exercise uses, cannot be deleted, so the downgrade then
    fails instead of changing them."""
    op.execute(
        exercises.delete().where(exercises.c.name.in_([exercise["name"] for exercise in EXERCISES]))
    )
    op.execute(equipment.delete().where(equipment.c.name.in_(list(EQUIPMENT))))
