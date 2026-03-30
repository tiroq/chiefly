from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://chiefly:chiefly@localhost:5433/chiefly"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    google_credentials_file: str = "/app/credentials/google_credentials.json"
    google_tasks_inbox_list_id: str = ""

    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    llm_api_key: str = ""
    llm_base_url: str = ""

    sync_poll_interval_seconds: int = 60
    inbox_poll_interval_seconds: int | None = None

    @property
    def effective_sync_interval(self) -> int:
        if self.inbox_poll_interval_seconds is not None:
            return self.inbox_poll_interval_seconds
        return self.sync_poll_interval_seconds

    processing_interval_seconds: int = 10
    daily_review_cron: str = "0 9 * * *"
    project_sync_cron: str = "0 * * * *"
    timezone: str = "UTC"

    admin_token: str = "admin"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
