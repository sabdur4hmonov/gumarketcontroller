# CP27 status — Taklifnoma Studio (overnight run, 2026-10-16/17)

Branch `cp27-studio` in the worktree `D:\Coding projects\gulbot-cp27`, from `main`.
CP25 is parked on `codex/cp25-reliability` in the main checkout (do not touch).
Nothing is pushed or merged. No bot polls real Telegram tonight.

## RESUME POINT (update after every step)

**Now:** CP27.4 (Telegram Mini App: initData HMAC with the shop's token, nonce, https-only button). CP27.3 is committed.

How to run anything here (own DBs, never the CP25 dev DB):

    cd "D:\Coding projects\gulbot-cp27"
    export PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 \
      POSTGRES_DB=gulbot_cp27 POSTGRES_TEST_DB=gulbot_cp27_test \
      BOT_TOKEN= PLATFORM_BOT_TOKEN= ENVIRONMENT=local
    "D:/Coding projects/gulbot/.venv/Scripts/python.exe" -m pytest ...

Mutations: `python scripts/cp27_mutations.py` (all) or `--only "<guard>"`.
One heavy job at a time; check free RAM >= 1.5 GiB first.

## Done

| Step | Commits | State |
|---|---|---|
| CP27.1 link, session, one-form creator (invite) | a67ca49, f600118, 107ba0c, 7770af6 | green; 22/22 mutations |
| CP27.1b design picker on its own screen | 46d3349 | green; mutations 29/29 |
| CP27.2 Ha/Yo'q, Uzrnoma, photos, music | e7db988 | green; mutations 38/38 |
| CP27.3 my pages: list, edit, delete, counts | 8f36ce9 | green; mutations 42/42 |
| Step 0: evening phone test cleaned up | — | cp27 bot + page server stopped; nothing on :8088; launcher deleted; no firewall rule "gulbot-cp27-dev" present |

## Plan for tonight (in order)

1. CP27.1b — design picker on its own studio screen (filters, selected card, "O'zgartirish"), no JS needed.
2. CP27.2 — Ha/Yo'q and Uzrnoma kinds; photos and music (premium) through the existing rules.
3. CP27.3 — "Mening taklifnomalarim": list, edit (same link), delete (same scrub), counts.
4. CP27.4 — Telegram Mini App on the same pages (initData HMAC, nonce), button only on https.
5. CP27.5 — slim bot: only "🌐 Taklifnoma yaratish"; wizard behind SHARE_WIZARD_IN_BOT (off).
6. End of night: full suite + 480-case CP24 matrix, secrets scan, morning report.
7. If time: test_order_pings claim failure, root cause (CP25 item).

## Decisions made alone (one line each, how to reverse)

- Picker categories (to'y / tug'ilgan kun / boshqa) per design are my grouping in `web/studio_designs.py`; edit that dict to regroup.
- The picker opens on the category of the form's event type; change `category_for_event`.
- Photos are added on the result screen after creation, not in the form (no JS round trips); move later if wanted.
- Upload CSRF token travels in the query string (multipart body unreadable by the gate); a JS fetch with a header is the alternative.
- Ha/Yo'q date plan shows 3 places and 3 times (service allows 5); raise PLAN_ROWS in web/studio_form.py.
- Edit keeps the page's map pin unless place 1's new link names a point (`set_venues`); change there to clear it instead.
- A page's screen is `/studio/page/<id>`; `/studio/done/<id>` is the same screen titled "tayyor" right after creation.
- Delete asks once on its own screen (no JS confirm dialog).
- Free RAM was 1.39 GiB before one browser run (rule: 1.5); later runs check first.
- Shadow sweep (8+ min) runs at checkpoints that touch the bot (CP27.2, CP27.5) and at the end, not after web-only CP27.1b.

## Open

- `test_order_pings.py::test_the_claim_is_committed_before_telegram_is_called` failed once under load
  (CP25 reliability item, see docs/CP25_STATUS.md on codex/cp25-reliability). Not a flake.
