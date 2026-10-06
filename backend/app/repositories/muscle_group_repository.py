from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MuscleGroup


class MuscleGroupRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find(self, *, is_active: bool | None = None) -> list[MuscleGroup]:
        """Muscle groups ordered by name; only active or inactive ones if is_active is given."""
        query = select(MuscleGroup).order_by(MuscleGroup.name)
        if is_active is not None:
            query = query.where(MuscleGroup.is_active == is_active)
        return list(self.session.scalars(query))
