from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("FOKUSLY_APP_NAME", "Fokusly API")
    app_version: str = os.getenv("FOKUSLY_APP_VERSION", "1.1.0")
    secret_key: str = os.getenv("FOKUSLY_SECRET_KEY", "dev-secret-key-change-me")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./fokusly.db")
    access_token_ttl_minutes: int = int(os.getenv("ACCESS_TOKEN_TTL_MINUTES", "30"))
    refresh_token_ttl_days: int = int(os.getenv("REFRESH_TOKEN_TTL_DAYS", "30"))
    reset_token_ttl_minutes: int = int(os.getenv("RESET_TOKEN_TTL_MINUTES", "30"))
    async_job_delay_seconds: int = int(os.getenv("ASYNC_JOB_DELAY_SECONDS", "1"))
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK", ""))
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    deepseek_timeout_seconds: int = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "30"))


settings = Settings()
