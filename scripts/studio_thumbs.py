"""Draw the studio design picker's thumbnails (CP27.1).

Each design's invitation cover, opened at 360 px in headless Chrome through
the CP24 browser harness (sample text, our own CSS and fonts, CSP applied),
then shrunk to 150x267 WebP in src/gulbot/web/static/studio/thumbs/<key>.webp.
Run it again whenever a design's look changes or a design is added;
tests/test_studio_web.py fails while any design has no thumbnail.

    python scripts/studio_thumbs.py [--only key ...]
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from PIL import Image  # noqa: E402
from tests.share_page_cp24_browser import browser_world  # noqa: E402

from gulbot.web.render import STATIC, THEME_NAMES  # noqa: E402

OUT = STATIC / "studio" / "thumbs"
SIZE = (150, 267)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args()
    keys = [key for key in THEME_NAMES if not args.only or key in args.only]
    OUT.mkdir(parents=True, exist_ok=True)
    with browser_world() as (browser, base):
        context = browser.new_context(
            viewport={"width": 360, "height": 640}, device_scale_factor=1, reduced_motion="reduce"
        )
        page = context.new_page()
        for key in keys:
            page.goto(f"{base}/case?theme={key}&kind=invite&lang=uz", wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(400)
            shot = Image.open(io.BytesIO(page.screenshot(type="png"))).convert("RGB")
            thumb = shot.resize(SIZE, Image.Resampling.LANCZOS)
            target = OUT / f"{key}.webp"
            thumb.save(target, "WEBP", quality=72, method=6)
            print(f"{key}: {target.stat().st_size} bytes")
        context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
