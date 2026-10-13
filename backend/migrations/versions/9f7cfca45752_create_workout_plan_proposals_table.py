"""create workout_plan_proposals table

Revision ID: 9f7cfca45752
Revises: 620eafb9c204
Create Date: 2026-10-13 18:10:00.000000

The workout plans the coach proposes, waiting for the user's approval, were
kept in the memory of one process: a restart or a second worker lost them.
They are now kept here. The proposals made before this revision were in
memory only, so there is nothing to move.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '9f7cfca45752'
down_revision: Union[str, Sequence[str], None] = '620eafb9c204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('workout_plan_proposals',
    sa.Column('proposal_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('binding', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('workout_plan_id', sa.Integer(), nullable=True),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workout_plan_id'], ['workout_plans.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('proposal_id')
    )
    op.create_index(op.f('ix_workout_plan_proposals_user_id'), 'workout_plan_proposals', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema. The proposals waiting for approval are lost: the
    earlier code kept them in memory only."""
    op.drop_index(op.f('ix_workout_plan_proposals_user_id'), table_name='workout_plan_proposals')
    op.drop_table('workout_plan_proposals')
