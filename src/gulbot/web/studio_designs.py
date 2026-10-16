"""How Taklifnoma Studio's picker groups the forty designs (CP27.1b).

A design may sit in more than one category. This is a picker's grouping, not a
rule: any design still works for any page kind and event, exactly as in the bot.
tests/test_studio_picker.py fails if a design is added without a category.
"""

from __future__ import annotations

from typing import Final

#: Category key -> what the picker's filter button says.
CATEGORIES: Final = {"toy": "To‘y", "tugilgan": "Tug‘ilgan kun", "boshqa": "Boshqa"}
#: The free/premium filter.
TIERS: Final = {"all": "Hammasi", "free": "Bepul", "premium": "⭐ Premium"}

_TOY, _TUG, _BOSH = "toy", "tugilgan", "boshqa"

DESIGN_CATEGORIES: Final[dict[str, frozenset[str]]] = {
    "milliy": frozenset({_TOY}),
    "atlas": frozenset({_TOY}),
    "minimal": frozenset({_TOY, _BOSH}),
    "bog": frozenset({_TOY, _BOSH}),
    "romantik": frozenset({_TOY}),
    "oltin": frozenset({_TOY}),
    "quvnoq": frozenset({_TUG}),
    "tungi": frozenset({_TOY, _BOSH}),
    "pastel": frozenset({_TUG, _TOY}),
    "konvert": frozenset({_TOY}),
    "foto": frozenset({_TOY, _TUG}),
    "bold": frozenset({_TUG, _BOSH}),
    "geometrik": frozenset({_BOSH}),
    "akvarel": frozenset({_TOY}),
    "vintaj": frozenset({_TOY}),
    "oqqora": frozenset({_TOY, _BOSH}),
    "bolalar": frozenset({_TUG}),
    "suzani": frozenset({_TOY}),
    "neon": frozenset({_TUG, _BOSH}),
    "deco": frozenset({_TOY, _BOSH}),
    "zarhal": frozenset({_TOY}),
    "zumrad": frozenset({_TOY}),
    "anor": frozenset({_TOY}),
    "girih": frozenset({_TOY}),
    "gulshabnam": frozenset({_TOY}),
    "sitrus": frozenset({_TUG}),
    "maktub": frozenset({_TOY}),
    "chiziq": frozenset({_BOSH}),
    "sahro": frozenset({_TOY}),
    "kamalak": frozenset({_TUG}),
    "ilm": frozenset({_BOSH}),
    "anjuman": frozenset({_BOSH}),
    "navroz": frozenset({_BOSH, _TUG}),
    "qish": frozenset({_TUG, _BOSH}),
    "lavha": frozenset({_TUG, _BOSH}),
    "kadr": frozenset({_TUG, _BOSH}),
    "zinalar": frozenset({_TOY}),
    "sokin": frozenset({_TOY, _BOSH}),
    "marjon": frozenset({_TOY}),
    "moviy": frozenset({_TOY, _BOSH}),
}

#: Which category the picker opens on, from the form's event type.
_EVENT_CATEGORY: Final = {
    "wedding": _TOY,
    "nikoh": _TOY,
    "fotiha": _TOY,
    "anniversary": _TOY,
    "birthday": _TUG,
    "beshik": _TUG,
    "sunnat": _TUG,
}


def category_for_event(event_type: str) -> str:
    return _EVENT_CATEGORY.get(event_type, _BOSH)
