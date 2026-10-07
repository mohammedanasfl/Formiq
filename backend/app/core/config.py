from typing import Annotated

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    app_name: str = "Formiq"
    app_env: str = "development"
    database_url: str
    # Used only by the integration tests; the application uses database_url.
    test_database_url: str | None = None
    # The AI coach's model (Gemini). Without a key the coach endpoint answers 503
    # and the rest of the API works as usual. SecretStr keeps the key out of
    # reprs and logs.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    # How long a Gemini request may take; a slower one fails like any other
    # provider error.
    gemini_timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 30.0
    # Langfuse tracing of the coach (the SDK's own variable names). Off unless
    # enabled and both keys are set; without it the coach works the same.
    langfuse_tracing_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    # seconds the background export may wait on Langfuse; requests never do
    langfuse_timeout: Annotated[int, Field(gt=0)] = 5


settings = Settings()
