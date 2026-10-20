"""add treadmill equipment

Revision ID: c9e24b7a5d13
Revises: a7d3f1c82e4b
Create Date: 2026-10-20 10:00:00.000000

The catalog named a treadmill only as "Machine", the equipment of the free-exercise-db
records for it. A user who said they had a treadmill was refused by the coach's
search ("the catalog has no equipment 'Treadmill'"), so its one imported treadmill
exercise could not be found (live QA, 2026-10-19). This adds the equipment itself;
`python -m app.cli import-exercises` then links the treadmill records to it, as
app.catalog.classification.EQUIPMENT_NAMED says.

Safe to run on a catalog that has users' plans: it adds one reference row (or leaves
it as it is when it exists) and changes no exercise. The downgrade gives the exercises
that use it their record's own equipment, "Machine", and deletes it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

# revision identifiers, used by Alembic.
revision: str = 'c9e24b7a5d13'
down_revision: Union[str, None] = 'a7d3f1c82e4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAME = "Treadmill"
DESCRIPTION = "A motorised belt for walking or running indoors."

equipment = sa.table(
    "equipment",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
)
exercise_equipment = sa.table(
    "exercise_equipment",
    sa.column("exercise_id", sa.Integer),
    sa.column("equipment_id", sa.Integer),
)


def upgrade() -> None:
    op.execute(
        insert(equipment)
        .values([{"name": NAME, "description": DESCRIPTION}])
        .on_conflict_do_nothing(index_elements=["name"])
    )


def downgrade() -> None:
    """Link each exercise that uses a treadmill to "Machine" instead (what its
    record says), then delete the equipment."""
    treadmill = sa.select(equipment.c.id).where(equipment.c.name == NAME).scalar_subquery()
    machine = sa.select(equipment.c.id).where(equipment.c.name == "Machine").scalar_subquery()
    op.execute(
        insert(exercise_equipment)
        .from_select(
            ["exercise_id", "equipment_id"],
            sa.select(exercise_equipment.c.exercise_id, machine).where(
                exercise_equipment.c.equipment_id == treadmill
            ),
        )
        .on_conflict_do_nothing()
    )
    op.execute(exercise_equipment.delete().where(exercise_equipment.c.equipment_id == treadmill))
    op.execute(equipment.delete().where(equipment.c.name == NAME))
