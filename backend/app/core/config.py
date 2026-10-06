from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    app_name: str = "Formiq"
    app_env: str = "development"
    database_url: str


settings = Settings()
