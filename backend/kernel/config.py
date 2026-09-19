from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str
    world_api_token: str = "dev-token"
    hr_webhook_coordinator: str = ""
    watchdog_s: int = 60
    coordinator_cooldown_s: int = 90
    sweep_interval_s: float = 3.0


settings = Settings()
