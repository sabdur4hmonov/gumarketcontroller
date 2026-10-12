"""CP23 phase 3: publishing a story to a shop's Instagram BUSINESS account.

BUILT, AND OFF BY DEFAULT. Nothing here runs unless
settings.instagram_publishing_enabled is on AND the Meta app id and secret are
set (the production guard refuses the half-configured case). Off, the bot
offers the downloadable story image of phase 2 and nothing else.

CONNECTING (the shop owner, from /shop/instagram): a one-time `state`
(hashed, 10 minutes, bound to the shop and the owner who started it) goes to
Instagram's login; the redirect back to /ig/callback is accepted once, the
code is exchanged for a long-lived token, which is stored ENCRYPTED with the
key and module bot tokens use (shop_tokens). Disconnecting deletes it.

PUBLISHING (the post's author, from the bot): the rendered story is stored
for Meta to fetch at an UNGUESSABLE https URL of our page server (32 random
bytes; only its hash is stored), valid 15 minutes, wiped as soon as the
attempt ends either way. A worker task creates a STORIES container with
that image_url, polls it, publishes it, and tells the author the outcome in
the shop's language. Limits: Meta's own content_publishing_limit is asked
first, and a shop may queue at most DAILY_CAP stories a day.

TOKENS ARE NEVER LOGGED OR SHOWN: errors carry codes (instagram_graph).
A token Meta calls invalid marks the connection expired, so nothing keeps
retrying it; the owner is told to reconnect. A daily task refreshes tokens
nearing their 60-day end.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import any_, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.config import get_settings
from gulbot.models.instagram import InstagramConnection, InstagramOAuthState, InstagramStoryUpload
from gulbot.models.shop import Shop
from gulbot.services.instagram_graph import Graph, GraphConfig, GraphError, authorize_link
from gulbot.services.shop_tokens import decrypt_access_token, encrypt_access_token

STATE_TTL = timedelta(minutes=10)
UPLOAD_TTL = timedelta(minutes=15)
REFRESH_BEFORE = timedelta(days=15)
DAILY_CAP = 25
POLL_ATTEMPTS = 12
POLL_SECONDS = 5.0
TOKEN_BYTES = 32

#: What the owner reads, by outcome code, in the shop's language.
MESSAGES: dict[str, dict[str, str]] = {
    "published": {
        "uz": "✅ Istoriya Instagram'ga joylandi.",
        "ru": "✅ История опубликована в Instagram.",
        "en": "✅ The story is published on Instagram.",
    },
    "queued": {
        "uz": "📲 Instagram'ga yuborildi. Natijasini shu yerda xabar qilaman.",
        "ru": "📲 Отправлено в Instagram. Сообщу результат здесь.",
        "en": "📲 Sent to Instagram. I will report the result here.",
    },
    "off": {
        "uz": "Instagram'ga avtomatik joylash o'chirilgan. Rasmni yuklab olib, o'zingiz joylang.",
        "ru": "Автопубликация в Instagram выключена. Скачайте изображение и опубликуйте сами.",
        "en": "Instagram auto-publishing is off. Download the image and post it yourself.",
    },
    "not_connected": {
        "uz": "Do'kon Instagram akkaunti ulanmagan. Uni /shop panelida ulang.",
        "ru": "Instagram-аккаунт магазина не подключён. Подключите его в панели /shop.",
        "en": "The shop's Instagram account is not connected. Connect it in the /shop panel.",
    },
    "token_invalid": {
        "uz": "Instagram ulanishi eskirgan. Uni /shop panelida qayta ulang.",
        "ru": "Подключение Instagram устарело. Переподключите его в панели /shop.",
        "en": "The Instagram connection has expired. Reconnect it in the /shop panel.",
    },
    "daily_cap": {
        "uz": "Bugun juda ko'p istoriya yuborildi. Ertaga urinib ko'ring.",
        "ru": "Сегодня отправлено слишком много историй. Попробуйте завтра.",
        "en": "Too many stories were sent today. Try again tomorrow.",
    },
    "quota": {
        "uz": "Instagram kunlik joylash chegarasiga yetildi. Keyinroq urinib ko'ring.",
        "ru": "Достигнут дневной лимит публикаций Instagram. Попробуйте позже.",
        "en": "Instagram's daily publishing limit is reached. Try again later.",
    },
    "rate_limited": {
        "uz": "Instagram so'rovlarni vaqtincha cheklayapti. Birozdan so'ng urinib ko'ring.",
        "ru": "Instagram временно ограничивает запросы. Попробуйте чуть позже.",
        "en": "Instagram is limiting requests for now. Try again a little later.",
    },
    "container_failed": {
        "uz": "Instagram rasmni qabul qilmadi. Boshqa ko'rinishni tanlab, qayta urinib ko'ring.",
        "ru": "Instagram не принял изображение. Выберите другой вид и попробуйте снова.",
        "en": "Instagram did not accept the image. Pick another layout and try again.",
    },
    "timeout": {
        "uz": "Instagram javob bermadi. Istoriya joylanmadi; keyinroq qayta urinib ko'ring.",
        "ru": "Instagram не ответил. История не опубликована; попробуйте позже.",
        "en": "Instagram did not answer. The story was not published; try again later.",
    },
    "graph": {
        "uz": "Instagram xato qaytardi. Istoriya joylanmadi.",
        "ru": "Instagram вернул ошибку. История не опубликована.",
        "en": "Instagram returned an error. The story was not published.",
    },
}
# Transport failures read like a non-answer; a malformed answer like an error.
MESSAGES["network"] = MESSAGES["timeout"]
MESSAGES["bad_response"] = MESSAGES["graph"]


class InstagramRefused(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def message(code: str, lang: str) -> str:
    texts = MESSAGES.get(code, MESSAGES["graph"])
    return texts.get(lang, texts["uz"])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def enabled() -> bool:
    settings = get_settings()
    return bool(
        settings.instagram_publishing_enabled
        and settings.instagram_app_id.strip()
        and settings.instagram_app_secret.get_secret_value().strip()
    )


def graph_config() -> GraphConfig:
    settings = get_settings()
    return GraphConfig(
        app_id=settings.instagram_app_id,
        app_secret=settings.instagram_app_secret.get_secret_value(),
        graph_url=settings.instagram_graph_url.rstrip("/"),
        oauth_url=settings.instagram_oauth_url.rstrip("/"),
        authorize_url=settings.instagram_authorize_url,
        version=settings.instagram_graph_version,
    )


def redirect_uri() -> str:
    return f"{get_settings().public_base_url}/ig/callback"


def image_url(token: str) -> str:
    return f"{get_settings().public_base_url}/ig/{token}.jpg"


def _require_enabled() -> None:
    if not enabled():
        raise InstagramRefused("off")


async def _is_owner(session: AsyncSession, *, shop_id: int, owner_id: int) -> bool:
    found = await session.scalar(
        select(Shop.id).where(
            Shop.id == shop_id, literal(owner_id) == any_(Shop.owner_telegram_ids)
        )
    )
    return found is not None


# --- connecting ---------------------------------------------------------------------


async def start_connect(session: AsyncSession, *, shop_id: int, owner_id: int) -> str:
    """The Instagram login link for this shop, with a fresh one-time state."""
    _require_enabled()
    if owner_id <= 0 or not await _is_owner(session, shop_id=shop_id, owner_id=owner_id):
        raise InstagramRefused("not_owner")
    state = secrets.token_urlsafe(TOKEN_BYTES)
    session.add(
        InstagramOAuthState(
            token_hash=_hash(state),
            shop_id=shop_id,
            owner_id=owner_id,
            expires_at=datetime.now(UTC) + STATE_TTL,
        )
    )
    await session.flush()
    return authorize_link(graph_config(), redirect_uri=redirect_uri(), state=state)


async def complete_connect(
    session: AsyncSession, graph: Graph, *, state: str, code: str
) -> InstagramConnection:
    """The redirect back from Instagram. The state is spent whatever happens."""
    _require_enabled()
    now = datetime.now(UTC)
    row = await session.scalar(
        select(InstagramOAuthState)
        .where(InstagramOAuthState.token_hash == _hash(state))
        .with_for_update()
    )
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise InstagramRefused("state_invalid")
    row.used_at = now
    await session.flush()
    # Still an owner? Removed owners lose a flow they started.
    if not await _is_owner(session, shop_id=row.shop_id, owner_id=row.owner_id):
        raise InstagramRefused("not_owner")
    try:
        short, user_id = await graph.exchange_code(code, redirect_uri=redirect_uri())
        token = await graph.long_lived(short)
        account_id, username = await graph.me(token.access_token)
    except GraphError as error:
        raise InstagramRefused(error.code) from None
    if account_id != user_id or not account_id.isdigit():
        raise InstagramRefused("bad_response")
    values = {
        "ig_user_id": account_id,
        "username": username[:64] or "?",
        "token_encrypted": encrypt_access_token(token.access_token),
        "token_expires_at": now + timedelta(seconds=token.expires_in),
        "status": "active",
        "connected_by": row.owner_id,
        "connected_at": now,
        "refreshed_at": None,
        "last_error": None,
    }
    await session.execute(
        insert(InstagramConnection)
        .values(shop_id=row.shop_id, **values)
        .on_conflict_do_update(index_elements=[InstagramConnection.shop_id], set_=values)
    )
    connection = await session.get(InstagramConnection, row.shop_id, populate_existing=True)
    if connection is None:  # pragma: no cover - just written
        raise InstagramRefused("graph")
    return connection


async def disconnect(session: AsyncSession, *, shop_id: int, owner_id: int) -> bool:
    if not await _is_owner(session, shop_id=shop_id, owner_id=owner_id):
        raise InstagramRefused("not_owner")
    connection = await session.get(InstagramConnection, shop_id)
    if connection is None:
        return False
    await session.delete(connection)
    await session.flush()
    return True


async def active_connection(session: AsyncSession, shop_id: int) -> InstagramConnection | None:
    return await session.scalar(
        select(InstagramConnection).where(
            InstagramConnection.shop_id == shop_id, InstagramConnection.status == "active"
        )
    )


# --- publishing -------------------------------------------------------------------


async def queue_story(
    session: AsyncSession, *, shop_id: int, actor: int, draft_id: int, layout: str, jpeg: bytes
) -> tuple[int, str]:
    """Store the story for Meta to fetch. Returns (upload id, the URL token)."""
    _require_enabled()
    if await active_connection(session, shop_id) is None:
        raise InstagramRefused("not_connected")
    since = datetime.now(UTC) - timedelta(days=1)
    today = await session.scalar(
        select(func.count())
        .select_from(InstagramStoryUpload)
        .where(InstagramStoryUpload.shop_id == shop_id, InstagramStoryUpload.created_at > since)
    )
    if (today or 0) >= DAILY_CAP:
        raise InstagramRefused("daily_cap")
    token = secrets.token_urlsafe(TOKEN_BYTES)
    upload = InstagramStoryUpload(
        shop_id=shop_id,
        draft_id=draft_id,
        actor=actor,
        layout=layout,
        token_hash=_hash(token),
        image=jpeg,
        expires_at=datetime.now(UTC) + UPLOAD_TTL,
    )
    session.add(upload)
    await session.flush()
    return upload.id, token


async def served_image(session: AsyncSession, token: str) -> bytes | None:
    """What /ig/<token>.jpg serves: only a live upload's image, else nothing."""
    if not 32 <= len(token) <= 64:
        return None
    return await session.scalar(
        select(InstagramStoryUpload.image).where(
            InstagramStoryUpload.token_hash == _hash(token),
            InstagramStoryUpload.status.in_(("queued", "container")),
            InstagramStoryUpload.expires_at > datetime.now(UTC),
        )
    )


