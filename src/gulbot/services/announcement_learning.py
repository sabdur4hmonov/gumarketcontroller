"""A shop's learned corrections (CP23 addendum): stored, applied, listed, forgotten.

What may be learned is decided in announcements/learning.py (pure). This
module only keeps it -- strictly per shop: every read and write is filtered
by shop_id, so one shop's corrections never touch another's announcements --
and caps it at CORRECTIONS_CAP rows a shop, dropping the least recently used.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.announcements.learning import Learned
from gulbot.announcements.lexicon import normalize_word
from gulbot.models.announcement import AnnouncementCorrection

CORRECTIONS_CAP = 200


async def learned_for(session: AsyncSession, shop_id: int) -> dict[str, str]:
    rows = await session.execute(
        select(AnnouncementCorrection.heard, AnnouncementCorrection.corrected)
        .where(AnnouncementCorrection.shop_id == shop_id)
        .order_by(AnnouncementCorrection.last_used_at.desc())
        .limit(CORRECTIONS_CAP)
    )
    return {heard: corrected for heard, corrected in rows}


async def remember(
    session: AsyncSession, *, shop_id: int, taught_by: int, items: Sequence[Learned]
) -> list[Learned]:
    """Store what was learned (a newer fix of the same words replaces the older)."""
    now = datetime.now(UTC)
    for item in items:
        await session.execute(
            insert(AnnouncementCorrection)
            .values(
                shop_id=shop_id,
                heard=item.heard,
                corrected=item.corrected,
                kind=item.kind,
                taught_by=taught_by,
                last_used_at=now,
            )
            .on_conflict_do_update(
                index_elements=[AnnouncementCorrection.shop_id, AnnouncementCorrection.heard],
                set_={
                    "corrected": item.corrected,
                    "kind": item.kind,
                    "taught_by": taught_by,
                    "last_used_at": now,
                },
            )
        )
    if items:
        keep = (
            select(AnnouncementCorrection.id)
            .where(AnnouncementCorrection.shop_id == shop_id)
            .order_by(AnnouncementCorrection.last_used_at.desc(), AnnouncementCorrection.id.desc())
            .limit(CORRECTIONS_CAP)
        )
        await session.execute(
            delete(AnnouncementCorrection).where(
                AnnouncementCorrection.shop_id == shop_id,
                AnnouncementCorrection.id.notin_(keep.scalar_subquery()),
            )
        )
    await session.flush()
    return list(items)


async def mark_used(session: AsyncSession, *, shop_id: int, applied: Sequence[str]) -> None:
    """Count the uses of what extraction applied ("heard → corrected")."""
    heard = {normalize_word(entry.split(" → ", 1)[0]) for entry in applied}
    if not heard:
        return
    await session.execute(
        update(AnnouncementCorrection)
        .where(AnnouncementCorrection.shop_id == shop_id, AnnouncementCorrection.heard.in_(heard))
        .values(uses=AnnouncementCorrection.uses + 1, last_used_at=datetime.now(UTC))
    )


async def corrections(session: AsyncSession, shop_id: int) -> list[AnnouncementCorrection]:
    return list(
        (
            await session.scalars(
                select(AnnouncementCorrection)
                .where(AnnouncementCorrection.shop_id == shop_id)
                .order_by(AnnouncementCorrection.last_used_at.desc())
                .limit(CORRECTIONS_CAP)
            )
        ).all()
    )


async def forget(session: AsyncSession, *, shop_id: int, correction_id: int) -> bool:
    """Delete one of THIS shop's corrections; another shop's id deletes nothing."""
    result = await session.execute(
        delete(AnnouncementCorrection).where(
            AnnouncementCorrection.shop_id == shop_id, AnnouncementCorrection.id == correction_id
        )
    )
    await session.flush()
    return bool(result.rowcount)  # type: ignore[attr-defined]
