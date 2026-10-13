"""add exercise source, uses and images

Revision ID: 620eafb9c204
Revises: cf98650b3833
Create Date: 2026-10-13 18:05:00.000000

Prepares the catalog for exercises imported from an upstream dataset
(python -m app.cli import-exercises), and for Formiq's own classification of
what each exercise suits:

- source, source_id, source_version and source_record: where an exercise comes
  from. Formiq's own exercises, every existing row, are FORMIQ with no
  source_id or record; an imported one keeps its upstream id (unique per
  source, apart from Formiq's id), the upstream version, and the upstream
  record with every field as it was.
- uses: the workout sections (WARM_UP, MAIN_WORKOUT, COOL_DOWN) Formiq judges an
  exercise suitable for. Formiq's own exercises get theirs here, below.
- image_paths: an exercise's images, in order, relative to the images
  directory. None exist yet.
- movement_pattern may be null: Formiq has not classified most imported
  exercises, and none is invented for them.
- the muscle groups and equipment the upstream dataset names that the catalog
  lacked (app.catalog.free_exercise_db maps every upstream value to one).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert


# revision identifiers, used by Alembic.
revision: str = '620eafb9c204'
down_revision: Union[str, Sequence[str], None] = 'cf98650b3833'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The tables as they are at this revision. The application models are not
# imported, so later model changes do not change this migration.
muscle_groups = sa.table(
    "muscle_groups",
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
)
equipment = sa.table(
    "equipment",
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
)

MUSCLE_GROUPS = {
    "Abductors": "The muscles at the outer hip that move the leg out to the side.",
    "Adductors": "The muscles of the inner thigh that bring the leg in toward the body.",
    "Neck": "The muscles at the front, sides and back of the neck.",
}

EQUIPMENT = {
    "Machine": "A weight or cardio machine that the exercise's source does not name.",
    "Medicine Ball": "A weighted ball for throwing, slamming and carrying.",
    "Exercise Ball": "A large inflatable ball, also called a stability ball.",
    "Foam Roller": "A firm foam cylinder for self-massage.",
    "EZ Curl Bar": "A short barbell with angled grips.",
    "Other Equipment": "Equipment that the exercise's source does not name, such as a box, "
    "a sled, a strap, a chair or a bar.",
}

# Formiq's classification of its own exercises (all the rows at this
# revision): a strength exercise is a main exercise, a mobility drill warms up,
# a stretch cools down, and easy cardio does both. Then the exceptions.
STRENGTH_PATTERNS = (
    "HORIZONTAL_PUSH",
    "HORIZONTAL_PULL",
    "VERTICAL_PUSH",
    "VERTICAL_PULL",
    "SQUAT",
    "HINGE",
    "LUNGE",
    "CARRY",
    "ROTATION",
    "ISOLATION",
)
USES_BY_PATTERN = {
    **{pattern: ["MAIN_WORKOUT"] for pattern in STRENGTH_PATTERNS},
    "MOBILITY": ["WARM_UP"],
    "STRETCH": ["COOL_DOWN"],
    "CARDIO": ["WARM_UP", "COOL_DOWN"],
}
USES_BY_NAME = {
    # slow, gentle drills that also suit the end of a workout
    "Cat-Cow": ["WARM_UP", "COOL_DOWN"],
    "World's Greatest Stretch": ["WARM_UP", "COOL_DOWN"],
    "Thoracic Open Book": ["WARM_UP", "COOL_DOWN"],
    # jumping raises the heart rate: a warm-up, not a cool-down
    "Jumping Jacks": ["WARM_UP"],
    # light bodyweight activation drills, and main exercises for a beginner
    "Bodyweight Squat": ["WARM_UP", "MAIN_WORKOUT"],
    "Glute Bridge": ["WARM_UP", "MAIN_WORKOUT"],
    "Bird Dog": ["WARM_UP", "MAIN_WORKOUT"],
}


def uses(values):
    return sa.cast(postgresql.array(values), postgresql.ARRAY(sa.String(20)))


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'exercises', 'movement_pattern', existing_type=sa.String(length=30), nullable=True
    )
    op.add_column(
        'exercises',
        sa.Column(
            'uses',
            postgresql.ARRAY(sa.String(length=20)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
    )
    op.add_column(
        'exercises',
        sa.Column(
            'image_paths',
            postgresql.ARRAY(sa.String(length=255)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
    )
    op.add_column(
        'exercises',
        sa.Column('source', sa.String(length=30), server_default='FORMIQ', nullable=False),
    )
    op.add_column('exercises', sa.Column('source_id', sa.String(length=100), nullable=True))
    op.add_column('exercises', sa.Column('source_version', sa.String(length=64), nullable=True))
    op.add_column(
        'exercises',
        sa.Column('source_record', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_unique_constraint(
        'exercises_source_source_id_key', 'exercises', ['source', 'source_id']
    )

    exercises = sa.table(
        "exercises",
        sa.column("name", sa.String),
        sa.column("movement_pattern", sa.String),
        sa.column("uses", postgresql.ARRAY(sa.String(20))),
    )
    for pattern, values in USES_BY_PATTERN.items():
        op.execute(
            exercises.update()
            .where(exercises.c.movement_pattern == pattern)
            .values(uses=uses(values))
        )
    for name, values in USES_BY_NAME.items():
        op.execute(exercises.update().where(exercises.c.name == name).values(uses=uses(values)))

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


def downgrade() -> None:
    """Downgrade schema. The earlier schema cannot tell an imported exercise
    from Formiq's own, and needs a movement pattern for each: with imported
    exercises in the catalog, the downgrade fails instead of changing them."""
    imported = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM exercises "
            "WHERE source <> 'FORMIQ' OR movement_pattern IS NULL)"
        )
    )
    if imported:
        raise RuntimeError(
            "the catalog has imported or unclassified exercises, which the earlier schema "
            "cannot hold; remove them before downgrading"
        )
    # muscle groups and equipment that an exercise uses cannot be deleted
    # (RESTRICT): with none imported, nothing uses these
    op.execute(equipment.delete().where(equipment.c.name.in_(list(EQUIPMENT))))
    op.execute(muscle_groups.delete().where(muscle_groups.c.name.in_(list(MUSCLE_GROUPS))))
    op.drop_constraint('exercises_source_source_id_key', 'exercises', type_='unique')
    op.drop_column('exercises', 'source_record')
    op.drop_column('exercises', 'source_version')
    op.drop_column('exercises', 'source_id')
    op.drop_column('exercises', 'source')
    op.drop_column('exercises', 'image_paths')
    op.drop_column('exercises', 'uses')
    op.alter_column(
        'exercises', 'movement_pattern', existing_type=sa.String(length=30), nullable=False
    )
