from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://chiefly:chiefly@localhost:5433/chiefly"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    google_credentials_file: str = "/app/credentials/google_credentials.json"
    google_tasks_default_tasklist_id: str = ""

    # Backward-compatible alias: reads GOOGLE_TASKS_INBOX_LIST_ID env var
    google_tasks_inbox_list_id: str = ""

    @property
    def default_tasklist_id(self) -> str:
        """Canonical accessor. Prefers new name, falls back to legacy."""
        return self.google_tasks_default_tasklist_id or self.google_tasks_inbox_list_id

    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    llm_api_key: str = ""
    llm_base_url: str = ""

    # Multi-model support: when llm_auto_mode is True, different pipeline
    # steps can use different models (fast for normalize, quality for classify).
    # When False (default), all steps use llm_model — zero behavior change.
    llm_fast_model: str = ""
    llm_quality_model: str = ""
    llm_fallback_model: str = ""
    llm_auto_mode: bool = False

    sync_interval_seconds: int = 60

    # Backward-compatible aliases
    sync_poll_interval_seconds: int | None = None
    inbox_poll_interval_seconds: int | None = None

    @property
    def effective_sync_interval(self) -> int:
        if self.inbox_poll_interval_seconds is not None:
            return self.inbox_poll_interval_seconds
        if self.sync_poll_interval_seconds is not None:
            return self.sync_poll_interval_seconds
        return self.sync_interval_seconds

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
