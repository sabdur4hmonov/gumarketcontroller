"""Runtime configuration, loaded from the environment.

Port numbers live here rather than being hardcoded at call sites so that
tests/test_infrastructure.py can assert them in one place.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Mapping
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Uzbekistan is UTC+5 with no DST, but we resolve it through zoneinfo rather
# than hardcoding an offset -- a fixed +5 is an assumption that rots silently.
TASHKENT = ZoneInfo("Asia/Tashkent")

#: Settings.brand_name bounds: HTML-special and format-special characters.
BRAND_FORBIDDEN = frozenset("<>&{}")
BRAND_MAX = 40


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
    postgres_pool_size: int = Field(default=5, ge=1, le=100)
    postgres_pool_overflow: int = Field(default=10, ge=0, le=100)
    postgres_task_pool_size: int = Field(default=1, ge=1, le=20)

    redis_host: str = "localhost"
    redis_port: int = 6380
    redis_db_broker: int = 0
    redis_db_results: int = 1
    redis_db_fsm: int = 2
    redis_db_test: int = 15

    bot_token: SecretStr = SecretStr("")
    #: Fernet key(s) for shops.bot_token_encrypted; comma-separated to rotate
    #: (first encrypts, all decrypt). Read only by gulbot.services.shop_tokens.
    shop_token_encryption_key: SecretStr = SecretStr("")
    #: The PLATFORM bot, where shop owners onboard (bot/routers/shop_onboarding.py).
    #: Not any shop's bot. Empty = onboarding is off; the process still serves
    #: every shop it has.
    platform_bot_token: SecretStr = SecretStr("")
    #: Telegram ids allowed into the platform admin panel (CP18), comma- or
    #: space-separated. Read only through gulbot.services.admin_auth.admin_ids;
    #: anything unparsable empties the whole list. Required in production.
    platform_admin_telegram_ids: str = ""
    #: Where the public Ha/Yo'q and taklifnoma pages are served, as an ORIGIN
    #: (scheme://host[:port], no path). The bot builds every link on it. In
    #: production the bot offers pages only once this is https -- see
    #: gulbot.web.links and docs/DEPLOY.md, "Public pages".
    public_base_url: str = "http://127.0.0.1:8088"
    web_host: str = "127.0.0.1"
    web_port: int = 8088
    #: Behind a reverse proxy, read the client address from X-Forwarded-For
    #: (rate limits). Never on when the service faces the internet directly.
    web_trust_proxy: bool = False
    timezone: str = "Asia/Tashkent"
    environment: str = "local"
    #: LOCAL TESTING ONLY. On, the share-page creation limits, the premium gate
    #: and the public pages' rate limits are bypassed so every design can be
    #: tried. Read only through unlimited_pages_active(), which is False in
    #: production whatever this says; production refuses to start with it on.
    dev_unlimited_pages: bool = False
    log_level: str = "INFO"
    #: The product's name wherever a person reads it (CP19). The brand is not
    #: decided; this is the ONE place it is written. Read it through
    #: gulbot.brand.brand_name(); tests/test_brand.py fails the build if it is
    #: typed anywhere else.
    brand_name: str = "Gulbot"

    stt_engine: str = "faster-whisper"
    stt_model_path: str = ""
    stt_cpu_threads: int = 2
    stt_audio_dir: str = tempfile.gettempdir() + "/gulbot-stt"
    stt_gemini_enabled: bool = False
    gemini_api_key: SecretStr = SecretStr("")
    stt_gemini_model: str = ""

    #: CP23 phase 3: publishing story images to a shop's Instagram BUSINESS
    #: account through Meta's official API. OFF until the owner has a Meta app
    #: with content publishing approved (docs/DEPLOY.md, "Instagram"); off,
    #: the bot offers only the downloadable story image.
    instagram_publishing_enabled: bool = False
    instagram_app_id: str = ""
    instagram_app_secret: SecretStr = SecretStr("")
    #: Overridable for the tests' fake Graph server; never in production.
    instagram_graph_url: str = "https://graph.instagram.com"
    instagram_oauth_url: str = "https://api.instagram.com"
    instagram_authorize_url: str = "https://www.instagram.com/oauth/authorize"
    instagram_graph_version: str = "v21.0"

    @field_validator("brand_name")
    @classmethod
    def _brand_fits_every_surface(cls, value: str) -> str:
        """Bot messages are Telegram HTML, catalog strings are str.format'ed, and
        the name sits in a page title: refuse what would break any of them."""
        value = value.strip()
        if not value:
            raise ValueError("brand_name is empty")
        if len(value) > BRAND_MAX:
            raise ValueError(f"brand_name is longer than {BRAND_MAX} characters")
        if BRAND_FORBIDDEN & set(value):
            forbidden = "".join(sorted(BRAND_FORBIDDEN))
            raise ValueError(f"brand_name may not contain any of {forbidden}")
        return value

    def database_url(self, *, database: str | None = None, driver: str = "asyncpg") -> str:
        name = database or self.postgres_db
        return (
            f"postgresql+{driver}://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{name}"
        )

    def redis_url(self, db: int) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{db}"


# --- the production guard ----------------------------------------------------
#
# THE MOST IMPORTANT CHECK IN THE PRE-DEPLOYMENT AUDIT, and the simplest. Every
# other finding protects against something rare or subtle. This protects against
# a deploy that forgets one environment variable: pydantic-settings then quietly
# falls back to whatever `.env` sits in the working directory, and after that to
# the built-in defaults -- which ARE the dev setup. The pilot's real customers
# would flow through the dev bot token or into the dev database, and nothing
# anywhere would say so. Reproduced in audit pass 6 before this existed.
#
# So in production the four settings that decide WHERE traffic goes must be
# REAL environment variables, and the password must not be the dev one. Anything
# else is refused at process start with an exception, never a warning: a warning
# is a line that scrolls past, and the failure it warns about is silent.

#: The ENVIRONMENT value that arms the guard. Compared after strip() and
#: lower(), so " Production" arms it too rather than quietly not matching.
PRODUCTION = "production"

#: Must each come from a real, non-empty environment variable in production.
#: Together they decide which bot answers and which database is written. A value
#: from `.env` or from a default is refused even if it happens to be correct --
#: the point is that nobody chose it for this deploy.
PRODUCTION_REQUIRED_ENV = (
    "BOT_TOKEN",
    "POSTGRES_HOST",
    "POSTGRES_DB",
    "POSTGRES_PASSWORD",
)

#: The dev password, shipped as the default and in docker-compose.yml.
DEV_DEFAULT_PASSWORD = "gulbot"


def parse_admin_ids(raw: str) -> frozenset[int]:
    """PLATFORM_ADMIN_TELEGRAM_IDS as a set of ids. Anything unparsable, or a
    non-positive id, makes the WHOLE list empty: a typo must lock everyone
    out, never let a wrong id in."""
    try:
        ids = frozenset(int(part) for part in raw.replace(",", " ").split())
    except ValueError:
        return frozenset()
    return ids if all(i > 0 for i in ids) else frozenset()


class ProductionConfigError(RuntimeError):
    """Raised at startup when a production process has non-production config.

    Deliberately not caught anywhere. The process must die with this message.
    """


def production_config_problems(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> list[str]:
    """Every reason this configuration must not run in production. Names only.

    The messages never contain a value -- a refusal that printed the token it was
    refusing would be a leak of its own.
    """
    if settings.environment.strip().lower() != PRODUCTION:
        return []
    env = os.environ if environ is None else environ
    # Names compared case-insensitively, as pydantic-settings reads them.
    real = {key.upper(): value for key, value in env.items()}
    problems = [
        f"{name} is not set as a real, non-empty environment variable "
        f"(a value from .env or the built-in default is refused in production)"
        for name in PRODUCTION_REQUIRED_ENV
        if not real.get(name, "").strip()
    ]
    if settings.postgres_password.get_secret_value() == DEV_DEFAULT_PASSWORD:
        problems.append("POSTGRES_PASSWORD is the dev default password")
    if settings.dev_unlimited_pages:
        problems.append("DEV_UNLIMITED_PAGES is on (a local-testing switch; never in production)")
    # CP18: a production panel nobody can log into is a panel nobody watches,
    # and a typo in the list must be loud, not a silent lock-out.
    if not parse_admin_ids(settings.platform_admin_telegram_ids):
        problems.append(
            "PLATFORM_ADMIN_TELEGRAM_IDS is empty or not a list of Telegram ids "
            "(nobody could log into the admin panel)"
        )
    # CP23: Instagram publishing switched on must be able to work, and Meta
    # must reach the story image over https.
    if settings.instagram_publishing_enabled:
        if not settings.instagram_app_id.strip():
            problems.append("INSTAGRAM_PUBLISHING_ENABLED is on but INSTAGRAM_APP_ID is empty")
        if not settings.instagram_app_secret.get_secret_value().strip():
            problems.append("INSTAGRAM_PUBLISHING_ENABLED is on but INSTAGRAM_APP_SECRET is empty")
        if not settings.public_base_url.startswith("https://"):
            problems.append(
                "INSTAGRAM_PUBLISHING_ENABLED is on but PUBLIC_BASE_URL is not https "
                "(Meta fetches the story image from it)"
            )
        for name in ("graph", "oauth", "authorize"):
            if not getattr(settings, f"instagram_{name}_url").startswith("https://"):
                problems.append(f"INSTAGRAM_{name.upper()}_URL is not https")
    return problems


def check_production_config(settings: Settings, environ: Mapping[str, str] | None = None) -> None:
    """Raise ProductionConfigError listing EVERY problem at once."""
    problems = production_config_problems(settings, environ)
    if problems:
        raise ProductionConfigError(
            "REFUSING TO START: ENVIRONMENT=production, but this is not a production "
            "configuration.\n"
            + "\n".join(f"  - {problem}" for problem in problems)
            + "\nSet each of these as a real environment variable for this process. "
            "See docs/DEPLOY.md."
        )


UNLIMITED_PAGES_WARNING = (
    "DEV_UNLIMITED_PAGES is ON: page limits, premium gate and web rate limits are "
    "bypassed (local only)"
)


def unlimited_pages_active(settings: Settings | None = None) -> bool:
    """THE ONE CHECK every DEV_UNLIMITED_PAGES bypass goes through.

    False in production even if the flag is somehow on: the startup guard
    refuses that configuration, and this does not rely on the guard having run.
    """
    settings = get_settings() if settings is None else settings
    return settings.dev_unlimited_pages and settings.environment.strip().lower() != PRODUCTION


def warn_if_unlimited_pages(logger: logging.Logger) -> None:
    """One WARNING at process start (bot, web, worker) while the switch is on."""
    if unlimited_pages_active():
        logger.warning(UNLIMITED_PAGES_WARNING)


@lru_cache
def get_settings() -> Settings:
    """The ONLY place the application builds its Settings.

    The guard lives here rather than in each entrypoint so that it cannot be
    forgotten by one: the bot, the Celery worker and beat, migrations, the seed
    CLI and the scripts all get their configuration through this call, and all
    of them call it before touching the network or the database.
    """
    settings = Settings()
    check_production_config(settings)
    return settings
