from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    app_name: str = "Formiq"
    app_env: str = "development"
    database_url: str
    # Used only by the integration tests; the application uses database_url.
    test_database_url: str | None = None


settings = Settings()
