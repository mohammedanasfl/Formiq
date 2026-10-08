from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# A signing secret is at least as long as its algorithm's hash (RFC 7518,
# section 3.2): `openssl rand -hex 32` prints 64 characters, enough for all three.
MIN_JWT_SECRET_LENGTH = {"HS256": 32, "HS384": 48, "HS512": 64}


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
    # Access tokens (app.core.security). Without a secret, logging in and every
    # route that needs the signed-in user answer 503: nothing falls back to
    # anonymous access. Only HMAC algorithms are accepted, so a token can never
    # name its own verification ("none", or a public key).
    auth_jwt_secret: SecretStr | None = None
    auth_jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    auth_access_token_expire_minutes: Annotated[int, Field(gt=0, le=1440)] = 30

    @field_validator("auth_jwt_secret")
    @classmethod
    def empty_jwt_secret_is_none(cls, secret: SecretStr | None) -> SecretStr | None:
        return secret if secret and secret.get_secret_value() else None

    @model_validator(mode="after")
    def check_jwt_secret_length(self) -> Self:
        # a short secret is guessable
        minimum = MIN_JWT_SECRET_LENGTH[self.auth_jwt_algorithm]
        if self.auth_jwt_secret and len(self.auth_jwt_secret.get_secret_value()) < minimum:
            raise ValueError(
                f"AUTH_JWT_SECRET must be at least {minimum} characters"
                f" for {self.auth_jwt_algorithm}"
            )
        return self


settings = Settings()
