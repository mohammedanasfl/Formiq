from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import DbSession, PathUserIsCurrentUser, UserId
from app.schemas import (
    UserCreate,
    UserProfileCreate,
    UserProfileResponse,
    UserProfileUpdate,
    UserResponse,
)
from app.services import UserProfileService, UserService
from app.services.exceptions import (
    InvalidProfileUpdateError,
    InvalidUserError,
    UserAlreadyExistsError,
    UserNotFoundError,
    UserProfileAlreadyExistsError,
    UserProfileNotFoundError,
)

router = APIRouter(prefix="/users", tags=["users"])

# Every route with a user_id is the signed-in user's own: any other id is not
# found. Creating a user needs no sign-in, and gives no way to sign in.
OWN = [PathUserIsCurrentUser]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user_data: UserCreate, db: DbSession):
    try:
        return UserService(db).create_user(user_data)
    except UserAlreadyExistsError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except InvalidUserError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/{user_id}", response_model=UserResponse, dependencies=OWN)
def get_user(user_id: UserId, db: DbSession):
    user = UserService(db).get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"user {user_id} does not exist"
        )
    return user


@router.post(
    "/{user_id}/profile",
    response_model=UserProfileResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=OWN,
)
def create_profile(user_id: UserId, profile_data: UserProfileCreate, db: DbSession):
    try:
        return UserProfileService(db).create_profile(user_id, profile_data)
    except UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except UserProfileAlreadyExistsError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("/{user_id}/profile", response_model=UserProfileResponse, dependencies=OWN)
def get_profile(user_id: UserId, db: DbSession):
    profile = UserProfileService(db).get_profile_by_user_id(user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no profile found for user {user_id}"
        )
    return profile


@router.patch("/{user_id}/profile", response_model=UserProfileResponse, dependencies=OWN)
def update_profile(user_id: UserId, profile_data: UserProfileUpdate, db: DbSession):
    try:
        return UserProfileService(db).update_profile(user_id, profile_data)
    except UserProfileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except InvalidProfileUpdateError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
