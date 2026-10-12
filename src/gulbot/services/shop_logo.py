"""A shop's own logo (CP23 addendum, the owner's request).

An owner sends the logo to the shop's bot -- as a photo, or as a PNG file to
keep its transparency. It is stored NORMALISED: EXIF-rotated, RGBA, fully
transparent borders trimmed, at most LOGO_SIDE px a side, PNG. Then every
photo of the shop's announcements and every story image carries it, in a
corner that never covers the text (designs.py / stories.py place it).

Only the shop's explicit owners (owner_telegram_ids) set or remove it:
staff publish, owners decide the shop's brand.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

from PIL import Image, ImageOps
from sqlalchemy import any_, delete, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.announcement import ShopLogo
from gulbot.models.shop import Shop

LOGO_SIDE = 512
MIN_SIDE = 16
MAX_BYTES = 10_000_000
MAX_PIXELS = 25_000_000


class LogoRefused(ValueError):
    pass


def normalise(data: bytes) -> tuple[bytes, int, int]:
    """Any image an owner sends -> (PNG bytes, width, height). Refuses junk."""
    if not 0 < len(data) <= MAX_BYTES:
        raise LogoRefused("Logo fayli 10 MB dan oshmasin")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise LogoRefused("Logo juda katta")
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except (OSError, ValueError) as error:
        if isinstance(error, LogoRefused):
            raise
        raise LogoRefused("Bu rasm emas. Logoni rasm yoki PNG fayl qilib yuboring") from None
    box = image.getchannel("A").getbbox()
    if box is None:
        raise LogoRefused("Logo butunlay shaffof")
    image = image.crop(box)
    image.thumbnail((LOGO_SIDE, LOGO_SIDE), Image.Resampling.LANCZOS)
    if min(image.size) < MIN_SIDE:
        raise LogoRefused("Logo juda kichik")
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), image.width, image.height


async def is_owner(session: AsyncSession, *, shop_id: int, actor: int) -> bool:
    found = await session.scalar(
        select(Shop.id).where(Shop.id == shop_id, literal(actor) == any_(Shop.owner_telegram_ids))
    )
    return actor > 0 and found is not None


async def set_logo(session: AsyncSession, *, shop_id: int, actor: int, data: bytes) -> ShopLogo:
    if not await is_owner(session, shop_id=shop_id, actor=actor):
        raise LogoRefused("Logoni faqat do'kon egasi o'rnatadi")
    png, width, height = normalise(data)
    values = {
        "image": png,
        "width": width,
        "height": height,
        "uploaded_by": actor,
        "updated_at": datetime.now(UTC),
    }
    await session.execute(
        insert(ShopLogo)
        .values(shop_id=shop_id, **values)
        .on_conflict_do_update(index_elements=[ShopLogo.shop_id], set_=values)
    )
    logo = await session.get(ShopLogo, shop_id, populate_existing=True)
    if logo is None:  # pragma: no cover - just written
        raise LogoRefused("Logo saqlanmadi")
    return logo


async def remove_logo(session: AsyncSession, *, shop_id: int, actor: int) -> bool:
    if not await is_owner(session, shop_id=shop_id, actor=actor):
        raise LogoRefused("Logoni faqat do'kon egasi o'chiradi")
    result = await session.execute(delete(ShopLogo).where(ShopLogo.shop_id == shop_id))
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def logo_image(session: AsyncSession, shop_id: int) -> Image.Image | None:
    """The shop's logo, decoded, for the renderers -- or None."""
    data = await session.scalar(select(ShopLogo.image).where(ShopLogo.shop_id == shop_id))
    if data is None:
        return None
    with Image.open(io.BytesIO(data)) as image:
        decoded: Image.Image = image.convert("RGBA")
    return decoded
