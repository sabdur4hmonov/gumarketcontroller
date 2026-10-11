# CP22 template gallery

Open [index.html](index.html) for the 20 actual caption renders and 10 original
Pillow overlay designs plus the unmodified photo option. All examples use an
original schematic bouquet. These are gallery renders, not Telegram UI captures.

`screenshots/` contains one browser screenshot per option (31 cards) and an
overview. They were captured with an installed Chrome in an isolated headless
profile at 1440×1200; no downloads or user browser state. Caption cards show
the exact visible text produced by the production renderer.

Regenerate from the repository root:

```
.venv/Scripts/python.exe scripts/gallery_cp22.py
node scripts/capture_cp22_gallery.cjs <installed-playwright-module-path> <chrome-executable>
```

The browser capture command needs an existing Playwright installation and
Chrome executable. It opens only the generated local HTML artifact. Original
fonts, their OFL licence and pinned hashes are in
`src/gulbot/announcements/assets/fonts/`.
