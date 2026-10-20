import pathlib
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.ai import GeminiProvider
from app.approvals import ProposalTerms
from app.core.config import agent_debug_allowed, content_capture_allowed, settings
from app.core.security import AccessTokens
from app.db.database import get_db
from app.models import User
from app.observability import Tracer
from app.observability.debug import DebugSink
from app.observability.langfuse_backend import create_tracer
from app.services import AuthService
from app.services.exceptions import AuthenticationError

# A database session for one request: get_db opens it from SessionLocal and
# closes it after the response.
DbSession = Annotated[Session, Depends(get_db)]


@lru_cache
def get_ai_provider() -> GeminiProvider:
    """The Gemini provider configured by GEMINI_API_KEY, GEMINI_MODEL and
    GEMINI_TIMEOUT_SECONDS, shared by all requests."""
    api_key = settings.gemini_api_key
    return GeminiProvider(
        api_key.get_secret_value() if api_key else None,
        settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds,
    )


AIProvider = Annotated[GeminiProvider, Depends(get_ai_provider)]


@lru_cache
def get_tracer() -> Tracer:
    """The coach's tracer, configured by the LANGFUSE_* settings and shared by all
    requests: Langfuse when enabled and configured, otherwise tracing off.
    Content capture is refused outside development and the tests (ValueError),
    as the settings refuse it, should they have been changed after loading:
    there, the privacy mask always applies."""
    if settings.langfuse_capture_content and not content_capture_allowed(settings.app_env):
        raise ValueError(
            f"LANGFUSE_CAPTURE_CONTENT is for development only, not APP_ENV={settings.app_env!r}"
        )
    secret_key = settings.langfuse_secret_key
    tracer = create_tracer(
        enabled=settings.langfuse_tracing_enabled,
        public_key=settings.langfuse_public_key,
        secret_key=secret_key.get_secret_value() if secret_key else None,
        base_url=settings.langfuse_base_url,
        environment=settings.app_env,
        timeout_seconds=settings.langfuse_timeout,
        capture_content=settings.langfuse_capture_content,
    )
    debug = build_debug_sink()
    if debug is None:
        return tracer
    # The local debug output rides on a tracer of its own (TRACING_OFF is shared):
    # the backend and capture_content are the configured ones, so what Langfuse
    # receives does not depend on it.
    return Tracer(tracer.backend, capture_content=tracer.capture_content, debug=debug)


def debug_secrets() -> list[str]:
    """The secrets the application holds, for the debug output to remove by value
    from anything it shows. Held only by the sink's scrubber, and never printed."""
    secrets = [
        secret.get_secret_value()
        for secret in (settings.gemini_api_key, settings.auth_jwt_secret, settings.langfuse_secret_key)
        if secret is not None
    ]
    if settings.langfuse_public_key:
        secrets.append(settings.langfuse_public_key)
    for url in (settings.database_url, settings.test_database_url):
        try:
            password = urlsplit(url).password if url else None
        except ValueError:
            password = None
        if password:
            secrets.append(password)
    return secrets


def build_debug_sink() -> DebugSink | None:
    """The local debug output AGENT_DEBUG asks for, or None when it is off. Refused
    (ValueError) outside development and test, or with APP_ENV left to its
    default, as the settings refuse it, should they have been changed after loading."""
    level = settings.agent_debug
    if level == "off":
        return None
    if not agent_debug_allowed(settings.app_env, explicit="app_env" in settings.model_fields_set):
        raise ValueError(
            "AGENT_DEBUG is for local development only: APP_ENV must be set to 'development' or 'test'"
        )
    return DebugSink(level, secrets=debug_secrets())


CoachTracer = Annotated[Tracer, Depends(get_tracer)]

# how long a workout plan the coach proposed waits for the user's approval
PROPOSAL_TTL = timedelta(minutes=30)


def utc_now() -> datetime:
    return datetime.now(UTC)


@lru_cache
def get_proposal_terms() -> ProposalTerms:
    """Formiq's clock and how long a proposed workout plan waits for the
    user's approval. The proposals themselves are kept in the database
    (app.services.plan_proposal_service), so they outlive a restart."""
    return ProposalTerms(clock=utc_now, ttl=PROPOSAL_TTL)


Proposals = Annotated[ProposalTerms, Depends(get_proposal_terms)]


def get_exercise_images_dir() -> pathlib.Path:
    """Where the exercise images the API serves are kept (EXERCISE_IMAGES_DIR)."""
    return settings.exercise_images_dir


ExerciseImagesDir = Annotated[pathlib.Path, Depends(get_exercise_images_dir)]


@lru_cache
def get_access_tokens() -> AccessTokens:
    """The access tokens configured by the AUTH_* settings, shared by all
    requests. Without AUTH_JWT_SECRET, every route that needs it answers 503."""
    secret = settings.auth_jwt_secret
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="authentication is not configured",
        )
    return AccessTokens(
        secret.get_secret_value(),
        settings.auth_jwt_algorithm,
        settings.auth_access_token_expire_minutes,
    )


AuthTokens = Annotated[AccessTokens, Depends(get_access_tokens)]

# auto_error=False: a missing or non-Bearer Authorization header gets the same
# 401 as an invalid token, below
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    db: DbSession,
    tokens: AuthTokens,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """The signed-in user: the one the request's Bearer access token was issued
    for. It is the request's only source of who it acts for. Without a valid
    token for an existing user the request ends here with 401, and nothing is
    read for anyone."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        return AuthService(db, tokens).authenticate(credentials.credentials)
    except AuthenticationError as error:
        raise unauthorized from error


CurrentUser = Annotated[User, Depends(get_current_user)]

# users.id is a PostgreSQL integer column: IDs outside its range would fail in the
# database, and IDs below 1 are never assigned, so both are rejected with 422.
UserId = Annotated[int, Path(ge=1, le=2_147_483_647)]


def require_path_user(user_id: UserId, current_user: CurrentUser) -> None:
    """For the routes under /users/{user_id}: the user in the path must be the
    signed-in user. Any other id is not found, whether or not that user exists,
    as another user's resource is."""
    if user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


PathUserIsCurrentUser = Depends(require_path_user)
