from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.ai import GeminiProvider
from app.core.config import settings
from app.db.database import get_db
from app.observability import Tracer
from app.observability.langfuse_backend import create_tracer

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
    requests: Langfuse when enabled and configured, otherwise tracing off."""
    secret_key = settings.langfuse_secret_key
    return create_tracer(
        enabled=settings.langfuse_tracing_enabled,
        public_key=settings.langfuse_public_key,
        secret_key=secret_key.get_secret_value() if secret_key else None,
        base_url=settings.langfuse_base_url,
        environment=settings.app_env,
        timeout_seconds=settings.langfuse_timeout,
    )


CoachTracer = Annotated[Tracer, Depends(get_tracer)]
