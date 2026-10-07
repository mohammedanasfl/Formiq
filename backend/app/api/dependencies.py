from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.ai import GeminiProvider
from app.core.config import settings
from app.db.database import get_db

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
