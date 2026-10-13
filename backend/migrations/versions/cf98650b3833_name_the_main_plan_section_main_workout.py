"""name the main plan section MAIN_WORKOUT

Revision ID: cf98650b3833
Revises: 14d543e636a8
Create Date: 2026-10-13 18:00:00.000000

A plan exercise's section now has the same values as a catalog exercise's
uses: WARM_UP, MAIN_WORKOUT and COOL_DOWN. The main section was MAIN; the rows
that have it become MAIN_WORKOUT, and so does the column's default. Nothing
else about them changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf98650b3833'
down_revision: Union[str, Sequence[str], None] = '14d543e636a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE workout_plan_exercises SET section = 'MAIN_WORKOUT' WHERE section = 'MAIN'")
    op.alter_column(
        'workout_plan_exercises',
        'section',
        existing_type=sa.String(length=20),
        server_default='MAIN_WORKOUT',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE workout_plan_exercises SET section = 'MAIN' WHERE section = 'MAIN_WORKOUT'")
    op.alter_column(
        'workout_plan_exercises',
        'section',
        existing_type=sa.String(length=20),
        server_default='MAIN',
    )
