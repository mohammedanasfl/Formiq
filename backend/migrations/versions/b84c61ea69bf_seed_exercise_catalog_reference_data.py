"""seed exercise catalog reference data

Revision ID: b84c61ea69bf
Revises: 0d243d0e46b1
Create Date: 2026-10-06 18:46:23.600370

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert


# revision identifiers, used by Alembic.
revision: str = 'b84c61ea69bf'
down_revision: Union[str, Sequence[str], None] = '0d243d0e46b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The tables as they are at this revision. The application models are not
# imported, so later model changes do not change this migration.
muscle_groups = sa.table(
    "muscle_groups",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
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

MUSCLE_GROUPS = {
    "Chest": "The pectoral muscles at the front of the upper torso.",
    "Upper Back": "The trapezius, rhomboids and other muscles between the shoulder blades.",
    "Lats": "The latissimus dorsi, the broad muscles along the sides of the back.",
    "Lower Back": "The erector spinae, the muscles along the lower spine.",
    "Shoulders": "The deltoids as a whole; the front and rear heads are also listed separately.",
    "Front Deltoid": "The front (anterior) head of the deltoid.",
    "Rear Deltoid": "The rear (posterior) head of the deltoid.",
    "Biceps": "The muscles at the front of the upper arm that bend the elbow.",
    "Triceps": "The muscles at the back of the upper arm that straighten the elbow.",
    "Forearms": "The muscles of the forearm, including the grip muscles.",
    "Core": "The abdominal and deep trunk muscles that stabilize the spine.",
    "Obliques": "The muscles at the sides of the abdomen that rotate and bend the trunk.",
    "Glutes": "The gluteal muscles of the hips.",
    "Quadriceps": "The muscles at the front of the thigh that straighten the knee.",
    "Hamstrings": "The muscles at the back of the thigh that bend the knee and extend the hip.",
    "Calves": "The gastrocnemius and soleus, the muscles at the back of the lower leg.",
}

EQUIPMENT = {
    "Barbell": "A long bar loaded with weight plates.",
    "Dumbbell": "A short hand-held weight, used one in each hand or alone.",
    "Kettlebell": "A cast-iron weight with a handle on top.",
    "Bench": "A flat or adjustable weight bench.",
    "Squat Rack": "A rack that holds a barbell at shoulder height, with safety bars.",
    "Cable Machine": "A weight stack with adjustable pulleys and handles.",
    "Smith Machine": "A barbell that moves in fixed vertical rails.",
    "Leg Press Machine": "A machine for pushing a weighted platform with the legs.",
    "Pull-up Bar": "A fixed horizontal bar to hang and pull up from.",
    "Resistance Band": "An elastic band that provides resistance.",
}

# A deliberately small set of exercises, one or two per movement pattern.
# An exercise with no equipment needs none.
EXERCISES = [
    {
        "name": "Barbell Bench Press",
        "description": "Lie on a bench and press a barbell from the chest to straight arms.",
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "HORIZONTAL_PUSH",
        "muscles": {"Chest": "PRIMARY", "Front Deltoid": "SECONDARY", "Triceps": "SECONDARY"},
        "equipment": ["Barbell", "Bench"],
    },
    {
        "name": "Push-Up",
        "description": "From a high plank, lower the chest to the floor and push back up.",
        "difficulty": "BEGINNER",
        "movement_pattern": "HORIZONTAL_PUSH",
        "muscles": {
            "Chest": "PRIMARY",
            "Front Deltoid": "SECONDARY",
            "Triceps": "SECONDARY",
            "Core": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Seated Cable Row",
        "description": "Sit at a cable station and pull the handle to the torso.",
        "difficulty": "BEGINNER",
        "movement_pattern": "HORIZONTAL_PULL",
        "muscles": {
            "Upper Back": "PRIMARY",
            "Lats": "SECONDARY",
            "Rear Deltoid": "SECONDARY",
            "Biceps": "SECONDARY",
        },
        "equipment": ["Cable Machine"],
    },
    {
        "name": "Dumbbell Shoulder Press",
        "description": "Press two dumbbells from the shoulders to overhead.",
        "difficulty": "BEGINNER",
        "movement_pattern": "VERTICAL_PUSH",
        "muscles": {"Shoulders": "PRIMARY", "Triceps": "SECONDARY"},
        "equipment": ["Dumbbell"],
    },
    {
        "name": "Pull-Up",
        "description": "Hang from a bar with an overhand grip and pull the chin over the bar.",
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "VERTICAL_PULL",
        "muscles": {
            "Lats": "PRIMARY",
            "Upper Back": "SECONDARY",
            "Biceps": "SECONDARY",
            "Forearms": "SECONDARY",
        },
        "equipment": ["Pull-up Bar"],
    },
    {
        "name": "Barbell Back Squat",
        "description": "With a barbell across the upper back, squat down and stand back up.",
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "SQUAT",
        "muscles": {
            "Quadriceps": "PRIMARY",
            "Glutes": "PRIMARY",
            "Lower Back": "SECONDARY",
            "Hamstrings": "SECONDARY",
        },
        "equipment": ["Barbell", "Squat Rack"],
    },
    {
        "name": "Romanian Deadlift",
        "description": "Holding a barbell, hinge at the hips with soft knees and stand back up.",
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "HINGE",
        "muscles": {
            "Hamstrings": "PRIMARY",
            "Glutes": "PRIMARY",
            "Lower Back": "SECONDARY",
            "Forearms": "SECONDARY",
        },
        "equipment": ["Barbell"],
    },
    {
        "name": "Walking Lunge",
        "description": "Step into a lunge, then bring the back leg through into the next lunge.",
        "difficulty": "BEGINNER",
        "movement_pattern": "LUNGE",
        "muscles": {
            "Quadriceps": "PRIMARY",
            "Glutes": "PRIMARY",
            "Hamstrings": "SECONDARY",
            "Calves": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Farmer's Carry",
        "description": "Walk upright while holding a heavy dumbbell in each hand.",
        "difficulty": "BEGINNER",
        "movement_pattern": "CARRY",
        "muscles": {"Forearms": "PRIMARY", "Upper Back": "SECONDARY", "Core": "SECONDARY"},
        "equipment": ["Dumbbell"],
    },
    {
        "name": "Cable Woodchop",
        "description": "Pull a cable handle diagonally across the body while rotating the torso.",
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "ROTATION",
        "muscles": {"Obliques": "PRIMARY", "Core": "SECONDARY"},
        "equipment": ["Cable Machine"],
    },
    {
        "name": "Dumbbell Biceps Curl",
        "description": "Curl two dumbbells from the thighs to the shoulders.",
        "difficulty": "BEGINNER",
        "movement_pattern": "ISOLATION",
        "muscles": {"Biceps": "PRIMARY", "Forearms": "SECONDARY"},
        "equipment": ["Dumbbell"],
    },
]


def id_of(table, name):
    """The id of the row with this name, or NULL (a NOT NULL violation) if there is none."""
    return sa.select(table.c.id).where(table.c.name == name).scalar_subquery()


def upgrade() -> None:
    """Insert the reference data. Rows that already exist are left as they are,
    so running the inserts again adds no duplicates."""
    op.execute(
        insert(muscle_groups)
        .values([{"name": name, "description": text} for name, text in MUSCLE_GROUPS.items()])
        .on_conflict_do_nothing(index_elements=["name"])
    )
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
    """Delete the reference data. Deleting the exercises also deletes their
    muscle and equipment links. Muscle groups and equipment that other
    exercises still use cannot be deleted, so the downgrade then fails instead
    of changing those exercises."""
    op.execute(
        exercises.delete().where(exercises.c.name.in_([exercise["name"] for exercise in EXERCISES]))
    )
    op.execute(equipment.delete().where(equipment.c.name.in_(list(EQUIPMENT))))
    op.execute(muscle_groups.delete().where(muscle_groups.c.name.in_(list(MUSCLE_GROUPS))))
