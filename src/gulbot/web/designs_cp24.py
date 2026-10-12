"""Original CP24 artwork, previewable before the post-CP23 CHECK migration.

This catalog does not admit designs into database-backed creation. Activation
adds these keys to PAGE_TEMPLATES only after CP23 has landed and its additive
migration has widened the CHECK. Premium policy lives in services/premium.py.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Design:
    name: str
    color: str
    icon: str


CP24_DESIGNS: Final = {
    "zarhal": Design("Zarhal kecha", "#111315", "◆"),
    "zumrad": Design("Zumrad saroy", "#075448", "◇"),
    "anor": Design("Anor ipagi", "#ef6b52", "✺"),
    "girih": Design("Girih osmoni", "#101b49", "✦"),
    "gulshabnam": Design("Gul shabnami", "#ece4ff", "❀"),
    "sitrus": Design("Sitrus bayram", "#fff02e", "☀"),
    "maktub": Design("Mehr maktubi", "#d4bea0", "✉"),
    "chiziq": Design("Chiziq galereya", "#ececea", "▤"),
    "sahro": Design("Sahro quyoshi", "#c56840", "◒"),
    "kamalak": Design("Kamalak orzusi", "#bbe9ef", "🌈"),
    "ilm": Design("Ilm nuri", "#673d86", "⌑"),
    "anjuman": Design("Anjuman studiya", "#1e63c4", "▥"),
    "navroz": Design("Navro'z nafasi", "#81d36a", "✿"),
    "qish": Design("Qish yulduzi", "#b8e6f5", "❄"),
    "lavha": Design("Lavha jurnal", "#d8f06b", "▣"),
    "kadr": Design("Kadr xotira", "#f18a6c", "▧"),
    "zinalar": Design("Zinalar oltini", "#203a57", "▱"),
    "sokin": Design("Sokin bog'", "#f3ede3", "◌"),
    "marjon": Design("Marjon yurak", "#ffc4b8", "♡"),
    "moviy": Design("Moviy tantana", "#2851c7", "✧"),
}

PHOTO_FIRST: Final = frozenset({"foto", "lavha", "kadr"})
