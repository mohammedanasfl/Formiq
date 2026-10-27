from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Equipment


class EquipmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find(self, *, is_active: bool | None = None) -> list[Equipment]:
        """Equipment ordered by name; only active or inactive items if is_active is given."""
        query = select(Equipment).order_by(Equipment.name)
        if is_active is not None:
            query = query.where(Equipment.is_active == is_active)
        return list(self.session.scalars(query))

    def get_by_ids(self, equipment_ids: Iterable[int]) -> list[Equipment]:
        """The equipment with these ids, active or not, ordered by name; an id
        nothing has is left out."""
        ids = set(equipment_ids)
        if not ids:
            return []
        return list(
            self.session.scalars(
                select(Equipment).where(Equipment.id.in_(ids)).order_by(Equipment.name)
            )
        )
