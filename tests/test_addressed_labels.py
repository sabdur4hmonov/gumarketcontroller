"""The bot speaks in the SECOND person about the customer's people.

Recipient presets are stored first person, because that is how the customer
picks them: the button says "Onam", meaning "my mother". Rendering that stored
word straight into a sentence the BOT speaks makes the bot say "my mother" --
found on a real reminder, not by reading the code.

    before   Ertaga Onamning tug'ilgan kuni — 5-sentabr.
    after    Ertaga Onangizning tug'ilgan kuni — 5-sentabr.

CUSTOM LABELS ARE NEVER CONVERTED. "Aziza singlim" is the customer's own words
for their own person, and already carries a first-person suffix that would have
to be stripped and re-fitted under vowel harmony -- on free text that may be
multi-word, a bare name, or not Uzbek. Echoing it verbatim is quoting the
customer, which is correct. The SENTENCE is reshaped instead, into the same
appositive form the merged list already uses, so no possessive is needed:

    custom   Ertaga — Aziza singlim, tug'ilgan kun, 5-sentabr.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from gulbot.i18n.catalog import CATALOG
from gulbot.models.occasion import RecipientType
from gulbot.sending.render import render_reminder
from gulbot.utils.render import addressed_label

#: Exactly the mapping agreed for this fix. Spelled out rather than derived from
#: the catalog, so a typo in the catalog fails here instead of being mirrored.
SECOND_PERSON = {
    RecipientType.MOTHER: "Onangiz",
    RecipientType.SPOUSE: "Turmush o‘rtog‘ingiz",
    RecipientType.OLDER_SISTER: "Opangiz",
    RecipientType.YOUNGER_SISTER: "Singlingiz",
    RecipientType.PATERNAL_AUNT: "Ammangiz",
    RecipientType.MATERNAL_AUNT: "Xolangiz",
}


@pytest.mark.parametrize(("preset", "expected"), list(SECOND_PERSON.items()))
def test_each_preset_is_spoken_in_the_second_person(preset: RecipientType, expected: str) -> None:
    # The stored label is deliberately wrong here: the conversion must key on
    # the TYPE, never on the text, because a renamed preset always becomes
    # custom and matching on the string would mangle a real name.
    assert addressed_label("ignored stored text", preset.value, "uz") == expected


def test_every_preset_has_a_second_person_form() -> None:
    """Guards against adding a seventh preset and forgetting the catalog key.

    The button would then read "Bobom" and the reminder would say "Bobom" back,
    which is the exact bug this fix exists to remove.
    """
    missing = [
        preset.value
        for preset in RecipientType
        if preset is not RecipientType.CUSTOM and f"recipient.addr.{preset.value}" not in CATALOG
    ]
    assert not missing, f"presets with no second-person form: {missing}"


def test_the_agreed_mapping_covers_every_preset() -> None:
    """Guards the guard above: if a preset is added and this table is not
    updated, the parametrized test silently stops covering it."""
    assert set(SECOND_PERSON) | {RecipientType.CUSTOM} == set(RecipientType)


def test_a_custom_label_is_returned_untouched() -> None:
    for label in ("Aziza singlim", "Dilnoza", "best friend", "Аziza"):
        assert addressed_label(label, RecipientType.CUSTOM.value, "uz") == label


# --- through the real renderer ---------------------------------------------

TODAY = date(2026, 9, 4)


def make_group(label: str, recipient_type: str, *, extra: tuple | None = None):  # type: ignore[no-untyped-def]
    rows = [
        SimpleNamespace(
            occasion_id=1,
            occurrence_year=2026,
            offset_days=-1,
            due_at_utc=datetime(2026, 9, 4, 4, tzinfo=UTC),
        )
    ]
    occasions = [
        SimpleNamespace(id=1, recipient_id=1, label=label, kind="birthday", type=recipient_type)
    ]
    recipients = [SimpleNamespace(id=1, label=label, type=recipient_type)]
    if extra is not None:
        extra_label, extra_type = extra
        rows.append(
            SimpleNamespace(
                occasion_id=2,
                occurrence_year=2026,
                offset_days=-3,
                due_at_utc=datetime(2026, 9, 4, 4, tzinfo=UTC),
            )
        )
        occasions.append(
            SimpleNamespace(
                id=2, recipient_id=2, label=extra_label, kind="anniversary", type=extra_type
            )
        )
        recipients.append(SimpleNamespace(id=2, label=extra_label, type=extra_type))
    return SimpleNamespace(
        key="k",
        customer_id=1,
        shop_id=1,
        telegram_user_id=1,
        lang="uz",
        rows=tuple(rows),
        occasions=tuple(occasions),
        recipients=tuple(recipients),
    )


def test_a_preset_reminder_takes_the_possessive_second_person() -> None:
    body = render_reminder(make_group("Onam", RecipientType.MOTHER.value), today=TODAY)
    assert "Onangizning tug'ilgan kuni" in body
    assert "Onamning" not in body, "the bot is still speaking about its own mother"


def test_a_multi_word_preset_takes_the_suffix_cleanly() -> None:
    """All six forms end in -ngiz, so the -ning genitive attaches uniformly.
    Worth pinning: it is the reason no vowel-harmony branching is needed."""
    body = render_reminder(make_group("Turmush o'rtog'im", RecipientType.SPOUSE.value), today=TODAY)
    assert "Turmush o‘rtog‘ingizning" in body


def test_a_custom_reminder_uses_the_appositive_sentence() -> None:
    body = render_reminder(make_group("Aziza singlim", RecipientType.CUSTOM.value), today=TODAY)
    assert "Aziza singlim" in body, "the customer's own words must survive verbatim"
    assert "Aziza singlimning" not in body, "a possessive suffix was attached to free text"
    assert "— Aziza singlim," in body, "the appositive shape was not used"


def test_a_merged_reminder_addresses_every_recipient() -> None:
    body = render_reminder(
        make_group("Onam", RecipientType.MOTHER.value, extra=("Opa", "older_sister")),
        today=TODAY,
    )
    assert "Onangiz" in body and "Opangiz" in body
    assert "Onam —" not in body and "Opa —" not in body


def test_a_merged_reminder_leaves_a_custom_label_alone() -> None:
    """The list form needs no possessive, so a custom label is simply itself."""
    body = render_reminder(
        make_group("Onam", RecipientType.MOTHER.value, extra=("Aziza singlim", "custom")),
        today=TODAY,
    )
    assert "Onangiz" in body
    assert "Aziza singlim" in body


def test_a_custom_label_is_still_escaped() -> None:
    """Conversion must not become a hole in the HTML escaping. The bot sends
    with parse_mode=HTML and the label is free text."""
    body = render_reminder(make_group("<b>x</b>", RecipientType.CUSTOM.value), today=TODAY)
    assert "&lt;b&gt;x&lt;/b&gt;" in body
    assert "<b>x</b>" not in body


def test_nothing_here_changes_what_is_stored() -> None:
    """The fix is a rendering transform. `recipients.label` and
    `recipients.type` keep the values the customer chose, which is what the DB
    record and any admin-facing view show."""
    group = make_group("Onam", RecipientType.MOTHER.value)
    render_reminder(group, today=TODAY)
    assert group.recipients[0].label == "Onam"
    assert group.occasions[0].label == "Onam"
