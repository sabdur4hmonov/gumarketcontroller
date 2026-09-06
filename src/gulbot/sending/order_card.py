"""The order, as the shop reads it. Pure: no database, no Telegram, no clock.

Everything the group message says is derived from an `OrderCard` -- a flat
snapshot handed in by the caller -- so the wording can be tested exhaustively
without a session, and so the send path cannot accidentally start querying from
inside a render.

WHY A CARD RATHER THAN THE ORM ROW. The card is assembled once, when the ping is
sent, from the order's SNAPSHOT columns. A renderer holding an `Order` would be
one lazy load away from reading a product that has since been repriced or
deleted -- which is exactly what CP10a froze the snapshot to prevent. Passing a
frozen dataclass makes that mistake unavailable rather than merely discouraged.

ONE MESSAGE, ALWAYS. The card rides as the caption of the bouquet photo, the
same single-call discipline CP9 established: a photo and then a text message
would be two API calls, and a failure between them would leave a ping that is
half-sent, which is a state with no honest name. When the card is too long to
be a caption the whole thing falls back to text -- still one call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from gulbot.i18n import t
from gulbot.utils.render import escape, format_date_long, format_price

#: The announcement that goes out the moment an order is placed. The delivery
#: reminders are 1..n and index `shops.order_ping_offset_hours`; this one is not
#: in that array and never will be, so it takes the number below the first.
ANNOUNCEMENT = 0


@dataclass(frozen=True)
class OrderCard:
    """One order, flattened. Assembled from the snapshot, never from a product."""

    order_id: int
    product_name: str
    price_uzs: int | None
    telegram_file_id: str
    delivery_date: date
    delivery_hour: time
    landmark: str
    customer_telegram_id: int
    location_text: str | None = None
    location_lat: float | None = None
    location_lon: float | None = None
    customer_phone: str | None = None
    phone_verified: bool = False


def heading_for(card: OrderCard, *, ping_number: int, hours_ahead: int | None, lang: str) -> str:
    """ "New order", or "N hours until delivery".

    `hours_ahead` comes from the ping's scheduled offset, not from comparing the
    clock to the delivery time. A tick that runs three minutes late must still
    say "3 soat" -- the number the shop was promised -- rather than quietly
    rounding to a different one.
    """
    if ping_number == ANNOUNCEMENT:
        return t("group.new_order", lang, id=card.order_id)
    return t("group.ping", lang, id=card.order_id, hours=hours_ahead)


def bouquet_line(card: OrderCard, lang: str) -> str:
    """REUSES the reminder's keys on purpose.

    "narx operator tomonidan tasdiqlanadi" is a wording the shop and the
    customer must never disagree about, so it exists in exactly one place. The
    FSM's confirmation screen reuses the same pair.
    """
    name = escape(card.product_name)
    if card.price_uzs:
        return t("reminder.bouquet", lang, name=name, price=format_price(card.price_uzs))
    return t("reminder.bouquet.no_price", lang, name=name)


def location_line(card: OrderCard, lang: str) -> str:
    """A typed address, or the pin with a map link.

    The coordinates are printed as well as linked. A courier without data, or
    with a maps app that is not Google's, still has the numbers to type in.
    """
    if card.location_text is not None:
        return escape(card.location_text)
    lat, lon = card.location_lat, card.location_lon
    return t(
        "group.pin",
        lang,
        lat=f"{lat:.6f}",
        lon=f"{lon:.6f}",
        url=f"https://maps.google.com/?q={lat:.6f},{lon:.6f}",
    )


def customer_line(card: OrderCard, lang: str) -> str:
    """The number to call, and a link to the chat.

    An UNVERIFIED number is shown and labelled, never withheld -- the courier
    needs something to dial, and "typed by hand" is a legitimate choice the
    customer made (see `customers.phone_verified`). Hiding it would turn a
    caveat into a missing field.
    """
    if not card.customer_phone:
        phone = t("group.no_phone", lang)
    elif card.phone_verified:
        phone = escape(card.customer_phone)
    else:
        phone = t("group.phone_unverified", lang, phone=escape(card.customer_phone))
    return t("group.customer", lang, phone=phone, tg=card.customer_telegram_id)


def render_card(
    card: OrderCard, *, ping_number: int, hours_ahead: int | None = None, lang: str = "uz"
) -> str:
    """The whole message. One call per ping, whatever is in it."""
    return t(
        "group.card",
        lang,
        heading=heading_for(card, ping_number=ping_number, hours_ahead=hours_ahead, lang=lang),
        bouquet=bouquet_line(card, lang),
        date=format_date_long(card.delivery_date.day, card.delivery_date.month, None, lang),
        hour=card.delivery_hour.strftime("%H:%M"),
        location=location_line(card, lang),
        landmark=escape(card.landmark),
        customer=customer_line(card, lang),
    )
