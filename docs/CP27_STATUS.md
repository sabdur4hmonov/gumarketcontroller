# CP27 status — Taklifnoma Studio (overnight run, 2026-10-16/17)

Branch `cp27-studio` in the worktree `D:\Coding projects\gulbot-cp27`, from `main`.
CP25 is parked on `codex/cp25-reliability` in the main checkout (do not touch).
Nothing is pushed or merged. No bot polls real Telegram tonight.

## RESUME POINT (update after every step)

**Now:** CP27.1-27.5 done; waiting for the owner's PC test (docs/CP27_MORNING_REPORT.md). Next: owner feedback, then a phone/Mini App run on HTTPS.

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
| CP27.4 Telegram Mini App | c4a2fa3 | green; mutations 51/51 |
| CP27.5 slim bot (wizard behind SHARE_WIZARD_IN_BOT, off) | 0fbfeb3 | green; mutations 57/57 |
| End of night gate | 52bba4f | suite 7,367 passed + 1 fixed (.env.example); CP24 matrix + studio browser + infra 492 passed; secrets 0 |
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
- Mini App replay nonce = sha256 of the launch data's own hash, UNIQUE in `studio_webapp_uses` (one session per launch).
- The Mini App URL carries the shop id and bot @username; the shop id picks the key (wrong id = HMAC fails); the username only feeds the page's order link.
- Telegram Web (iframe) is not supported: `frame-ancestors 'none'` and SameSite=Lax stay; mobile/desktop Telegram apps only.
- The HMAC check is aiogram's `check_webapp_signature` (the bot's own library), tested against launch data crafted from Telegram's spec.
- SHARE_WIZARD_IN_BOT defaults OFF; tests/conftest.py pins it ON so the wizard's existing tests keep running; slim mode has its own tests and sweep.
- Slim mode keeps the wishes router (a notification with buttons); every other old wizard button answers with a studio link.
- "Mening sahifalarim" in the bot (old "mine" button) now sends the studio link; the list lives at /studio/pages.
- Shadow sweep (8+ min) runs at checkpoints that touch the bot (CP27.2, CP27.5) and at the end, not after web-only CP27.1b.

## Open

- CP25: DEV_UNLIMITED_PAGES (56309f1) is missing from `.env.example` on codex/cp25-reliability; `test_env_example_documents_every_setting` will fail there until one line is added.

- **order-pings claim test (CP25 item), investigated 2026-10-17:** the loaded failure was `assert [] == ['sending']`, an EMPTY list: the
  fake transport's send_photo never ran, so NO send happened. The message ("another connection could not see the claim") misreads that.
  Reproduced exactly by setting the fixture's due time 1 s ahead (`now() + interval '1 second'`); 1 s behind passes. Cause class: `committed_world`
  sets `due_at_utc = now()` by the POSTGRES clock (Docker's WSL VM) while the tick runs with `now_utc=datetime.now(UTC)` from the Windows host,
  against CONTRIBUTING's rule ("a due time explicitly in the past relative to the now the test passes in"); a VM clock ahead of the host under
  load leaves the row not yet due. Skew measured now: within +/-15 ms (not proven for the failing moment). Claim-before-send is NOT implicated.
  Proposed CP25 fix (not applied; CP25 is parked and not to be touched): insert `due_at_utc` from the host clock minus 1 s, and assert
  `observed` is non-empty with its own message before checking 'sending'. To record in docs/CP25_STATUS.md on codex/cp25-reliability.

- `test_order_pings.py::test_the_claim_is_committed_before_telegram_is_called` failed once under load
  (CP25 reliability item, see docs/CP25_STATUS.md on codex/cp25-reliability). Not a flake.
