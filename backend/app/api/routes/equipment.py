from fastapi import APIRouter

from app.api.dependencies import DbSession
from app.schemas import EquipmentResponse
from app.services import ExerciseCatalogService

router = APIRouter(prefix="/equipment", tags=["equipment"])


@router.get("", response_model=list[EquipmentResponse])
def list_equipment(db: DbSession, is_active: bool = True):
    return ExerciseCatalogService(db).list_equipment(is_active)
