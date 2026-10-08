from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.api.dependencies import DbSession
from app.schemas import ExerciseFilters, ExerciseResponse
from app.services import ExerciseCatalogService

router = APIRouter(prefix="/exercises", tags=["exercises"])

# exercises.id is a PostgreSQL integer column: IDs outside its range would fail in
# the database, and IDs below 1 are never assigned, so both are rejected with 422.
ExerciseId = Annotated[int, Path(ge=1, le=2_147_483_647)]


@router.get("", response_model=list[ExerciseResponse])
def list_exercises(filters: Annotated[ExerciseFilters, Query()], db: DbSession):
    return ExerciseCatalogService(db).list_exercises(filters)


@router.get("/{exercise_id}", response_model=ExerciseResponse)
def get_exercise(exercise_id: ExerciseId, db: DbSession):
    exercise = ExerciseCatalogService(db).get_exercise_by_id(exercise_id)
    if exercise is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"exercise {exercise_id} does not exist"
        )
    return exercise
