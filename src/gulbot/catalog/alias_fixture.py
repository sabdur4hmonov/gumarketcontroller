"""The hashtag alias fixture: synonyms -> canonical tag.

A FIXTURE, not a migration. Two reasons:

  * a migration runs once per database, so correcting a bad synonym would need
    a new migration every time; a fixture is re-seedable;
  * this is the shop's vocabulary, not the application's schema. It will be
    edited by whoever knows what customers actually type, which is not whoever
    writes migrations.

Bump FIXTURE_VERSION when the table below changes. Seeded rows record the
version that wrote them, so a reseed can tell its own rows from ones a human
added by hand -- and never overwrites the latter.

The left-hand side is what a CUSTOMER might type or a shop might tag. The
right-hand side is the canonical Uzbek Latin tag. Aliases must already be in
normalized form: `seed_hashtag_aliases` normalises both sides and refuses a
pair that collapses to the same key, which would be a no-op row.
"""

from __future__ import annotations

from typing import Final

FIXTURE_VERSION: Final = 1

#: alias -> canonical. Latin Uzbek, Cyrillic (Russian and Uzbek), and English.
#: Kept flat and boring on purpose: this file is meant to be edited by hand.
ALIASES: Final[dict[str, str]] = {
    # --- rose -> atirgul ---------------------------------------------------
    "roza": "atirgul",
    "роза": "atirgul",
    "розы": "atirgul",
    "rose": "atirgul",
    "roses": "atirgul",
    "атиргул": "atirgul",
    "gulatirgul": "atirgul",
    # --- tulip -> tyulpan --------------------------------------------------
    "tulip": "tyulpan",
    "tulips": "tyulpan",
    "тюльпан": "tyulpan",
    "тюльпаны": "tyulpan",
    "лале": "tyulpan",
    "lola gul": "tyulpan",
    "тюлпан": "tyulpan",
    # --- chrysanthemum -> xrizantema ---------------------------------------
    "хризантема": "xrizantema",
    "хризантемы": "xrizantema",
    "chrysanthemum": "xrizantema",
    "krizantema": "xrizantema",
    # --- carnation -> chinnigul --------------------------------------------
    "гвоздика": "chinnigul",
    "carnation": "chinnigul",
    "чиннигул": "chinnigul",
    # --- peony -> pion -----------------------------------------------------
    "пион": "pion",
    "пионы": "pion",
    "peony": "pion",
    "peonies": "pion",
    # --- lily -> nilufar ---------------------------------------------------
    "лилия": "nilufar",
    "lily": "nilufar",
    "нилуфар": "nilufar",
    # --- gerbera -----------------------------------------------------------
    "гербера": "gerbera",
    "герберы": "gerbera",
    # --- generic bouquet -> buket ------------------------------------------
    "букет": "buket",
    "bouquet": "buket",
    "guldasta": "buket",
    "гулдаста": "buket",
    # --- occasion tags -----------------------------------------------------
    "день рождения": "tugilgankun",
    "birthday": "tugilgankun",
    "tugilgan kun": "tugilgankun",
    "свадьба": "toy",
    "wedding": "toy",
    "туй": "toy",
    "8 март": "8mart",
    "8 mart": "8mart",
}
