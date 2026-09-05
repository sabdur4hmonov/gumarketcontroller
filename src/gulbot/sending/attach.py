"""Composing a bouquet into a reminder.

The one place in the send path that is allowed to know the catalogue exists.
`dispatcher.py` and `render.py` still must not -- `tests/test_sending_scope.py`
fails the build if they mention it -- because dispatch owns claiming, retrying
and marking, and none of that changes because a message now carries a photo.

WHY THE REMINDER BECOMES A CAPTION. CP6 guarantees that every row of a group is
marked in ONE update, so a partially-sent group is not a state the database can
hold. That holds only while a group is ONE API call. Sending text and then a
photo would be two, and a failure between them would leave a state with no
honest name. `sendPhoto` carries the reminder as its caption, so a reminder with
a bouquet costs exactly as many calls as one without: one.

WHEN THERE IS NO BOUQUET, the answer is None and the dispatcher sends bare text.
That is not a degraded path -- it is CP6, unchanged. An empty catalogue, a
customer with no preference and nothing indexed, a reminder too long to be a
caption: all of them still send the reminder. The catalogue may add to a
reminder; it may never cost one.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.i18n import t
from gulbot.models.recipient import Recipient
from gulbot.sending.dispatcher import DueGroup
from gulbot.sending.transport import CAPTION_LIMIT, Attachment
from gulbot.services.bouquets import Bouquet, choose_bouquet
from gulbot.utils.render import escape, format_price

Renderer = Callable[[DueGroup], str]


def leading_recipient(group: DueGroup) -> Recipient | None:
    """Whose preference wins in a merged reminder.

    The one whose date is SOONEST -- the same person the merged message leads
    with, so the photo matches the first line rather than the last. Days ahead
    is `-offset_days`, so the soonest occasion is the largest offset (closest
    to zero), not the smallest.
    """
    if not group.rows:
        return None
    soonest = max(group.rows, key=lambda row: row.offset_days)
    occasion = next((o for o in group.occasions if o.id == soonest.occasion_id), None)
    if occasion is None:  # pragma: no cover - context is loaded together
        return None
    return next((r for r in group.recipients if r.id == occasion.recipient_id), None)


def caption_for(group: DueGroup, bouquet: Bouquet, *, render: Renderer) -> str:
    """The reminder, then the bouquet's own line."""
    lang = group.lang
    # The name comes from a shop's caption, i.e. arbitrary text, and the bot
    # sends with parse_mode=HTML. Captions are parsed exactly like messages.
    name = escape(bouquet.name)
    if bouquet.has_price:
        offer = t("reminder.bouquet", lang, name=name, price=format_price(bouquet.price_uzs or 0))
    else:
        # A named requirement since the original design: an unpriced post is
        # shown, never hidden. The operator confirms the price.
        offer = t("reminder.bouquet.no_price", lang, name=name)
    return f"{render(group)}\n\n{offer}"


async def attach_bouquet(
    session: AsyncSession, group: DueGroup, *, render: Renderer
) -> Attachment | None:
    """Pick a bouquet for this group and compose the photo message."""
    recipient = leading_recipient(group)
    bouquet = await choose_bouquet(
        session,
        shop_id=group.shop_id,
        preferred_hashtag=recipient.preferred_hashtag if recipient else None,
    )
    if bouquet is None:
        return None

    caption = caption_for(group, bouquet, render=render)
    if len(caption) > CAPTION_LIMIT:
        # Rather than truncate the reminder or split it into two sends. The
        # reminder is the product; the bouquet is a suggestion.
        return None
    return Attachment(file_id=bouquet.telegram_file_id, caption=caption)
