"""The product's name, read from its one place (CP19).

The brand is not decided. `Settings.brand_name` (`BRAND_NAME`) holds it, and
everything a person reads -- the bot's texts through the `{brand}` placeholder,
the admin panel through the templates' `brand()`, the gone page, the calendar
file -- asks this function. tests/test_brand.py fails the build when the name
is typed anywhere else.
"""

from __future__ import annotations

from gulbot.config import get_settings


def brand_name() -> str:
    return get_settings().brand_name
