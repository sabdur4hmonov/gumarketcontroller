"""CP23 addendum live evidence, through the REAL dev bot and channel.

    python scripts/live_cp23_addendum.py --shop-id 1 --output docs/cp23-addendum-live-proof.json

1. What speech recognition "heard" has a wrong word ("atirgil"); the owner
   fixes it with "✏️ Matnni tuzatish" -> the SAME extraction runs on the
   corrected text and the shop learns atirgil -> atirgul.
2. The next announcement with the same mishearing is corrected
   automatically, before the lexicon; it is published (with a SAMPLE logo
   stamped on its photo, removed again at the end -- the owner sends the
   real one with /logo).
3. The published post's price is edited from "Mening e'lonlarim": the
   channel caption changes and the catalogue shows the new price.
4. Whether Telegram delivered the bot an edited_channel_post for its own edit
   is OBSERVED (without acknowledging any update) and recorded.

No speech model runs on this machine: the "heard" text stands in for what the
recogniser would return, and is said to be exactly that. Local dev only.
Choices are supplied through the same service functions the buttons call.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import io
import json
import time
from pathlib import Path
from typing import Any

from aiogram.types import BufferedInputFile, Message
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from gulbot.announcements.extraction import Fields
from gulbot.bot.factory import ALLOWED_UPDATES
from gulbot.bot.registry import registry_for
from gulbot.bot.routers.announcements import exact_preview
from gulbot.config import get_settings
from gulbot.db.session import task_session_factory
from gulbot.models.announcement import AnnouncementCorrection
from gulbot.models.product import Product
from gulbot.models.shop import Shop
from gulbot.services import announcements as service
from gulbot.services import published_posts, shop_logo

ROOT = Path(__file__).resolve().parents[1]
HEARD = "Qizil atirgil, o'n bitta dona, narxi ikki yuz ming so'm"
FIXED = "Qizil atirgul, o'n bitta dona, narxi ikki yuz ming so'm"
NEXT_HEARD = "Oq atirgil yigirma bitta dona, narxi uch yuz ming so'm"


def sample_photo() -> bytes:
    spec = importlib.util.spec_from_file_location("gallery_cp23", ROOT / "scripts/gallery_cp23.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("gallery script missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    photo: bytes = module.sample_photo("atirgul")
    return photo


def sample_logo() -> bytes:
    """A plainly labelled SAMPLE logo (removed at the end)."""
    image = Image.new("RGBA", (520, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 516, 196), radius=40, outline=(122, 20, 36, 255), width=10)
    font = ImageFont.truetype(
        str(ROOT / "src/gulbot/announcements/assets/fonts/NotoSans-SemiBold.ttf"), 70
    )
    draw.text((50, 55), "NAMUNA", font=font, fill=(122, 20, 36, 255))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


async def live(*, shop_id: int) -> dict[str, Any]:
    if get_settings().environment != "local":
        raise ValueError("local dev environment required")
    proof: dict[str, Any] = {
        "scope": "real dev Bot API and channel; production services; no speech model -- the "
        "'heard' text stands in for the recogniser's output",
    }
    async with task_session_factory() as factory, factory() as session:
        shop = await session.scalar(select(Shop).where(Shop.id == shop_id))
        if shop is None or shop.channel_id is None or len(shop.owner_telegram_ids or []) != 1:
            raise ValueError("the dev shop needs exactly one owner and a channel")
        owner, channel = shop.owner_telegram_ids[0], shop.channel_id
        if await shop_logo.logo_image(session, shop_id) is not None:
            raise ValueError("the dev shop already has a logo; not overwriting it with a sample")
        registry = await registry_for(session, shop_ids=[shop_id])
        await session.commit()
        try:
            bot = registry.bot_for(shop_id)
            proof["bot_username"] = (await bot.get_me()).username
            uploaded: Message = await bot.send_photo(
                owner,
                BufferedInputFile(await asyncio.to_thread(sample_photo), "cp23a.jpg"),
                caption="CP23 qo'shimcha sinov (sxematik namuna surat)",
            )
            assert uploaded.photo

            # 1. A mishearing, fixed with "Matnni tuzatish".
            first = await service.new_draft(session, shop_id=shop_id, actor=owner)
            first.photos = [uploaded.photo[-1].file_id]
            await service.parse_description(session, first, HEARD)
            before = Fields.from_data(first.fields)
            learned = await service.retext(session, first, actor=owner, text=FIXED)
            after = Fields.from_data(first.fields)
            await service.cancel(session, first)  # this one is not published
            await session.commit()
            proof["fix"] = {
                "heard": HEARD,
                "uncertain_before": before.uncertain,
                "heard_as": before.heard,
                "corrected_text": FIXED,
                "learned": [vars(item) for item in learned],
                "fields_after": {
                    "flowers": after.flowers,
                    "count": after.count,
                    "price": after.price,
                    "colour": after.colour,
                },
            }

            # 2. The same mistake, corrected automatically next time; published
            #    with a SAMPLE logo.
            await shop_logo.set_logo(session, shop_id=shop_id, actor=owner, data=sample_logo())
            second = await service.new_draft(session, shop_id=shop_id, actor=owner)
            second.photos = [uploaded.photo[-1].file_id]
            await service.parse_description(session, second, NEXT_HEARD)
            auto = Fields.from_data(second.fields)
            service.confirm(second)
            await service.apply_default_template(session, second)
            await exact_preview(bot, uploaded, session, second)
            link = await service.publish(
                session,
                bot=bot,
                shop_id=shop_id,
                actor=owner,
                draft_id=second.id,
                revision=second.revision,
            )
            await session.commit()
            row = await session.scalar(
                select(AnnouncementCorrection).where(
                    AnnouncementCorrection.shop_id == shop_id,
                    AnnouncementCorrection.heard == "atirgil",
                )
            )
            product = await session.scalar(
                select(Product).where(
                    Product.shop_id == shop_id,
                    Product.channel_message_id == second.receipts[0]["message_id"],
                )
            )
            assert product is not None
            proof["auto_corrected"] = {
                "heard": NEXT_HEARD,
                "learned_applied": auto.learned,
                "flowers": auto.flowers,
                "uncertain": auto.uncertain,
                "correction_uses": row.uses if row else None,
                "published": link,
                "template": second.template,
                "logo": "sample logo stamped on the post photo",
                "catalog_before_edit": {
                    "id": product.id,
                    "name": product.name,
                    "price_uzs": product.price_uzs,
                },
            }

            # 3. The price edited after publication; 4. observe own-edit updates.
            pending = await bot.get_updates(timeout=0, allowed_updates=ALLOWED_UPDATES)
            await published_posts.edit_field(
                session,
                bot,
                shop_id=shop_id,
                actor=owner,
                draft_id=second.id,
                field="price",
                value="350 ming",
            )
            await session.commit()
            started, seen = time.monotonic(), {}
            while time.monotonic() - started < 8:
                for update in await bot.get_updates(timeout=1, allowed_updates=ALLOWED_UPDATES):
                    seen[update.update_id] = update
                await asyncio.sleep(1)
            own_edits = [
                u.update_id
                for u in seen.values()
                if u.edited_channel_post
                and u.edited_channel_post.chat.id == channel
                and u.edited_channel_post.message_id == second.receipts[0]["message_id"]
            ]
            refreshed = await session.scalar(
                select(Product)
                .where(Product.id == product.id)
                .execution_options(populate_existing=True)
            )
            assert refreshed is not None
            proof["edit"] = {
                "new_price_typed": "350 ming",
                "catalog_after_edit": {
                    "name": refreshed.name,
                    "price_uzs": refreshed.price_uzs,
                    "active": refreshed.active,
                },
                "own_edited_channel_post_observed": bool(own_edits),
                "observation_seconds": round(time.monotonic() - started, 1),
                "pending_before": len(pending),
                "note": "No update was acknowledged. The catalogue was updated by calling the "
                "indexer's apply_edit directly, which does not depend on this delivery.",
            }
            await bot.send_message(
                owner,
                f"CP23 qo'shimcha: {link}\nKatalog: {refreshed.name}, {refreshed.price_uzs} so'm",
            )
        finally:
            # The sample logo goes: the owner sends the real one with /logo.
            await shop_logo.remove_logo(session, shop_id=shop_id, actor=owner)
            await session.commit()
            await registry.close()
    proof["sample_logo_removed"] = True
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(live(shop_id=args.shop_id))
    except Exception as exc:
        raise SystemExit(
            f"Live CP23 addendum failed ({type(exc).__name__}); no credentials printed"
        ) from None
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"saved: {args.output}")
