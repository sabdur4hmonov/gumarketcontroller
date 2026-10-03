"""Each shop's bot token: encrypted on the way in, decrypted on the way out.

A bot token is the whole of a shop's Telegram identity -- whoever holds it
reads that shop's customers' messages and speaks as the shop -- so the
database only ever holds Fernet ciphertext (`shops.bot_token_encrypted`), and
the key lives in SHOP_TOKEN_ENCRYPTION_KEY and nowhere else.

THE ONLY MODULE THAT TOUCHES THE PLAINTEXT OR THE KEY. Everything else asks
here, so every place a token can be handled is in one file.

NO SECRET IN ANY MESSAGE. Every error raised here says what is wrong and which
setting or column to look at, and never carries the token, the ciphertext or
the key: these messages end up in logs, in Celery's failure output and in
tracebacks. The cryptography library's own exceptions are replaced rather
than chained, so there is nothing underneath to print either.

KEY ROTATION. SHOP_TOKEN_ENCRYPTION_KEY may hold several comma-separated keys:
the FIRST encrypts, ALL decrypt (Fernet's MultiFernet). Rotating is: put the
new key first, re-encrypt, then drop the old one.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.config import get_settings
from gulbot.models.shop import Shop

KEY_ENV = "SHOP_TOKEN_ENCRYPTION_KEY"

#: Telegram's token shape: the bot's numeric id, a colon, then the secret.
#: Stricter than aiogram's own check on purpose -- it admits only characters
#: that are safe inside the request URL, so a stored token can never produce a
#: malformed URL, whose error text would contain the token.
TOKEN_SHAPE = re.compile(r"\d{1,20}:[A-Za-z0-9_-]{30,64}")


class TokenCipherError(RuntimeError):
    """Base for everything here. Messages never carry a secret."""


class EncryptionKeyMissing(TokenCipherError):
    def __init__(self) -> None:
        super().__init__(f"{KEY_ENV} is not set, so no shop's bot token can be encrypted or read")


class EncryptionKeyInvalid(TokenCipherError):
    def __init__(self) -> None:
        super().__init__(
            f"{KEY_ENV} is not a valid Fernet key (32 url-safe base64-encoded bytes; "
            "several may be comma-separated)"
        )


class TokenUndecryptable(TokenCipherError):
    def __init__(self) -> None:
        super().__init__(
            f"the stored bot token cannot be decrypted with {KEY_ENV}: the key has "
            "changed or the stored value is damaged"
        )


class InvalidBotToken(ValueError):
    """Refused at WRITE time. The value itself is never repeated."""

    def __init__(self) -> None:
        super().__init__(
            "that is not a Telegram bot token (expected '<digits>:<30-64 letters, digits, - or _>')"
        )


def _cipher() -> MultiFernet:
    configured = get_settings().shop_token_encryption_key.get_secret_value()
    keys = [key.strip() for key in configured.split(",") if key.strip()]
    if not keys:
        raise EncryptionKeyMissing
    try:
        return MultiFernet([Fernet(key) for key in keys])
    except (ValueError, TypeError):
        raise EncryptionKeyInvalid from None


def cipher_ready() -> None:
    """Raise TokenCipherError unless SHOP_TOKEN_ENCRYPTION_KEY can encrypt.

    For a process to check at START, rather than at the first owner who needs
    it -- the platform bot refuses to start without it.
    """
    _cipher()


def is_token_shaped(token: object) -> bool:
    """The FORMAT check -- no Telegram call. What onboarding accepts a paste on."""
    return isinstance(token, str) and TOKEN_SHAPE.fullmatch(token) is not None


def bot_id_of(token: str) -> int:
    """The bot's numeric id: the public half of its token, before the colon.

    Not secret -- it is the id every user of the bot can see -- which is why
    it may be stored in the clear and made UNIQUE, while the rest may not.
    """
    if not is_token_shaped(token):
        raise InvalidBotToken
    return int(token.split(":", 1)[0])


def encrypt_token(token: str) -> str:
    """The stored form of `token`. Refuses anything not shaped like a token."""
    if not is_token_shaped(token):
        raise InvalidBotToken
    return _cipher().encrypt(token.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    cipher = _cipher()
    try:
        return cipher.decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        raise TokenUndecryptable from None


async def set_shop_bot_token(session: AsyncSession, *, shop_id: int, token: str) -> None:
    """Store `token` for one shop, encrypted. Raises LookupError for no such shop.

    Storage only. How an owner hands a token over is
    gulbot.bot.routers.shop_onboarding.

    Records the bot's public id beside it, in `shops.bot_telegram_id`, whose
    UNIQUE constraint is what stops two shops holding one bot. A second shop
    storing an already-registered bot fails here with IntegrityError.
    """
    stored = await session.scalar(
        update(Shop)
        .where(Shop.id == shop_id)
        .values(bot_token_encrypted=encrypt_token(token), bot_telegram_id=bot_id_of(token))
        .returning(Shop.id)
    )
    if stored is None:
        raise LookupError(f"no shop with id={shop_id}; no bot token was stored")
    await session.flush()


@dataclass(frozen=True)
class ShopBotCredential:
    """What a registry needs to decide which bot speaks for a shop.

    The ciphertext is excluded from repr: not secret without the key, but
    there is no reason for it to reach a log either.
    """

    shop_id: int
    token_encrypted: str | None = field(repr=False)
    uses_process_bot_token: bool


async def load_bot_credentials(
    session: AsyncSession, *, shop_ids: Collection[int] | None = None
) -> dict[int, ShopBotCredential]:
    """Every shop's credential (or just `shop_ids`'), still encrypted.

    Loaded as ciphertext and decrypted only when a bot is actually built, so a
    tick that sends for three shops decrypts three tokens, not a thousand.
    """
    query = select(Shop.id, Shop.bot_token_encrypted, Shop.uses_process_bot_token)
    if shop_ids is not None:
        query = query.where(Shop.id.in_(list(shop_ids)))
    rows = await session.execute(query)
    return {
        int(shop_id): ShopBotCredential(
            shop_id=int(shop_id),
            token_encrypted=token_encrypted,
            uses_process_bot_token=bool(legacy),
        )
        for shop_id, token_encrypted, legacy in rows
    }
