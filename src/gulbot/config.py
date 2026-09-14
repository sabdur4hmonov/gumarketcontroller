"""Runtime configuration, loaded from the environment.

Port numbers live here rather than being hardcoded at call sites so that
tests/test_infrastructure.py can assert them in one place.
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Uzbekistan is UTC+5 with no DST, but we resolve it through zoneinfo rather
# than hardcoding an offset -- a fixed +5 is an assumption that rots silently.
TASHKENT = ZoneInfo("Asia/Tashkent")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_user: str = "gulbot"
    # SECRETS ARE SecretStr. Found in the pre-deployment audit, pass 6: pydantic's
    # repr of Settings printed every field, and pytest prints that repr in
    # any failing assertion that touches a Settings object -- which put the
    # real bot token into test output. SecretStr masks repr, str, f-strings,
    # %-formatting and model_dump(); `.get_secret_value()` is the only way
    # out, so every place that reads the value is greppable.
    postgres_password: SecretStr = SecretStr("gulbot")
    postgres_db: str = "gulbot"
    postgres_test_db: str = "gulbot_test"

    redis_host: str = "localhost"
    redis_port: int = 6380
    redis_db_broker: int = 0
    redis_db_results: int = 1
    redis_db_fsm: int = 2
    redis_db_test: int = 15

    bot_token: SecretStr = SecretStr("")
    timezone: str = "Asia/Tashkent"
    environment: str = "local"
    log_level: str = "INFO"

    def database_url(self, *, database: str | None = None, driver: str = "asyncpg") -> str:
        name = database or self.postgres_db
        return (
            f"postgresql+{driver}://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{name}"
        )

    def redis_url(self, db: int) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
