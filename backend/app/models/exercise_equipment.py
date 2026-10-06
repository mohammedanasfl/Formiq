from sqlalchemy import Column, ForeignKey, Table

from app.db.base import Base

# The equipment an exercise needs. An exercise without rows here needs no
# equipment. The rows belong to the exercise: deleting the exercise deletes
# them, while equipment that an exercise uses cannot be deleted (deactivate it
# instead). equipment_id is indexed for finding the exercises that use a piece
# of equipment; the primary key index starts with exercise_id.
exercise_equipment = Table(
    "exercise_equipment",
    Base.metadata,
    Column("exercise_id", ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "equipment_id",
        ForeignKey("equipment.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    ),
)
