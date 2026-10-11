"""Real dev bot/channel text-fallback evidence, with explicit destination IDs.

python scripts/live_cp22.py --shop-id 1 --owner-id <id> --channel-id <id> \
  --wire-empty-dev-shop --output <proof.json>

Uses real Bot API sends and the production authoring/indexing services. The
description/confirmation/style choices are supplied by this CLI, not claimed
to be human Telegram taps. Never run on production. Never acknowledges or
drops pending Telegram updates; own-post observations can be inconclusive.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from aiogram.types import BufferedInputFile
from sqlalchemy import select

from gulbot.bot.factory import ALLOWED_UPDATES
from gulbot.bot.registry import registry_for
from gulbot.bot.routers.announcements import exact_preview
from gulbot.config import get_settings
from gulbot.db.session import task_session_factory
from gulbot.models.product import Product
from gulbot.models.shop import Shop
from gulbot.services import announcements as service


async def live(*, shop_id: int, owner: int, channel: int, wire: bool) -> dict[str, Any]:
    if get_settings().environment != "local" or owner <= 0 or not str(channel).startswith("-100"):
        raise ValueError("local dev environment and explicit owner/channel IDs required")
    async with task_session_factory() as factory, factory() as session:
        shop = await session.scalar(select(Shop).where(Shop.id == shop_id))
        if shop is None:
            raise ValueError("dev shop does not exist")
        if wire:
            if shop.channel_id not in {None, channel} or shop.owner_telegram_ids not in [
                [],
                [owner],
            ]:
                raise ValueError("refusing to overwrite existing shop wiring")
            shop.channel_id, shop.owner_telegram_ids = channel, [owner]
            await session.commit()
        if shop.channel_id != channel:
            raise ValueError("channel does not match the selected dev shop")
        await service.require_author(session, shop_id=shop_id, actor=owner)
        registry = await registry_for(session, shop_ids=[shop_id])
        try:
            bot = registry.bot_for(shop_id)
            me = await bot.get_me()
            member = await bot.get_chat_member(channel, me.id)
            if member.status != "administrator" or not getattr(member, "can_post_messages", False):
                raise ValueError("dev bot must be a channel admin with posting permission")
            # Reading with no offset does not acknowledge any pending update.
            before = await bot.get_updates(timeout=0, allowed_updates=ALLOWED_UPDATES)
            source = await asyncio.to_thread(Path("docs/cp22-gallery/bouquet.jpg").read_bytes)
            uploaded = await bot.send_photo(
                owner,
                BufferedInputFile(source, "cp22-sample.jpg"),
                caption="CP22 sinov guldastasi — matn orqali.",
            )
            if not uploaded.photo:
                raise ValueError("sample photo upload returned no photo")
            draft = await service.new_draft(session, shop_id=shop_id, actor=owner)
            draft.photos = [uploaded.photo[-1].file_id]
            await service.parse_description(
                session, draft, "Qizil atirgul, ellik bitta dona, narxi to'rt yuz ellik ming so'm"
            )
            service.confirm(draft)
            service.choose_style(draft, kind="caption", value="premium")
            service.choose_style(draft, kind="image", value="gold-corners")
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
            observation_started = time.monotonic()
            after_by_id = {}
            while time.monotonic() - observation_started < 8:
                observed = await bot.get_updates(timeout=1, allowed_updates=ALLOWED_UPDATES)
                after_by_id.update({update.update_id: update for update in observed})
                await asyncio.sleep(1)
            observation_seconds = round(time.monotonic() - observation_started, 2)
            after = list(after_by_id.values())
            own_ids = {r["message_id"] for r in draft.receipts}
            own_updates = [
                u.update_id
                for u in after
                if u.channel_post
                and u.channel_post.chat.id == channel
                and u.channel_post.message_id in own_ids
            ]
            product = await session.scalar(
                select(Product).where(
                    Product.shop_id == shop_id,
                    Product.channel_message_id == draft.receipts[0]["message_id"],
                )
            )
            if product is None or product.price_uzs != 450000 or product.finalized_at is None:
                raise ValueError("published bouquet did not appear in the catalog")
            await bot.send_message(
                owner, f"Joylandi: {link}\nKatalog: {product.name}, {product.price_uzs:,} so'm"
            )
            return {
                "scope": "real dev Bot API/channel and production services; CLI supplied choices",
                "mode": "text-fallback; no voice recording supplied",
                "shop_id": shop_id,
                "bot_username": me.username,
                "channel_id": channel,
                "draft_id": draft.id,
                "post_link": link,
                "receipts": draft.receipts,
                "catalog": {
                    "id": product.id,
                    "name": product.name,
                    "price_uzs": product.price_uzs,
                    "finalized_at": product.finalized_at.isoformat(),
                },
                "own_channel_post_observed": bool(own_updates),
                "observed_update_ids": own_updates,
                "observation_seconds": observation_seconds,
                "pending_before": len(before),
                "pending_after": len(after),
                "observation_limit": (
                    "No pending updates acknowledged; a 100-update backlog makes absence "
                    "inconclusive. This observation is not a Telegram delivery guarantee."
                ),
            }
        finally:
            await registry.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-id", type=int, required=True)
    parser.add_argument("--owner-id", type=int, required=True)
    parser.add_argument("--channel-id", type=int, required=True)
    parser.add_argument("--wire-empty-dev-shop", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        proof = asyncio.run(
            live(
                shop_id=args.shop_id,
                owner=args.owner_id,
                channel=args.channel_id,
                wire=args.wire_empty_dev_shop,
            )
        )
    except Exception as exc:
        raise SystemExit(
            f"Live CP22 failed ({type(exc).__name__}); no credentials printed"
        ) from None
    args.output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Live post and catalog evidence saved: {args.output}")
