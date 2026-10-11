"""Dedicated stt queue. Every task owns and closes its network clients."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.announcements.audio_guard import scrub
from gulbot.announcements.stt import transcribe
from gulbot.announcements.templates import escaped_fit
from gulbot.bot.registry import registry_for
from gulbot.config import get_settings
from gulbot.db.session import task_session_factory
from gulbot.models.announcement import AnnouncementDraft
from gulbot.services import announcements as service
from gulbot.worker.app import app

STT_SOFT_LIMIT, STT_HARD_LIMIT = 360, 420


async def enqueue_transcription(
    *, shop_id: int, actor: int, draft_id: int, revision: int, file_id: str
) -> str:
    args = {"shop_id": shop_id, "actor": actor, "draft_id": draft_id, "revision": revision}
    result = await asyncio.to_thread(
        transcribe_voice.apply_async,
        kwargs={**args, "file_id": file_id},
        queue="stt",
        expires=300,
        link_error=transcription_failed.si(**args).set(queue="celery"),
    )
    return str(result.id)


async def work(*, shop_id: int, actor: int, draft_id: int, revision: int, file_id: str) -> None:
    async with task_session_factory() as factory, factory() as session:
        draft = await service.draft_for(
            session, shop_id=shop_id, actor=actor, draft_id=draft_id, revision=revision
        )
        if draft.status != "transcribing":
            return  # Redelivery cannot transcribe or notify again.
        registry = await registry_for(session, shop_ids=[shop_id])
        await session.commit()  # Never hold a row lock across CPU recognition.
        try:
            bot = registry.bot_for(shop_id)
            await process(session, bot, draft, file_id)
        finally:
            await registry.close()


async def process(session: AsyncSession, bot: Bot, draft: AnnouncementDraft, file_id: str) -> None:
    from gulbot.bot.routers.announcements import review_keyboard

    settings = get_settings()
    revision = draft.revision
    shop_id, actor, draft_id = draft.shop_id, draft.author_id, draft.id
    root = Path(settings.stt_audio_dir).resolve()  # noqa: ASYNC240 dedicated worker, no other job
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = Path(tempfile.mkdtemp(prefix="cp22-audio-", dir=root))
    guardian = subprocess.Popen(  # noqa: ASYNC220 janitor starts before download, worker-only
        [
            sys.executable,
            "-m",
            "gulbot.announcements.audio_guard",
            str(directory),
            str(root),
            str(os.getpid()),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    try:
        source, wav = directory / "voice.ogg", directory / "voice.wav"
        try:
            await bot.download(file_id, destination=source, timeout=30)
            if source.stat().st_size > 10_000_000:
                raise ValueError("voice too large")
            result = transcribe(source, wav, settings)
        finally:
            scrub(directory, root)  # Delete BEFORE storing text or sending results.
        draft = await service.draft_for(
            session, shop_id=shop_id, actor=actor, draft_id=draft_id, revision=revision
        )
        if draft.status != "transcribing":
            return
        draft.status = "review"
        await service.parse_description(session, draft, result.text)
        await session.commit()
        f = draft.fields
        body = "\n".join(
            [
                "Ovozdan tushunildi — tekshiring:",
                result.text,
                f"Gullar: {', '.join(f.get('flowers', []))}",
                f"Soni: {f.get('count')}",
                f"Narxi: {f.get('price')} so'm",
                f"Rang: {f.get('colour')}",
                *[f"⚠ {w}" for w in f.get("warnings", [])],
                *[f"Imlo: {c}" for c in f.get("corrections", [])[:10]],
            ]
        )
        if draft.acknowledgement_id:
            await bot.edit_message_text(
                escaped_fit(body, 3900),
                chat_id=draft.author_id,
                message_id=draft.acknowledgement_id,
                reply_markup=review_keyboard(draft),
            )
    except service.AnnouncementRefused:
        await session.rollback()  # Revoked access or superseded job: no stale write.
    except Exception:
        await session.rollback()
        try:
            draft = await service.draft_for(
                session, shop_id=shop_id, actor=actor, draft_id=draft_id, revision=revision
            )
        except service.AnnouncementRefused:
            return
        if draft.status != "transcribing":
            return
        draft.status = "review"
        draft.revision += 1
        await session.commit()
        if draft.acknowledgement_id:
            await bot.edit_message_text(
                "Ovoz aniqlanmadi. Tavsifni matn bilan yuboring.",
                chat_id=draft.author_id,
                message_id=draft.acknowledgement_id,
            )
    finally:
        scrub(directory, root)
        guardian.terminate()
        guardian.wait(timeout=5)


@app.task(
    name="gulbot.transcribe_voice",
    queue="stt",
    soft_time_limit=STT_SOFT_LIMIT,
    time_limit=STT_HARD_LIMIT,
    acks_late=False,
    reject_on_worker_lost=False,
)
def transcribe_voice(
    *, shop_id: int, actor: int, draft_id: int, revision: int, file_id: str
) -> None:
    asyncio.run(
        work(shop_id=shop_id, actor=actor, draft_id=draft_id, revision=revision, file_id=file_id)
    )


async def failed(*, shop_id: int, actor: int, draft_id: int, revision: int) -> None:
    async with task_session_factory() as factory, factory() as session:
        try:
            draft = await service.draft_for(
                session, shop_id=shop_id, actor=actor, draft_id=draft_id, revision=revision
            )
        except service.AnnouncementRefused:
            return
        if draft.status != "transcribing":
            return
        draft.status = "review"
        draft.revision += 1
        acknowledgement = draft.acknowledgement_id
        await session.commit()
        registry = await registry_for(session, shop_ids=[shop_id])
        try:
            if acknowledgement:
                await registry.bot_for(shop_id).edit_message_text(
                    "Ovoz vaqti tugadi. Tavsifni matn bilan yuboring.",
                    chat_id=actor,
                    message_id=acknowledgement,
                )
        finally:
            await registry.close()


@app.task(name="gulbot.transcription_failed", queue="celery", soft_time_limit=30, time_limit=45)
def transcription_failed(*, shop_id: int, actor: int, draft_id: int, revision: int) -> None:
    asyncio.run(failed(shop_id=shop_id, actor=actor, draft_id=draft_id, revision=revision))
