"""Generate original CP24 360px evidence and a cold-weight ledger.

Run from this worktree, after the focused browser gate. Uses installed Chrome,
never downloads a browser, never opens a DB or sends a Telegram message.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tests.share_page_cp24_browser import audit_case, browser_world  # noqa: E402

from gulbot.models.share_page import PAGE_LANGUAGES, PageKind  # noqa: E402
from gulbot.services.premium import CP24_PREMIUM_TEMPLATES  # noqa: E402
from gulbot.web.designs_cp24 import CP24_DESIGNS  # noqa: E402


def main() -> None:
    target = ROOT / "docs" / "screenshots" / "cp24"
    target.mkdir(parents=True, exist_ok=True)
    ledger: dict[str, Any] = {}
    with browser_world() as (browser, origin):
        for theme, design in CP24_DESIGNS.items():
            weights = []
            for kind in PageKind:
                for lang in PAGE_LANGUAGES:
                    image = target / f"{theme}-{kind}-360.png" if lang == "uz" else None
                    seal = (
                        target / f"{theme}-seal-360.png"
                        if kind == PageKind.INVITE and lang == "uz"
                        else None
                    )
                    result = audit_case(
                        browser,
                        origin,
                        theme,
                        str(kind),
                        lang,
                        worst=False,
                        screenshot=image,
                        seal_screenshot=seal,
                    )
                    assert result["status"] == 200
                    assert result["width"] == 360 and not result["overflow"], (
                        theme,
                        kind,
                        lang,
                        result["overflow"],
                    )
                    assert not result["external"] and not result["errors"] and not result["csp"]
                    assert not result["missingImages"]
                    assert not result["seal_overflow"]
                    assert result["font_bytes"] <= 110 * 1024
                    assert result["chrome_bytes"] <= 180 * 1024
                    weights.append(
                        {
                            "kind": str(kind),
                            "lang": lang,
                            "chrome_bytes": result["chrome_bytes"],
                            "fonts_bytes": result["font_bytes"],
                            "fixture_gallery_bytes": result["photo_bytes"],
                            "assets": result["assets"],
                        }
                    )
            ledger[theme] = {
                "name": design.name,
                "premium": theme in CP24_PREMIUM_TEMPLATES,
                "max_chrome_bytes": max(w["chrome_bytes"] for w in weights),
                "max_fonts_bytes": max(w["fonts_bytes"] for w in weights),
                "visits": weights,
            }
            print(
                f"{theme}: screenshots complete; "
                f"max chrome {ledger[theme]['max_chrome_bytes']} bytes",
                flush=True,
            )
    (target / "weights.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    rows = []
    for theme, item in ledger.items():
        pictures = "".join(
            f'<a href="screenshots/cp24/{theme}-{k}-360.png">'
            f'<img src="screenshots/cp24/{theme}-{k}-360.png" width="180" '
            f'loading="lazy" alt="{html.escape(item["name"])}: {k}"></a>'
            for k in ("invite", "yesno", "apology")
        )
        gift = "Premium" if item["premium"] else "Free"
        rows.append(
            f"<article><h2>{html.escape(item['name'])}</h2>"
            f"<p><code>{theme}</code> · {gift} · "
            f"{item['max_chrome_bytes'] / 1024:.1f} KiB cold</p>"
            f'<div class="previews">{pictures}</div>'
            f'<a href="screenshots/cp24/{theme}-seal-360.png">Sealed envelope</a></article>'
        )
    document = (
        (
            '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta '
            'name="viewport" content="width=device-width"><meta name="robots" '
            'content="noindex"><title>CP24 — 20 original share-page designs</t'
            'itle><link rel="stylesheet" href="cp24-designs.css"></head><body>'
            "<header><p>GULBOT · CP24 DESIGN REVIEW</p><h1>Twenty new ways to "
            "share a moment.</h1><p>Bright originals, three page types, 360 px"
            ". Activated after CP23 with the CP24 CHECK migration.</p><p>Click ea"
            "ch image for the full screenshot. Columns: Taklifnoma, Ha/Yo‘q, U"
            'zrnoma. Each also has a sealed-envelope screenshot.</p><a href="s'
            'creenshots/cp24/weights.json">Cold byte ledger: 240 fresh-context'
            " visits in four languages</a></header><main>"
        )
        + "".join(rows)
        + "</main></body></html>"
    )
    (ROOT / "docs" / "cp24-designs.html").write_text(document, encoding="utf-8")
    (ROOT / "docs" / "cp24-designs.css").write_text(
        (
            "body{margin:0;background:#eef1e8;color:#203c31;font:16px/1.6 syst"
            "em-ui,sans-serif}header,main{max-width:1120px;margin:auto;padding"
            ":32px}header{border-bottom:3px solid #b5cf5b}h1{font-size:clamp(3"
            "2px,6vw,60px);line-height:1.1;max-width:800px}h2{margin:0;font-si"
            "ze:28px}article{background:#fffef7;padding:28px;margin:30px 0;bor"
            "der:1px solid #b4c6ad;border-radius:16px}a{color:#255e48}.preview"
            "s{display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap;mar"
            "gin:24px 0}.previews a{flex:1;min-width:160px;max-width:360px}.pr"
            "eviews img{width:100%;height:460px;object-fit:cover;object-positi"
            "on:top;border-radius:8px;border:1px solid #cfdbbf}code{font-size:"
            "14px}@media(max-width:500px){header,main{padding:18px}article{pad"
            "ding:18px}.previews a{min-width:100%;}.previews img{height:600px}"
            "}"
        ),
        encoding="utf-8",
    )
    table = [
        "# CP24 design evidence",
        "",
        (
            "Generated from original bounded samples, at 360 CSS px, in a fres"
            "h Chrome context per visit."
        ),
        (
            "Gallery fixtures are authored SVG flowers, not customer photos. A"
            "ll links below are local."
        ),
        "",
        (
            "All new designs are activated after CP23 by the single addi"
            "tive CHECK-widening migration."
        ),
        "",
        (
            "| Design | Gift | Cold chrome KiB (max of 3 kinds × 4 languages) "
            "| Fonts KiB | Screenshots |"
        ),
        "|---|---|---:|---:|---|",
    ]
    for theme, item in ledger.items():
        links = " · ".join(
            f"[{k}](screenshots/cp24/{theme}-{k}-360.png)"
            for k in ("invite", "yesno", "apology", "seal")
        )
        gift = "Premium" if item["premium"] else "Free"
        table.append(
            f"| {item['name']} (`{theme}`) | {gift} | "
            f"{item['max_chrome_bytes'] / 1024:.1f} | "
            f"{item['max_fonts_bytes'] / 1024:.1f} | {links} |"
        )
    table += [
        "",
        "[Visual index](cp24-designs.html) · [Full byte ledger](screenshots/cp24/weights.json)",
        "",
        (
            "Chrome includes HTML, requested CSS/JS and fonts, measured uncomp"
            "ressed. The ledger lists every request and separately counts the "
            "small SVG gallery fixtures. Actual customer photo payloads can be"
            " larger (existing per-photo 1.5 MB stored cap). Screenshot PNGs a"
            "re not page dependencies."
        ),
    ]
    (ROOT / "docs" / "CP24_EVIDENCE.md").write_text("\n".join(table) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
