from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str = ""
    supabase_service_role_key: str = ""

    happyrobot_api_key: str = ""
    happyrobot_base_url: str = "https://platform.happyrobot.ai/api/v2"
    ticket_workflow_id: str = ""


settings = Settings()
