"""CP24 focused assertion-only mutation proof; restores every byte in finally.

Run only when the focused browser/render tests have finished. Uses this
worktree's .env and test DB; never runs a full gate or a shared migration probe.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "CP24_MUTATIONS.json"
UNIT = "tests/test_web_cp24.py::"
BROWSER = (
    "tests/test_web_cp24_browser.py::test_worst_case_at_360_has_no_overflow_or_foreign_requests"
)
HTTP = UNIT + "test_every_design_kind_language_renders_200_without_foreign_assets"
ART = UNIT + "test_artwork_fonts_and_bytes_are_self_contained[zarhal]"
REGISTRY = "src/gulbot/web/designs_cp24.py"
RENDER = "src/gulbot/web/render.py"
THEME = "src/gulbot/web/static/css/theme-zarhal.css"


@dataclass(frozen=True)
class Mutant:
    name: str
    file: str
    old: str
    new: str
    test: str


def mutants() -> list[Mutant]:
    source = (ROOT / REGISTRY).read_text(encoding="utf-8")
    moviy = next(line + "\n" for line in source.splitlines() if '"moviy": Design' in line)
    svg_file = "src/gulbot/web/templates/_ornaments_cp24.html"
    svg = (ROOT / svg_file).read_text(encoding="utf-8")
    slot = re.search(r'(\{% if theme == "zarhal" %\}\n)(.*?)(\n\{% elif)', svg, re.S)
    assert slot is not None
    geometry = slot[2]
    return [
        Mutant(
            "lost design",
            REGISTRY,
            moviy,
            "",
            UNIT + "test_twenty_new_keys_never_replace_original_designs",
        ),
        Mutant(
            "old key overwritten",
            REGISTRY,
            '"zarhal": Design',
            '"milliy": Design',
            UNIT + "test_twenty_new_keys_never_replace_original_designs",
        ),
        Mutant("empty picker name", REGISTRY, '"Zarhal kecha"', '""', ART),
        Mutant("empty picker icon", REGISTRY, '"◆"', '""', ART),
        Mutant("meta palette mismatch", REGISTRY, "#111315", "#010203", ART),
        Mutant(
            "unlicensed display face",
            THEME,
            '--font-display: "Cormorant Garamond"',
            '--font-display: "Unlicensed Face"',
            ART,
        ),
        Mutant(
            "incomplete Uzbek fallback",
            THEME,
            '--font-display-uzc: "Cormorant Garamond"',
            '--font-display-uzc: "Prata"',
            ART,
        ),
        Mutant(
            "foreign CSS import",
            THEME,
            ":root {",
            '@import url("https://example.invalid/font.css");\n:root {',
            ART,
        ),
        Mutant("theme byte budget exceeded", THEME, ":root {", " " * 5000 + ":root {", ART),
        Mutant(
            "missing font declaration",
            "src/gulbot/web/static/css/fonts_cp24.css",
            'font-family: "Lora"',
            'font-family: "Missing"',
            UNIT + "test_cp24_font_declarations_have_licensed_complete_families",
        ),
        Mutant(
            "gift selection changed",
            "src/gulbot/services/premium.py",
            '        "zarhal",',
            '        "sitrus",',
            UNIT + "test_cp24_gift_selection_is_twelve_premium_and_eight_free",
        ),
        Mutant(
            "new envelope removed",
            RENDER,
            'theme == "konvert" or theme in CP24_DESIGNS',
            'theme == "konvert"',
            ART,
        ),
        Mutant(
            "creator seal replaced",
            "src/gulbot/web/templates/_base.html",
            "{{ v.seal_letter }}",
            "XX",
            BROWSER + "[uz_cyrl-yesno-zarhal]",
        ),
        Mutant(
            "unsafe inline CSP",
            "src/gulbot/web/app.py",
            "style-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "tests/test_web_pages.py::test_the_csp_allows_nothing_inline_and_nothing_foreign",
        ),
        Mutant(
            "autoescape disabled",
            RENDER,
            'select_autoescape(["html"], default=True, default_for_string=True)',
            "False",
            HTTP + "[uz-invite-sitrus]",
        ),
        Mutant(
            "lead photo duplicated",
            RENDER,
            "(photos[1:] if framed else photos)",
            "(photos if framed else photos)",
            UNIT
            + "test_photo_first_consumes_one_gallery_photo_and_obeys_gallery_switch[invite-lavha]",
        ),
        Mutant(
            "disabled gallery leaks lead",
            RENDER,
            '(page.template == "foto" or page.show_gallery)',
            "True",
            UNIT
            + "test_photo_first_consumes_one_gallery_photo_and_obeys_gallery_switch[invite-lavha]",
        ),
        Mutant(
            "shop label cannot shrink",
            "src/gulbot/web/static/css/base.css",
            ".shop-brand > span:last-child { min-width: 0; overflow-wrap: anywhere; }",
            "",
            BROWSER + "[uz-invite-milliy]",
        ),
        Mutant(
            "long title/wish overflows",
            "src/gulbot/web/static/css/base.css",
            ".eyebrow, .wish-author { overflow-wrap: anywhere; }",
            "",
            BROWSER + "[uz-invite-milliy]",
        ),
        Mutant(
            "Cyrillic colours corrupted",
            "src/gulbot/web/sections.py",
            'to_cyrillic(_names["uz"])',
            'to_cyrillic("Qora")',
            UNIT + "test_palette_labels_cover_all_four_languages",
        ),
        Mutant(
            "audio context before tap",
            "src/gulbot/web/static/js/music.js",
            "var ctx = null;",
            "var ctx = new Ctx();",
            BROWSER + "[uz-yesno-zarhal]",
        ),
        Mutant(
            "guest counter removed",
            "src/gulbot/web/templates/invite.html",
            'id="rsvp-count"',
            'id="rsvp-total"',
            HTTP + "[uz-invite-sitrus]",
        ),
        Mutant(
            "escaping button removed",
            "src/gulbot/web/templates/yesno.html",
            'id="no"',
            'id="not-no"',
            HTTP + "[uz-yesno-sitrus]",
        ),
        Mutant(
            "HTML language lost",
            RENDER,
            '"html_lang": strings.HTML_LANG[lang]',
            '"html_lang": "en"',
            HTTP + "[uz-invite-sitrus]",
        ),
        Mutant(
            "maximum seal text overflows",
            "src/gulbot/web/static/css/base.css",
            ".seal-max { font-size: 12px; padding: 0; }",
            "",
            BROWSER + "[uz-yesno-zarhal]",
        ),
        Mutant(
            "footer ink matches background",
            THEME,
            "--shop-ink: #ffffff;",
            "--shop-ink: #111315;",
            UNIT + "test_shop_brand_and_primary_buttons_have_readable_contrast[zarhal]",
        ),
        Mutant(
            "gold button ink matches fill",
            THEME,
            "--accent-ink: #101010;",
            "--accent-ink: #d8bc72;",
            UNIT + "test_shop_brand_and_primary_buttons_have_readable_contrast[zarhal]",
        ),
        Mutant(
            "ornament left blank",
            svg_file,
            geometry,
            "",
            UNIT + "test_twenty_new_ornaments_are_drawn_and_distinct",
        ),
    ]


class MutationResult(TypedDict):
    guard: str
    file: str
    test: str
    assertion_caught: bool
    exit_code: int


def main() -> None:
    from gulbot.config import get_settings

    os.chdir(ROOT)
    settings = get_settings()
    if settings.postgres_test_db != "gulbot_cp24_test" or settings.redis_db_test != 11:
        raise SystemExit("CP24 mutation proof requires its own database.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", nargs="+", help="Recheck named guards; retain prior results explicitly"
    )
    args = parser.parse_args()
    all_mutants = mutants()
    known = {m.name: m for m in all_mutants}
    if args.only and set(args.only) - known.keys():
        raise SystemExit("Unknown mutation guard.")
    selected = [m for m in all_mutants if not args.only or m.name in args.only]
    results: list[MutationResult] = []
    if args.only and REPORT.exists():
        for result in json.loads(REPORT.read_text(encoding="utf-8"))["results"]:
            prior = known.get(result["guard"])
            if (
                prior
                and prior.name not in args.only
                and result["file"] == prior.file
                and result["test"] == prior.test
            ):
                results.append(result)
    for mutant in selected:
        file = ROOT / mutant.file
        original = file.read_bytes()
        source = file.read_text(encoding="utf-8")
        if mutant.old not in source:
            raise SystemExit(f"Mutant anchor missing: {mutant.name}")
        try:
            file.write_text(source.replace(mutant.old, mutant.new, 1), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", mutant.test, "-x", "--tb=short"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"},
            )
            output = completed.stdout + completed.stderr
            caught = completed.returncode == 1 and bool(
                re.search(r"E\s+(?:assert|AssertionError)", output)
            )
            results.append(
                {
                    "guard": mutant.name,
                    "file": mutant.file,
                    "test": mutant.test,
                    "assertion_caught": caught,
                    "exit_code": completed.returncode,
                }
            )
            print(f"{mutant.name}: {'assertion caught' if caught else 'NOT PROVEN'}", flush=True)
            if not caught:
                print(output[-2500:])
        finally:
            file.write_bytes(original)
        if file.read_bytes() != original:
            raise SystemExit("Mutation restore failed.")
    REPORT.write_text(
        json.dumps(
            {
                "caught": sum(r["assertion_caught"] for r in results),
                "total": len(results),
                "results": results,
                "last_rechecked_guards": [m.name for m in selected],
                "report_scope": "Accumulated per-guard proof" if args.only else "Complete sweep",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if not all(r["assertion_caught"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
