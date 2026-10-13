"""add workout plan exercise sections

Revision ID: c062e4afd0b0
Revises: c3a1f2d9e8b7
Create Date: 2026-10-13 12:00:00.000000

A plan's exercises now belong to a section (WARM_UP, MAIN or COOL_DOWN), and a
set's target may be a duration instead of reps, for timed warm-up and cool-down
activities. Existing plan exercises become MAIN and keep their reps: nothing
else about them changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c062e4afd0b0'
down_revision: Union[str, Sequence[str], None] = 'c3a1f2d9e8b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'workout_plan_exercises',
        sa.Column('section', sa.String(length=20), server_default='MAIN', nullable=False),
    )
    op.add_column(
        'workout_plan_exercises', sa.Column('duration_seconds', sa.Integer(), nullable=True)
    )
    op.alter_column('workout_plan_exercises', 'reps', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Downgrade schema. The earlier schema has no sections and needs reps: a
    warm-up or cool-down exercise, or a timed one, would lose its meaning in
    it, so the downgrade then fails instead of changing those plans."""
    sectioned = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM workout_plan_exercises "
            "WHERE section <> 'MAIN' OR reps IS NULL OR duration_seconds IS NOT NULL)"
        )
    )
    if sectioned:
        raise RuntimeError(
            "workout plans have warm-up, cool-down or timed exercises, which the earlier "
            "schema cannot hold; remove them before downgrading"
        )
    op.alter_column('workout_plan_exercises', 'reps', existing_type=sa.Integer(), nullable=False)
    op.drop_column('workout_plan_exercises', 'duration_seconds')
    op.drop_column('workout_plan_exercises', 'section')
