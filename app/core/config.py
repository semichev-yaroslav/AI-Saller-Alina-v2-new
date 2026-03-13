from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Saller Alina"
    app_env: str = "dev"
    api_prefix: str = ""
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/ai_sales_manager"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_temperature: float = 0.2
    openai_timeout_sec: float = 30.0

    telegram_bot_token: str | None = None
    telegram_admin_chat_id: int | None = None
    telegram_poll_timeout_sec: int = 25
    telegram_poll_interval_sec: float = 1.0

    history_window_messages: int = Field(default=100, ge=10, le=200)
    company_knowledge_dir: str = "knowledge/company"
    company_knowledge_max_files: int = Field(default=12, ge=1, le=50)
    company_knowledge_max_chars: int = Field(default=4000, ge=500, le=20000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
