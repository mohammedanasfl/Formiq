from sqlalchemy import Column, ForeignKey, Table

from app.db.base import Base

# The catalog equipment a user chose for their profile. A profile without rows
# here has chosen none of it: either it said it has none (user_profiles.no_equipment)
# or it never said. The rows belong to the profile: deleting the profile deletes
# them, while equipment that a profile uses cannot be deleted (deactivate it
# instead). equipment_id is indexed for finding the profiles that use a piece of
# equipment; the primary key index starts with user_profile_id.
user_profile_equipment = Table(
    "user_profile_equipment",
    Base.metadata,
    Column("user_profile_id", ForeignKey("user_profiles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "equipment_id",
        ForeignKey("equipment.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    ),
)