Notify = Callable[[int, int, str], Awaitable[None]]  # (shop_id, chat_id, text)
Sleep = Callable[[float], Awaitable[None]]


async def publish_upload(
    sessions: async_sessionmaker[AsyncSession],
    graph: Graph,
    *,
    upload_id: int,
    token: str,
    notify: Notify,
    sleep: Sleep = asyncio.sleep,
) -> str:
    """Container -> poll -> publish. Returns the upload's final status."""
    async with sessions() as session:
        upload = await session.scalar(
            select(InstagramStoryUpload)
            .where(InstagramStoryUpload.id == upload_id)
            .with_for_update()
        )
        if upload is None:
            return "missing"
        if upload.status != "queued" or upload.token_hash != _hash(token):
            return upload.status  # a redelivery, or a token that is not this upload's
        shop_id, actor = upload.shop_id, upload.actor
        lang = await session.scalar(select(Shop.lang).where(Shop.id == shop_id)) or "uz"
        connection = await active_connection(session, shop_id)
        if not enabled() or connection is None:
            code = "off" if not enabled() else "not_connected"
            await _finish(session, upload, "failed", code)
            await session.commit()
            await notify(shop_id, actor, message(code, lang))
            return "failed"
        access, ig_user = decrypt_access_token(connection.token_encrypted), connection.ig_user_id
        upload.status = "container"
        await session.commit()

    async def fail(code: str) -> str:
        async with sessions() as session:
            row = await session.get(InstagramStoryUpload, upload_id, with_for_update=True)
            if row is not None:
                await _finish(session, row, "failed", code)
            if code == "token_invalid":
                await session.execute(
                    update(InstagramConnection)
                    .where(InstagramConnection.shop_id == shop_id)
                    .values(status="expired", last_error=code)
                )
            await session.commit()
        await notify(shop_id, actor, message(code, lang))
        return "failed"

    try:
        if await graph.quota_left(ig_user, access) <= 0:
            return await fail("quota")
        container = await graph.create_story(ig_user, access, image_url=image_url(token))
        async with sessions() as session:
            await session.execute(
                update(InstagramStoryUpload)
                .where(InstagramStoryUpload.id == upload_id)
                .values(container_id=container)
            )
            await session.commit()
        for attempt in range(POLL_ATTEMPTS):
            status = await graph.container_status(container, access)
            if status == "FINISHED":
                break
            if status in {"ERROR", "EXPIRED"}:
                return await fail("container_failed")
            if attempt < POLL_ATTEMPTS - 1:
                await sleep(POLL_SECONDS)
        else:
            return await fail("timeout")
        media = await graph.publish(ig_user, access, container_id=container)
    except GraphError as error:
        return await fail(error.code)

    async with sessions() as session:
        row = await session.get(InstagramStoryUpload, upload_id, with_for_update=True)
        if row is not None:
            row.media_id = media
            await _finish(session, row, "published", None)
        await session.commit()
    await notify(shop_id, actor, message("published", lang))
    return "published"


