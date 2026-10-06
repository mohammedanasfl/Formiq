from fastapi import APIRouter

from app.api.dependencies import DbSession
from app.schemas import MuscleGroupResponse
from app.services import ExerciseCatalogService

router = APIRouter(prefix="/muscle-groups", tags=["muscle groups"])


@router.get("", response_model=list[MuscleGroupResponse])
def list_muscle_groups(db: DbSession, is_active: bool = True):
    return ExerciseCatalogService(db).list_muscle_groups(is_active)
