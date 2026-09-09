"""Inline callback data factories.

Each factory exposes `samples()`, and the shadow sweep probes the live
dispatcher with every sample. Adding a factory therefore extends the gate
automatically -- there is no separate list to keep in sync.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData

from gulbot.models.occasion import MAX_DAY_IN_MONTH, OccasionKind, OccasionType
from gulbot.models.recipient import FLOWER_PRESETS


class OccasionTypeCB(CallbackData, prefix="occtype"):
    type: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(type=t.value).pack() for t in OccasionType]


class OccasionKindCB(CallbackData, prefix="occkind"):
    """WHAT the date is, asked after WHO it is for."""

    kind: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(kind=k.value).pack() for k in OccasionKind]


class MonthCB(CallbackData, prefix="occmonth"):
    month: int

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(month=m).pack() for m in range(1, 13)]


class DayCB(CallbackData, prefix="occday"):
    day: int

    @classmethod
    def samples(cls) -> list[str]:
        # First, last and a Feb-29 boundary value.
        return [cls(day=d).pack() for d in (1, 15, 29, 30, max(MAX_DAY_IN_MONTH))]


class YearSkipCB(CallbackData, prefix="occyear"):
    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action="skip").pack()]


class ConfirmCB(CallbackData, prefix="occconfirm"):
    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action=a).pack() for a in ("save", "discard")]


class BackCB(CallbackData, prefix="occback"):
    """Back inside the inline flow. Handled per state, never globally."""

    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action="back").pack()]


class OccasionActionCB(CallbackData, prefix="occact"):
    action: str
    occasion_id: int

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action="deactivate", occasion_id=1).pack()]


class AddOccasionCB(CallbackData, prefix="occadd"):
    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action="start").pack()]


class YesNoCB(CallbackData, prefix="occyn"):
    """Answers to the chained "yana ...?" questions.

    `scope` distinguishes the two loops so the same Ha/Yo'q pair can appear
    twice without the handlers becoming ambiguous.
    """

    scope: str
    answer: str

    @classmethod
    def samples(cls) -> list[str]:
        return [
            cls(scope=scope, answer=answer).pack()
            for scope in ("dates", "people")
            for answer in ("yes", "no")
        ]


class RecipientCB(CallbackData, prefix="rcp"):
    action: str
    recipient_id: int

    @classmethod
    def samples(cls) -> list[str]:
        return [
            cls(action=action, recipient_id=1).pack()
            for action in ("open", "rename", "deactivate", "add_date")
        ]


class EditOccasionCB(CallbackData, prefix="occedit"):
    occasion_id: int

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(occasion_id=1).pack()]


class RecipientListCB(CallbackData, prefix="rcplist"):
    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action="back").pack()]


class FlowerCB(CallbackData, prefix="flower"):
    """Per-recipient flower preset. "skip" stores NULL."""

    choice: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(choice=c).pack() for c in (*FLOWER_PRESETS, "skip")]


class ReminderCountCB(CallbackData, prefix="remcount"):
    value: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(value=v).pack() for v in ("1", "2", "3", "skip")]


class SendTimeCB(CallbackData, prefix="sendtime"):
    """Named slots, not clock times.

    aiogram packs callback data with ":" as the field separator, so "09:00"
    would be parsed as two fields. The name maps to a real time in
    customer.SEND_TIME_CHOICES.
    """

    value: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(value=v).pack() for v in ("morning", "noon", "evening", "skip")]


class OrderAdminCB(CallbackData, prefix="ordadm"):
    """The two buttons on the shop's order card.

    THE PREFIX IS LOAD-BEARING. It is the one thing the chat gate lets
    through from a group -- see `ChatGateMiddleware` -- so renaming it
    silently makes the buttons stop working rather than failing loudly.
    `tests/test_admin_orders.py` pins the two names together.

    The order id travels in the button rather than in state, because the
    card outlives any conversation: an admin may act on a card from
    yesterday, and there is no session to have remembered it.
    """

    action: str
    order_id: int

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action=a, order_id=1).pack() for a in ("confirm", "reject")]


class BrowsePageCB(CallbackData, prefix="brwpage"):
    """Paging through the catalogue. Direction only -- the cursor lives in
    FSM data, because a cursor in callback data would be a timestamp a
    customer could edit."""

    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action=a).pack() for a in ("next", "prev", "close")]


class BrowsePickCB(CallbackData, prefix="brwpick"):
    """One bouquet chosen from the list."""

    product_id: int

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(product_id=n).pack() for n in (1, 4242)]


class OrderStartCB(CallbackData, prefix="ordstart"):
    """The button under a bouquet.

    `recipient_id` is 0 when there is no one to name -- the browse screen,
    where the customer picked a bouquet without any occasion behind it. From
    a reminder it is the person the reminder was ABOUT, which does two
    things: it is finally what writes `orders.recipient_id` (nothing ever
    did, so the column was NULL on every order), and it gives "who is this
    for" a one-tap answer instead of making the customer type a name the
    bot already knows.

    Zero rather than None because callback data is a string either way, and
    an absent field would make the two callers produce different shapes.
    """

    product_id: int
    recipient_id: int = 0

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(product_id=1).pack(), cls(product_id=1, recipient_id=7).pack()]


class OrderRecipientCB(CallbackData, prefix="ordrecip"):
    """Accepting the name the bot already knows, or asking to type another.

    Only ever shown when the order came from a reminder: the browse path has
    no name to offer, so it goes straight to free text.
    """

    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action=a).pack() for a in ("known", "other")]


class OrderDateCB(CallbackData, prefix="orddate"):
    """Days from today, not an ISO date: an offset cannot disagree with the
    shop's timezone about which day "today" is."""

    offset: int

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(offset=o).pack() for o in (0, 1, 13)]


class OrderHourCB(CallbackData, prefix="ordhour"):
    hour: int

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(hour=h).pack() for h in (9, 12, 19)]


class OrderLocationCB(CallbackData, prefix="ordloc"):
    mode: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(mode=m).pack() for m in ("text", "pin")]


class OrderConfirmCB(CallbackData, prefix="ordconf"):
    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action=a).pack() for a in ("submit", "discard")]


class OrderBackCB(CallbackData, prefix="ordback"):
    """Back inside the order flow. Per state, never global."""

    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action="back").pack()]


ALL_FACTORIES: tuple[type[CallbackData], ...] = (
    OccasionTypeCB,
    MonthCB,
    DayCB,
    YearSkipCB,
    ConfirmCB,
    BackCB,
    OccasionActionCB,
    AddOccasionCB,
    YesNoCB,
    RecipientCB,
    EditOccasionCB,
    RecipientListCB,
    FlowerCB,
    ReminderCountCB,
    SendTimeCB,
    OrderStartCB,
    OrderRecipientCB,
    OrderDateCB,
    OrderHourCB,
    OrderLocationCB,
    OrderConfirmCB,
    OrderBackCB,
    BrowsePageCB,
    BrowsePickCB,
    OrderAdminCB,
)


def all_callback_samples() -> list[str]:
    samples: list[str] = []
    for factory in ALL_FACTORIES:
        samples.extend(factory.samples())  # type: ignore[attr-defined]
    return samples
