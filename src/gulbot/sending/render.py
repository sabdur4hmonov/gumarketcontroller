"""Turning a due group into reminder text.

CP6 sends BARE TEXT. No bouquet suggestions, no catalogue lookup, no inline
order button. CP9 attaches suggestions by widening the transport and this
renderer -- the dispatcher does not change, because it only ever calls a
`Renderer` and a `Transport`.

Two shapes, because one date and several dates read very differently:

    one   Ertaga Onamning tug'ilgan kuni — 5-sentabr.
    many  Yaqin kunlarda:
          • Onam — tug'ilgan kun, 5-sentabr (ertaga)
          • Opa  — tug'ilgan kun, 7-sentabr (3 kundan keyin)

Naming the KIND is only possible because occasions carry one; before that fix
every reminder could say no more than "Onam — 05.09".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from gulbot.i18n import t
from gulbot.models.occasion import RecipientType
from gulbot.scheduling.occurrences import TASHKENT
from gulbot.sending.dispatcher import DueGroup
from gulbot.utils.render import (
    addressed_label,
    escape,
    format_date_long,
)


@dataclass(frozen=True)
class _Entry:
    """One occasion as the reminder text needs it."""

    label: str
    #: A custom label cannot take a possessive suffix, so the single-reminder
    #: sentence is reshaped around it. See utils.render.addressed_label.
    is_custom: bool
    #: Inside a sentence: "Onangizning tug'ilgan KUNI".
    kind_possessive: str
    #: Standing alone in a list item: "tug'ilgan kun".
    kind_plain: str
    date: str
    days: int


def describe_when(days_ahead: int, lang: str, *, capitalised: bool = False) -> str:
    """ "today" / "tomorrow" / "in N days", in the register the caller needs."""
    prefix = "reminder.whencap" if capitalised else "reminder.when"
    if days_ahead <= 0:
        return t(f"{prefix}.today", lang)
    if days_ahead == 1:
        return t(f"{prefix}.tomorrow", lang)
    return t(f"{prefix}.in_days", lang, days=days_ahead)


def render_reminder(group: DueGroup, *, today: date | None = None) -> str:
    """One message covering every occasion in the group."""
    lang = group.lang
    send_day = today or min(r.due_at_utc for r in group.rows).astimezone(TASHKENT).date()

    by_occasion = {occasion.id: occasion for occasion in group.occasions}
    recipients = {recipient.id: recipient for recipient in group.recipients}

    entries: list[_Entry] = []
    for row in sorted(group.rows, key=lambda r: (r.occurrence_year, r.offset_days)):
        occasion = by_occasion.get(row.occasion_id)
        if occasion is None:  # pragma: no cover - context is loaded together
            continue
        occurrence = send_day - timedelta(days=row.offset_days)
        # The recipient is the source of truth for both; an occasion carries a
        # copy of each, used only if the recipient row is somehow absent.
        recipient = recipients.get(occasion.recipient_id)
        raw_label = recipient.label if recipient else occasion.label
        recipient_type = recipient.type if recipient else occasion.type
        entries.append(
            _Entry(
                label=escape(addressed_label(raw_label, recipient_type, lang)),
                is_custom=recipient_type == RecipientType.CUSTOM.value,
                kind_possessive=t(f"occkind.poss.{occasion.kind}", lang),
                kind_plain=t(f"occkind.{occasion.kind}", lang).lower(),
                date=format_date_long(occurrence.day, occurrence.month, None, lang),
                days=(occurrence - send_day).days,
            )
        )

    # De-duplicate while preserving order: a merged group can legitimately hold
    # two rows for the same person and date at different offsets.
    seen: dict[tuple[str, str], _Entry] = {}
    for entry in entries:
        seen.setdefault((entry.label, entry.date), entry)
    # Soonest first. Sorting by offset_days would put a -3 reminder above a -1
    # one, listing next week ahead of tomorrow.
    unique = sorted(seen.values(), key=lambda e: e.days)

    heading = t("reminder.heading", lang)
    footer = t("reminder.footer", lang)

    if len(unique) == 1:
        only = unique[0]
        # A preset takes the possessive sentence; a custom label takes the
        # appositive one, which needs no suffix and so is safe for any text.
        body = t(
            "reminder.single_custom" if only.is_custom else "reminder.single",
            lang,
            when=describe_when(only.days, lang, capitalised=True),
            label=only.label,
            kind=only.kind_plain if only.is_custom else only.kind_possessive,
            date=only.date,
        )
    else:
        lines = [
            t(
                "reminder.item",
                lang,
                label=entry.label,
                kind=entry.kind_plain,
                date=entry.date,
                when=describe_when(entry.days, lang),
            )
            for entry in unique
        ]
        body = t("reminder.merged_intro", lang) + "\n" + "\n".join(lines)

    return f"{heading}\n\n{body}\n\n{footer}"