async def _finish(
    session: AsyncSession, upload: InstagramStoryUpload, status: str, code: str | None
) -> None:
    """End an attempt: the image is wiped, so the URL stops answering."""
    upload.status = status
    upload.error_code = code
    upload.image = None
    upload.finished_at = datetime.now(UTC)
    await session.flush()


# --- upkeep ---------------------------------------------------------------------------


async def refresh_tokens(session: AsyncSession, graph: Graph) -> dict[str, int]:
    """Daily: refresh tokens nearing their end, retire dead ones, wipe stale uploads."""
    now = datetime.now(UTC)
    counts = {"refreshed": 0, "expired": 0, "uploads_expired": 0}
    due = (
        await session.scalars(
            select(InstagramConnection).where(
                InstagramConnection.status == "active",
                InstagramConnection.token_expires_at < now + REFRESH_BEFORE,
            )
        )
    ).all()
    for connection in due:
        if connection.token_expires_at <= now:
            connection.status, connection.last_error = "expired", "expired"
            counts["expired"] += 1
            continue
        try:
            token = await graph.refresh(decrypt_access_token(connection.token_encrypted))
        except GraphError as error:
            if error.code == "token_invalid":
                connection.status, connection.last_error = "expired", error.code
                counts["expired"] += 1
            else:
                connection.last_error = error.code  # retried tomorrow
            continue
        connection.token_encrypted = encrypt_access_token(token.access_token)
        connection.token_expires_at = now + timedelta(seconds=token.expires_in)
        connection.refreshed_at, connection.last_error = now, None
        counts["refreshed"] += 1
    stale = await session.execute(
        update(InstagramStoryUpload)
        .where(
            InstagramStoryUpload.status.in_(("queued", "container")),
            InstagramStoryUpload.expires_at < now,
        )
        .values(status="expired", image=None, finished_at=now, error_code="expired")
    )
    counts["uploads_expired"] = stale.rowcount or 0  # type: ignore[attr-defined]
    await session.flush()
    return counts
