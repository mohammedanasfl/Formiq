from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from fastapi.responses import FileResponse

from app.api.dependencies import DbSession, ExerciseImagesDir
from app.catalog.images import media_type
from app.schemas import ExerciseFilters, ExerciseResponse
from app.services import ExerciseCatalogService

router = APIRouter(prefix="/exercises", tags=["exercises"])

# exercises.id is a PostgreSQL integer column: IDs outside its range would fail in
# the database, and IDs below 1 are never assigned, so both are rejected with 422.
ExerciseId = Annotated[int, Path(ge=1, le=2_147_483_647)]
# an image's place in the exercise's images, 0 first
ImagePosition = Annotated[int, Path(ge=0, le=999)]
# images change only with a new import: clients may keep them for a day
IMAGE_CACHE_CONTROL = "public, max-age=86400"


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


@router.get(
    "/{exercise_id}/images/{position}",
    response_class=FileResponse,
    responses={
        200: {"content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}}},
        404: {"description": "The exercise has no image at this position"},
    },
)
def get_exercise_image(
    exercise_id: ExerciseId, position: ImagePosition, db: DbSession, images_dir: ExerciseImagesDir
):
    """The exercise's image at this position, as its images list gives it. The
    client names the exercise and the position, never a file: a missing
    exercise, position or file is the same 404, which says nothing about where
    images are kept."""
    file = ExerciseCatalogService(db).get_exercise_image(exercise_id, position, images_dir)
    if file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="image not found")
    return FileResponse(
        file, media_type=media_type(file), headers={"Cache-Control": IMAGE_CACHE_CONTROL}
    )
