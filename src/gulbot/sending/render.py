"""Turning a due group into reminder text.

CP6 sends BARE TEXT. No bouquet suggestions, no catalogue lookup, no inline
order button. CP9 attaches suggestions by widening the transport and this
renderer -- the dispatcher does not change, because it only ever calls a
`Renderer` and a `Transport`.
"""

from __future__ import annotations

from datetime import date, timedelta

from gulbot.i18n import t
from gulbot.scheduling.occurrences import TASHKENT
from gulbot.sending.dispatcher import DueGroup
from gulbot.utils.render import escape, format_date


def describe_when(days_ahead: int, lang: str) -> str:
    if days_ahead <= 0:
        return t("reminder.when.today", lang)
    if days_ahead == 1:
        return t("reminder.when.tomorrow", lang)
    return t("reminder.when.in_days", lang, days=days_ahead)


def render_reminder(group: DueGroup, *, today: date | None = None) -> str:
    """One message covering every occasion in the group.

    A merged group lists each date with its own label, which is why CP5
    persists per-occasion rows rather than collapsing them at materialisation.
    """
    lang = group.lang
    send_day = today or min(r.due_at_utc for r in group.rows).astimezone(TASHKENT).date()

    by_occasion = {occasion.id: occasion for occasion in group.occasions}
    labels = {recipient.id: recipient.label for recipient in group.recipients}

    lines = []
    for row in sorted(group.rows, key=lambda r: (r.occurrence_year, r.offset_days)):
        occasion = by_occasion.get(row.occasion_id)
        if occasion is None:  # pragma: no cover - context is loaded together
            continue
        occurrence = send_day - timedelta(days=row.offset_days)
        label = labels.get(occasion.recipient_id, occasion.label)
        lines.append(
            t(
                "reminder.item",
                lang,
                label=escape(label),
                date=format_date(occurrence.day, occurrence.month, None),
                when=describe_when((occurrence - send_day).days, lang),
            )
        )

    body = "\n".join(dict.fromkeys(lines))
    return f"{t('reminder.heading', lang)}\n\n{body}\n\n{t('reminder.footer', lang)}"
