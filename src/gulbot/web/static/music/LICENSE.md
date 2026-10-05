# Music on Gulbot pages — license record

Gulbot pages may play one of the tracks below, if the page's creator picks one.
The music is **off by default** and plays **only after the visitor taps** the
music button. Pages never autoplay.

There are **no audio files**. Each track is a short melody written as notes in
`static/js/music.js` and synthesised in the visitor's browser by the Web Audio
API. No recording, sample, loop or sound font from anyone else is used, and no
existing song is copied or adapted.

| Track     | What it is                                    | Author                    | License |
|-----------|-----------------------------------------------|---------------------------|---------|
| `bahor`   | Light major-pentatonic tune, 104 bpm          | Original, written for Gulbot (CP17, 2026-10-05) | CC0 1.0 |
| `oqshom`  | Slow waltz in A minor, 84 bpm                 | Original, written for Gulbot (CP17, 2026-10-05) | CC0 1.0 |
| `tantana` | Bright celebratory tune, 120 bpm              | Original, written for Gulbot (CP17, 2026-10-05) | CC0 1.0 |

CC0 1.0 Universal: https://creativecommons.org/publicdomain/zero/1.0/ — the
authors waive all copyright to the extent possible under law. Shops and page
creators may use these tracks freely.

## What creators cannot do

Creators **cannot upload or link their own music**. The bot offers only the
tracks in this table, and the database accepts only their names
(`ck_share_pages_music_known`). This keeps copyrighted songs off the pages.

## Adding a track

1. Compose it yourself (or take one whose license allows this use and record
   that license here, with the source).
2. Add it to `TRACKS` in `static/js/music.js`, to `MUSIC_TRACKS` in
   `models/share_page.py`, and to the CHECK in a new migration.
3. Add a row to this table.
