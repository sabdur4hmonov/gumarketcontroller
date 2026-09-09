"""FSM states.

Every text-waiting handler must be gated on one of these. A handler that waits
for free text at state None will swallow input intended for a flow, which is the
failure mode the shadowing sweep exists to catch.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    choosing_language = State()
    #: Asked ONCE, at the end of the first-contact chain, and skippable. A
    #: customer who only ever wants reminders is not made to hand over a phone
    #: number for a service that will never phone them.
    sharing_phone = State()


class SettingsFlow(StatesGroup):
    choosing_language = State()


class AddOccasion(StatesGroup):
    """Adding a recurring date.

    Only `entering_label` and `entering_year` wait for text; every other step is
    an inline picker. Keeping the text-waiting surface this small is deliberate:
    free-text dates in uz/ru produce garbage no parser fixes, and every
    text-waiting state is somewhere shadowing can bite.
    """

    choosing_type = State()
    entering_label = State()
    # WHAT the date is. Asked after the person, before the date itself.
    choosing_kind = State()
    choosing_month = State()
    choosing_day = State()
    entering_year = State()
    confirming = State()
    # The chained "yana ...?" loops. Both are button-only, so neither widens
    # the text-waiting surface.
    asking_more_dates = State()
    # Asked once per recipient, only when they have no preference yet.
    asking_flower = State()
    asking_more_people = State()
    # Customer-level, asked once, at the very end of the chain.
    asking_reminder_count = State()
    asking_send_time = State()


class EditRecipient(StatesGroup):
    """Renaming a person.

    Changing a DATE reuses AddOccasion's month -> day -> year -> confirm
    sub-flow rather than duplicating it; the FSM data carries the occasion
    being edited. Two states here instead of six.
    """

    choosing_label = State()
    entering_label = State()


class Browse(StatesGroup):
    """Looking through the catalogue without a reminder to start from.

    NO text-waiting states at all, which is why this group adds nothing to
    the surface Cancel and /start have to be proven against: every step is a
    button. A search box would change that, and is deliberately not here.
    """

    #: A page of bouquets. The cursor stack lives in FSM data, so paging
    #: backwards needs no second query shape.
    listing = State()
    #: One bouquet, shown as the shop's own post.
    viewing = State()


class PlaceOrder(StatesGroup):
    """Ordering a bouquet. Picker-driven, same discipline as AddOccasion.

    TWO text-waiting states and no more: the address and the landmark. Dates and
    hours are buttons because a free-text delivery time in uz/ru produces
    garbage no parser fixes -- and because every text-waiting state is somewhere
    Cancel and /start have to be proven to still win.

    `waiting_location` waits for a Telegram location message, not text, so it is
    NOT a catch-all: it filters on F.location and lets everything else fall
    through to nav.
    """

    choosing_date = State()
    choosing_hour = State()
    choosing_location = State()
    entering_address = State()
    waiting_location = State()
    entering_landmark = State()
    #: Who takes delivery. Offered as a one-tap button when the order came from
    #: a reminder and the bot already knows the name; free text otherwise.
    entering_recipient_name = State()
    #: NOT skippable, and only reached when the number is still missing. This is
    #: the moment it is actually needed and the moment the customer understands
    #: why it is being asked -- and it sits BEFORE the confirmation screen, not
    #: after the confirm tap, so the number appears on the screen they approve
    #: and nothing is interposed between that tap and the insert.
    entering_phone = State()
    confirming = State()
