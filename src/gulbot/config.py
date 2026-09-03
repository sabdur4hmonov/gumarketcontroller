"""Runtime configuration, loaded from the environment.

Port numbers live here rather than being hardcoded at call sites so that
tests/test_infrastructure.py can assert them in one place.
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

# Uzbekistan is UTC+5 with no DST, but we resolve it through zoneinfo rather
# than hardcoding an offset -- a fixed +5 is an assumption that rots silently.
TASHKENT = ZoneInfo("Asia/Tashkent")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_user: str = "gulbot"
    postgres_password: str = "gulbot"
    postgres_db: str = "gulbot"
    postgres_test_db: str = "gulbot_test"

    redis_host: str = "localhost"
    redis_port: int = 6380
    redis_db_broker: int = 0
    redis_db_results: int = 1
    redis_db_fsm: int = 2
    redis_db_test: int = 15

    bot_token: str = ""
    timezone: str = "Asia/Tashkent"
    environment: str = "local"
    log_level: str = "INFO"

    def database_url(self, *, database: str | None = None, driver: str = "asyncpg") -> str:
        name = database or self.postgres_db
        return (
            f"postgresql+{driver}://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{name}"
        )

    def redis_url(self, db: int) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
