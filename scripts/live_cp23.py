"""CP23 live evidence: a rose and a tulip announcement with flower templates,
published through the REAL dev bot to the REAL dev channel, and one
Instagram story image for each, sent to the owner.

    python scripts/live_cp23.py --shop-id 1 --output docs/cp23-live-proof.json

Local dev only (refuses any other ENVIRONMENT). Uses the shop's existing
wiring -- its only owner and its channel -- and never rewires it. The bot
must be an admin of that channel with posting rights.

The choices a person would tap (description, confirm, template, story
layout) are supplied by this script through the SAME service and router
functions the buttons call; it does not claim human taps. The photos are
the gallery's schematic samples (original drawings of each flower's
motif), uploaded to the owner's chat first, exactly as a photo an owner
sends would be. No voice: the text path, which CP22 keeps always working.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

from aiogram.types import BufferedInputFile, Message
from sqlalchemy import select

from gulbot.announcements.extraction import Fields
from gulbot.bot.registry import registry_for
from gulbot.bot.routers.announcements import exact_preview, send_story
from gulbot.config import get_settings
from gulbot.db.session import task_session_factory
from gulbot.models.product import Product
from gulbot.models.shop import Shop
from gulbot.services import announcements as service

ROOT = Path(__file__).resolve().parents[1]

#: (sample theme, what the owner "says", template chosen, story layout)
CASES = (
    (
        "atirgul",
        "Qizil atirgul, ellik bitta dona, narxi to'rt yuz ellik ming so'm",
        "atirgul.premium",
        "arch",
    ),
    (
        "lola",
        "Sariq lola yigirma besh dona, narxi uch yuz ming so'm. 8-Mart uchun",
        "lola.festive",
        "magazine",
    ),
)


def sample_photo(theme: str) -> bytes:
    spec = importlib.util.spec_from_file_location("gallery_cp23", ROOT / "scripts/gallery_cp23.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("gallery script missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    photo: bytes = module.sample_photo(theme)
    return photo


async def live(*, shop_id: int) -> dict[str, Any]:
    if get_settings().environment != "local":
        raise ValueError("local dev environment required")
    results: list[dict[str, Any]] = []
    async with task_session_factory() as factory, factory() as session:
        shop = await session.scalar(select(Shop).where(Shop.id == shop_id))
        if shop is None or shop.channel_id is None or len(shop.owner_telegram_ids or []) != 1:
            raise ValueError("the dev shop needs exactly one owner and a channel")
        owner, channel = shop.owner_telegram_ids[0], shop.channel_id
        await service.require_author(session, shop_id=shop_id, actor=owner)
        registry = await registry_for(session, shop_ids=[shop_id])
        await session.commit()
        try:
            bot = registry.bot_for(shop_id)
            me = await bot.get_me()
            member = await bot.get_chat_member(channel, me.id)
            if member.status != "administrator" or not getattr(member, "can_post_messages", False):
                raise ValueError("the dev bot must be a channel admin with posting rights")
            for theme, said, template, story in CASES:
                photo = await asyncio.to_thread(sample_photo, theme)
                uploaded: Message = await bot.send_photo(
                    owner,
                    BufferedInputFile(photo, f"cp23-{theme}.jpg"),
                    caption=f"CP23 sinov: {theme} (sxematik namuna surat)",
                )
                if not uploaded.photo:
                    raise ValueError("the sample upload returned no photo")
                draft = await service.new_draft(session, shop_id=shop_id, actor=owner)
                draft.photos = [uploaded.photo[-1].file_id]
                await service.parse_description(session, draft, said)
                service.confirm(draft)
                await service.apply_default_template(session, draft)
                detected = draft.template
                service.choose_template(draft, template)
                await exact_preview(bot, uploaded, session, draft)
                link = await service.publish(
                    session,
                    bot=bot,
                    shop_id=shop_id,
                    actor=owner,
                    draft_id=draft.id,
                    revision=draft.revision,
                )
                await session.commit()
                product = await session.scalar(
                    select(Product).where(
                        Product.shop_id == shop_id,
                        Product.channel_message_id == draft.receipts[0]["message_id"],
                    )
                )
                if product is None or product.finalized_at is None:
                    raise ValueError("the published post did not reach the catalogue")
                await send_story(bot, uploaded, session, draft, story)
                fields = Fields.from_data(draft.fields)
                results.append(
                    {
                        "said": said,
                        "extracted": {
                            "flowers": fields.flowers,
                            "count": fields.count,
                            "price": fields.price,
                            "colour": fields.colour,
                        },
                        "theme_detected": service.draft_theme(draft),
                        "default_template_after_confirm": detected,
                        "template_published": draft.template,
                        "post_link": link,
                        "receipts": draft.receipts,
                        "caption": draft.preview_caption,
                        "catalog": {
                            "id": product.id,
                            "name": product.name,
                            "price_uzs": product.price_uzs,
                            "hashtags_from_caption": [
                                t
                                for t in (draft.preview_caption or "").split()
                                if t.startswith("#")
                            ],
                        },
                        "story_layout": story,
                        "story_sent_as": ["document (no recompression)", "photo"],
                    }
                )
        finally:
            await registry.close()
    return {
        "scope": "real dev Bot API and channel; production services and router "
        "functions; choices supplied by this script, not human taps",
        "bot_username": me.username,
        "channel_id": channel,
        "photos": "schematic sample drawings (gallery_cp23.sample_photo), not real bouquets",
        "posts": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        proof = asyncio.run(live(shop_id=args.shop_id))
    except Exception as exc:
        raise SystemExit(
            f"Live CP23 failed ({type(exc).__name__}); no credentials printed"
        ) from None
    args.output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Live CP23 evidence saved: {args.output}")
