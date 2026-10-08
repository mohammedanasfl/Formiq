from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import AuthTokens, DbSession
from app.schemas import AccessTokenResponse, LoginRequest
from app.services import AuthService
from app.services.exceptions import InvalidCredentialsError

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
