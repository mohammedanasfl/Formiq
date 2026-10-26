from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/: the default images directory is inside it, wherever the process runs
BACKEND_DIR = Path(__file__).resolve().parents[2]

# A signing secret is at least as long as its algorithm's hash (RFC 7518,
# section 3.2): `openssl rand -hex 32` prints 64 characters, enough for all three.
MIN_JWT_SECRET_LENGTH = {"HS256": 32, "HS384": 48, "HS512": 64}

# The APP_ENV values where Langfuse may receive the coach's content
# (LANGFUSE_CAPTURE_CONTENT): local development and the tests. Any other, such
# as production or a name Formiq does not know, may not.
CONTENT_CAPTURE_ENVIRONMENTS = frozenset({"development", "test"})


def content_capture_allowed(app_env: str | None) -> bool:
    """Whether Langfuse may receive the coach's content where APP_ENV is app_env."""
    return app_env in CONTENT_CAPTURE_ENVIRONMENTS


# The APP_ENV values where AGENT_DEBUG may print the coach's turns to the terminal
# (app.observability.debug): local development and the tests. APP_ENV must also
# be set: its default is "development", which says nothing about where the
# application runs, so a deployment that forgot it never counts as one.
AGENT_DEBUG_ENVIRONMENTS = frozenset({"development", "test"})
AgentDebug = Literal["off", "events", "content"]


def agent_debug_allowed(app_env: str | None, *, explicit: bool) -> bool:
    """Whether AGENT_DEBUG may be on where APP_ENV is app_env, which is explicit
    when the environment or .env gave it (not when its default applies)."""
    return explicit and app_env in AGENT_DEBUG_ENVIRONMENTS


class Settings(BaseSettings):
    # hide_input_in_errors: a failed check of the settings as a whole (the
    # ones below) must not show the other settings, the secrets among them.
    model_config = SettingsConfigDict(env_file=".env", hide_input_in_errors=True)

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
    # The model the opt-in live smoke test uses (tests/integration/
    # test_gemini_live.py); never the application's. Unset: that test is skipped.
    gemini_test_model: str | None = None
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
    # For development only: Langfuse also receives what the coach was asked and
    # answered, each model request's instructions and conversation, and the
    # tools' arguments and results, the users' data included. Off, it receives
    # metadata only (docs/agent-production-contract.md, section 9). On outside
    # CONTENT_CAPTURE_ENVIRONMENTS, the settings are refused.
    langfuse_capture_content: bool = False
    # Local debugging of the coach's turns (app.observability.debug), printed to
    # stderr only: nothing goes to Langfuse, a file or any service, whatever
    # LANGFUSE_CAPTURE_CONTENT says. off: nothing. events: the ordered timeline
    # and safe metadata, no prompt or conversation content. content: also the
    # prompt text, tool declarations and the tool data that is safe to show,
    # with every user, model or profile text reduced to its size and a hash. On
    # outside AGENT_DEBUG_ENVIRONMENTS, or with APP_ENV not set, the settings
    # are refused.
    agent_debug: AgentDebug = "off"
    # Access tokens (app.core.security). Without a secret, logging in and every
    # route that needs the signed-in user answer 503: nothing falls back to
    # anonymous access. Only HMAC algorithms are accepted, so a token can never
    # name its own verification ("none", or a public key).
    auth_jwt_secret: SecretStr | None = None
    auth_jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    auth_access_token_expire_minutes: Annotated[int, Field(gt=0, le=1440)] = 30
    # The exercise images the API serves (backend/data/exercise-images/README.md).
    exercise_images_dir: Path = BACKEND_DIR / "data" / "exercise-images"

    @field_validator("auth_jwt_secret")
    @classmethod
    def empty_jwt_secret_is_none(cls, secret: SecretStr | None) -> SecretStr | None:
        return secret if secret and secret.get_secret_value() else None

    @field_validator("langfuse_capture_content")
    @classmethod
    def capture_content_only_in_development(cls, capture: bool, info: ValidationInfo) -> bool:
        # Refused, not turned off: the application does not start with users'
        # data set to leave for Langfuse. A field's error shows only its own
        # value, never the other settings, the secrets among them.
        app_env = info.data.get("app_env")
        if capture and not content_capture_allowed(app_env):
            raise ValueError(
                "LANGFUSE_CAPTURE_CONTENT sends the users' conversations and data to Langfuse, "
                f"so it is for development only, not APP_ENV={app_env!r}: turn it off, and "
                "tracing records metadata only"
            )
        return capture

    @field_validator("agent_debug", mode="before")
    @classmethod
    def agent_debug_is_case_insensitive(cls, value: object) -> object:
        # AGENT_DEBUG= (empty) or Events: the intent is clear
        return (value.strip().lower() or "off") if isinstance(value, str) else value

    @model_validator(mode="after")
    def agent_debug_only_in_development(self) -> Self:
        # Refused, not turned off: the application does not start with the
        # coach's turns set to be printed. APP_ENV must be set, not defaulted.
        explicit = "app_env" in self.model_fields_set
        if self.agent_debug != "off" and not agent_debug_allowed(self.app_env, explicit=explicit):
            raise ValueError(
                "AGENT_DEBUG prints the coach's turns to the terminal, so it is for local "
                "development only: set APP_ENV to 'development' or 'test' (it is "
                f"{self.app_env!r}{'' if explicit else ', by default, not set'}), or turn it off"
            )
        return self

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
