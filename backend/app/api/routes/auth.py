from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import AuthTokens, DbSession
from app.schemas import AccessTokenResponse, LoginRequest, RegisterRequest
from app.services import AuthService
from app.services.exceptions import (
    InvalidCredentialsError,
    InvalidPasswordError,
    UserAlreadyExistsError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AccessTokenResponse)
def login(login_data: LoginRequest, db: DbSession, tokens: AuthTokens):
    try:
        token = AuthService(db, tokens).login(login_data.email, login_data.password)
    except InvalidCredentialsError as error:
        # one answer for an unknown email, a wrong password and a user without one
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    return AccessTokenResponse(access_token=token)


@router.post(
    "/register", response_model=AccessTokenResponse, status_code=status.HTTP_201_CREATED
)
def register(registration: RegisterRequest, db: DbSession, tokens: AuthTokens):
    """Signs up: creates an account with this email and password and signs it
    in. An email that already has an account is refused, and that account is
    left as it was."""
    try:
        token = AuthService(db, tokens).register(registration.email, registration.password)
    except UserAlreadyExistsError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except InvalidPasswordError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return AccessTokenResponse(access_token=token)
