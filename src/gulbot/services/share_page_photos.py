"""A page's photos (CP17): the Foto design's framed photo, and an invitation's
gallery of up to six.

WHAT REACHES THE DATABASE IS NEVER WHAT WAS UPLOADED. Every photo is decoded
and re-encoded by Pillow:

* the EXIF orientation is applied to the pixels, and then EVERY piece of
  metadata is left behind -- EXIF (camera, time, GPS position), XMP, ICC
  profile, comments. Re-encoding writes none of it, because none of it is
  passed on; tests/test_share_page_photos.py proves the GPS block is gone;
* it is scaled to fit 1200 px and saved as a plain JPEG, a few hundred KB;
* anything Pillow cannot read as a picture is refused, and so is anything over
  MAX_INPUT_BYTES or MAX_PIXELS (a decompression bomb is a small file that
  decodes to gigabytes).

PER SHOP: the row carries shop_id with a composite FK onto the page, and is
served only through the page's token -- its id alone opens nothing. Deleting or
expiring the page deletes its photos with the rest of what the creator gave us.

HOW MANY: an invitation keeps up to GALLERY_MAX, numbered 1..6 in the order
sent (position 1 is the Foto frame); a Ha/Yo'q page keeps one, and a new one
replaces it. Removing photos renumbers nothing -- "clear" removes them all.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.share_page import ANSWERABLE_KINDS, GALLERY_MAX, SharePage, SharePagePhoto
from gulbot.services import premium

#: The upload itself: Telegram's own photos are far below this.
MAX_INPUT_BYTES: Final = 10 * 1024 * 1024
#: Decoded size limit: 40 megapixels.
MAX_PIXELS: Final = 40_000_000
#: The stored picture fits in this square.
MAX_SIDE: Final = 1200
JPEG_QUALITY: Final = 82


class PhotoRefused(ValueError):
    """Not a picture we will store: unreadable, too large, or too many pixels."""


@dataclass(frozen=True)
class CleanPhoto:
    data: bytes
    width: int
    height: int


def clean_photo(raw: bytes) -> CleanPhoto:
    """Decode, orient, shrink and re-encode -- with no metadata at all."""
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise PhotoRefused("size")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.width * probe.height > MAX_PIXELS:
                raise PhotoRefused("pixels")
            probe.verify()  # structural check; the image must be reopened after
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            upright = ImageOps.exif_transpose(image)
            picture = upright.convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise PhotoRefused("unreadable") from None
    picture.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    # No exif=, no icc_profile=, no comment= : the new file carries nothing
    # but pixels.
    picture.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return CleanPhoto(data=out.getvalue(), width=picture.width, height=picture.height)


class GalleryFull(PhotoRefused):
    """The page already holds as many photos as its kind allows."""


def photo_limit(page: SharePage) -> int:
    return GALLERY_MAX if page.kind == "invite" else 1


async def _own_open_page(
    session: AsyncSession, *, shop_id: int, customer_id: int, page_id: int, now: datetime
) -> SharePage | None:
    """THIS customer's live page in THIS shop, locked; None if not theirs, or a
    Ha/Yo'q page already answered (locked, like every other edit)."""
    page = await session.scalar(
        select(SharePage)
        .where(
            SharePage.id == page_id,
            SharePage.shop_id == shop_id,
            SharePage.customer_id == customer_id,
            SharePage.deleted_at.is_(None),
            SharePage.expires_at > now,
        )
        .with_for_update()
    )
    if page is None or (page.kind in ANSWERABLE_KINDS and page.answered_at is not None):
        return None
    return page


async def store_photo(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    page_id: int,
    raw: bytes,
    now: datetime | None = None,
) -> SharePagePhoto | None:
    """Clean and add a photo to THIS customer's live page in THIS shop. None if
    the page is not theirs; GalleryFull once an invitation holds six. On a
    Ha/Yo'q page the one photo is replaced."""
    now = now or datetime.now(UTC)
    page = await _own_open_page(
        session, shop_id=shop_id, customer_id=customer_id, page_id=page_id, now=now
    )
    if page is None:
        return None
    # CP18: every photo is premium (gulbot.services.premium). Raises
    # PremiumLocked for a customer who has not unlocked it at this shop.
    await premium.require(session, shop_id=shop_id, customer_id=customer_id)
    limit = photo_limit(page)
    taken = list(
        await session.scalars(
            select(SharePagePhoto.position).where(SharePagePhoto.page_id == page.id)
        )
    )
    if limit == 1:
        await session.execute(delete(SharePagePhoto).where(SharePagePhoto.page_id == page.id))
        position = 1
    elif len(taken) >= limit:
        raise GalleryFull("full")
    else:
        position = max(taken, default=0) + 1  # photos are only ever cleared all at once
    photo = clean_photo(raw)
    row = SharePagePhoto(
        shop_id=page.shop_id,
        page_id=page.id,
        position=position,
        data=photo.data,
        width=photo.width,
        height=photo.height,
        size_bytes=len(photo.data),
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def clear_photos(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    page_id: int,
    now: datetime | None = None,
) -> bool:
    """Remove every photo of THIS customer's own open page. False if not theirs."""
    now = now or datetime.now(UTC)
    page = await _own_open_page(
        session, shop_id=shop_id, customer_id=customer_id, page_id=page_id, now=now
    )
    if page is None:
        return False
    await session.execute(delete(SharePagePhoto).where(SharePagePhoto.page_id == page.id))
    return True


@dataclass(frozen=True)
class PhotoRef:
    id: int
    position: int
    width: int
    height: int


async def photos_of(session: AsyncSession, *, page_id: int) -> list[PhotoRef]:
    """The page's photos in order -- what the page needs to link them, no bytes."""
    rows = await session.execute(
        select(
            SharePagePhoto.id, SharePagePhoto.position, SharePagePhoto.width, SharePagePhoto.height
        )
        .where(SharePagePhoto.page_id == page_id)
        .order_by(SharePagePhoto.position)
    )
    return [PhotoRef(int(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in rows]


async def photo_for_token(
    session: AsyncSession, token: str, photo_id: int
) -> SharePagePhoto | None:
    """Photo `photo_id` if it belongs to the LIVE page at this token, or None."""
    now = datetime.now(UTC)
    return await session.scalar(
        select(SharePagePhoto)
        .join(SharePage, SharePage.id == SharePagePhoto.page_id)
        .where(
            SharePagePhoto.id == photo_id,
            SharePage.token == token,
            SharePage.deleted_at.is_(None),
            SharePage.expires_at > now,
        )
    )


async def photo_count(session: AsyncSession, *, page_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(SharePagePhoto)
            .where(SharePagePhoto.page_id == page_id)
        )
        or 0
    )
