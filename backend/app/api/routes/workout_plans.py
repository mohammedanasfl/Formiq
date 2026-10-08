from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.api.dependencies import DbSession, PathUserIsCurrentUser, UserId
from app.schemas import (
    WorkoutPlanCreate,
    WorkoutPlanExerciseCreate,
    WorkoutPlanExerciseResponse,
    WorkoutPlanExerciseUpdate,
    WorkoutPlanFilters,
    WorkoutPlanResponse,
    WorkoutPlanUpdate,
)
from app.services import WorkoutPlanExerciseService, WorkoutPlanService
from app.services.exceptions import (
    ExerciseNotFoundError,
    InactiveExerciseError,
    InvalidWorkoutPlanError,
    UserNotFoundError,
    WorkoutPlanConflictError,
    WorkoutPlanExerciseNotFoundError,
    WorkoutPlanNotFoundError,
)

# Each route is scoped to the user in the path, who must be the signed-in user:
# another user's plan is not found.
router = APIRouter(
    prefix="/users/{user_id}/workout-plans",
    tags=["workout plans"],
    dependencies=[PathUserIsCurrentUser],
)

# Like users.id, these are PostgreSQL integer columns: IDs outside their range
# would fail in the database, so they are rejected with 422.
PlanId = Annotated[int, Path(ge=1, le=2_147_483_647)]
PlanExerciseId = Annotated[int, Path(ge=1, le=2_147_483_647)]


@router.post("", response_model=WorkoutPlanResponse, status_code=status.HTTP_201_CREATED)
def create_workout_plan(user_id: UserId, plan_data: WorkoutPlanCreate, db: DbSession):
    try:
        return WorkoutPlanService(db).create_plan(user_id, plan_data)
    except UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (InvalidWorkoutPlanError, ExerciseNotFoundError, InactiveExerciseError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("", response_model=list[WorkoutPlanResponse])
def list_workout_plans(
    user_id: UserId, filters: Annotated[WorkoutPlanFilters, Query()], db: DbSession
):
    try:
        return WorkoutPlanService(db).list_plans(user_id, filters)
    except UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/{plan_id}", response_model=WorkoutPlanResponse)
def get_workout_plan(user_id: UserId, plan_id: PlanId, db: DbSession):
    plan = WorkoutPlanService(db).get_plan(user_id, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"user {user_id} has no workout plan {plan_id}",
        )
    return plan


@router.patch("/{plan_id}", response_model=WorkoutPlanResponse)
def update_workout_plan(
    user_id: UserId, plan_id: PlanId, plan_data: WorkoutPlanUpdate, db: DbSession
):
    try:
        return WorkoutPlanService(db).update_plan(user_id, plan_id, plan_data)
    except WorkoutPlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except InvalidWorkoutPlanError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except WorkoutPlanConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workout_plan(user_id: UserId, plan_id: PlanId, db: DbSession):
    try:
        WorkoutPlanService(db).delete_plan(user_id, plan_id)
    except WorkoutPlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except WorkoutPlanConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/{plan_id}/exercises",
    response_model=WorkoutPlanExerciseResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_workout_plan_exercise(
    user_id: UserId, plan_id: PlanId, exercise_data: WorkoutPlanExerciseCreate, db: DbSession
):
    try:
        return WorkoutPlanExerciseService(db).add_exercise(user_id, plan_id, exercise_data)
    except WorkoutPlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (ExerciseNotFoundError, InactiveExerciseError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except WorkoutPlanConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.patch(
    "/{plan_id}/exercises/{plan_exercise_id}", response_model=WorkoutPlanExerciseResponse
)
def update_workout_plan_exercise(
    user_id: UserId,
    plan_id: PlanId,
    plan_exercise_id: PlanExerciseId,
    exercise_data: WorkoutPlanExerciseUpdate,
    db: DbSession,
):
    try:
        return WorkoutPlanExerciseService(db).update_exercise(
            user_id, plan_id, plan_exercise_id, exercise_data
        )
    except (WorkoutPlanNotFoundError, WorkoutPlanExerciseNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (InvalidWorkoutPlanError, ExerciseNotFoundError, InactiveExerciseError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except WorkoutPlanConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.delete(
    "/{plan_id}/exercises/{plan_exercise_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_workout_plan_exercise(
    user_id: UserId, plan_id: PlanId, plan_exercise_id: PlanExerciseId, db: DbSession
):
    try:
        WorkoutPlanExerciseService(db).remove_exercise(user_id, plan_id, plan_exercise_id)
    except (WorkoutPlanNotFoundError, WorkoutPlanExerciseNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except InvalidWorkoutPlanError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except WorkoutPlanConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
