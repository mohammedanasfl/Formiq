"""add the equipment a user has to their profile

Revision ID: e5b3a96c1f48
Revises: c9e24b7a5d13
Create Date: 2026-10-27 10:00:00.000000

user_profile_equipment holds the catalog equipment a user chose, and
user_profiles.no_equipment says they chose none (bodyweight only). A profile with
neither has not said: every profile made before this migration, whose users were
never asked, is one. No row is invented for them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5b3a96c1f48'
down_revision: Union[str, Sequence[str], None] = 'c9e24b7a5d13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user_profiles', sa.Column('no_equipment', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_table('user_profile_equipment',
    sa.Column('user_profile_id', sa.Integer(), nullable=False),
    sa.Column('equipment_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_profile_id'], ['user_profiles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_profile_id', 'equipment_id')
    )
    op.create_index(op.f('ix_user_profile_equipment_equipment_id'), 'user_profile_equipment', ['equipment_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_user_profile_equipment_equipment_id'), table_name='user_profile_equipment')
    op.drop_table('user_profile_equipment')
    op.drop_column('user_profiles', 'no_equipment')
