# CP27 — tonggi hisobot / morning report (2026-10-17)

## Egasi uchun (qisqa)

**Nima tayyor.** Taklifnoma Studiya to‘liq ishlaydi (kompyuterda sinab ko‘rish mumkin):

- Botda bitta tugma: **💌 Taklifnoma · Ha/Yo'q → 🌐 Taklifnoma yaratish** — bir martalik havola (15 daqiqa).
- Bitta sahifada **Taklifnoma, Ha/Yo‘q va Uzrnoma**: ismlar, sana, bir nechta joy (To‘yxona, Uy…, xarita havolasi bilan), xabar, musiqa ⭐.
- **Dizayn tanlash** endi alohida ekranda: turkumlar (To‘y / Tug‘ilgan kun / Boshqa), Bepul / Premium, «Ko‘rish».
- **Mening sahifalarim**: ro‘yxat, ko‘rishlar soni, javoblar soni, tahrirlash (havola o‘zgarmaydi), o‘chirish.
- **Suratlar ⭐** (yaratilgandan keyin, sahifa ekranida qo‘shiladi; joylashuv va yashirin ma’lumotlar o‘chiriladi).
- **Telegram Mini App** tayyor va sinovdan o‘tgan, lekin faqat **HTTPS** domen bo‘lganda ko‘rinadi.
- Eski bosqichma-bosqich wizard o‘chirilgan (kerak bo‘lsa `SHARE_WIZARD_IN_BOT=true` bilan darhol qaytadi).

**Kompyuterda HOZIR sinash:**

1. Boshqa gulbot bot jarayoni ishlamayotganiga ishonch hosil qiling (kecha hammasi to‘xtatilgan).
2. PowerShell oching va bajaring:

   ```powershell
   cd "D:\Coding projects\gulbot-cp27"
   powershell -ExecutionPolicy Bypass -File scripts\run_studio_local.ps1
   ```

   Bot shu oynada, sahifa serveri alohida oynada ochiladi. To‘xtatish: har bir oynada **Ctrl+C**.
3. **Telegram Desktop**da `@Flowersmarketcontroller_bot` → `/start` → **💌 Taklifnoma · Ha/Yo'q** → **🌐 Taklifnoma yaratish**.
4. Bot bergan havolani bosing — kompyuter brauzerida `http://127.0.0.1:8088/studio/enter/...` ochiladi → **Kirish**.
5. Telefon ko‘rinishi uchun: **F12** → «Toggle device toolbar» (Ctrl+Shift+M) → kenglik **360**.
6. Sinang: Taklifnoma (2 ta joy, Google Maps havolasi), «O‘zgartirish» bilan dizayn, «Ko‘rish», «Yaratish»;
   keyin «Mening sahifalarim» → tahrirlash → o‘chirish; Ha/Yo‘q va Uzrnoma yorliqlari.
7. Premium (⭐ dizayn, musiqa, suratlar) yopiq ko‘rinadi — bu to‘g‘ri, sovg‘a buyurtma tasdiqlanganda ochiladi.

**Sizdan kerak:**

- Firewall qoidasi **"gulbot-cp27-dev" yo‘q** — o‘chirish kerak emas.
- Telefonda va Mini App uchun: **HTTPS domen** (yoki VPS) yoki tunnel. Tunnelni o‘zim o‘rnatmayman — siz rozilik bersangiz.
- CP25 bo‘yicha ikkita mayda narsa (pastda, "Open").

## Technical

**Commits on `cp27-studio` (local only, nothing pushed or merged):**

| Checkpoint | Commits |
|---|---|
| CP27.1 link, session, one-form creator | a67ca49, f600118, 107ba0c, 7770af6 |
| CP27.1b design picker on its own screen | 46d3349 (+ status 2bac6fe) |
| CP27.2 Ha/Yo'q, Uzrnoma, photos, music | e7db988 (+ d15e34d) |
| CP27.3 my pages: list, edit, delete, counts | 8f36ce9 (+ d88d813) |
| CP27.4 Telegram Mini App | c4a2fa3 (+ 3669b6b) |
| CP27.5 slim bot | 0fbfeb3 (+ 472ffb5) |
| .env.example fix + PC start script | 52bba4f |

Migrations (additive, round-tripped, single head): `c27a1e5d9f01` (studio tables, places), `c27b4d2e8a13` (Mini App replay table).

**Tests added tonight:** picker 7, kinds/photos/music 14, my pages 10, Mini App 15 (launch data crafted from Telegram's spec), slim bot 17,
plus 4 real-Chrome studio runs at 360 px (form/picker, Ha/Yo'q + Uzrnoma + real photo upload, list/edit/delete, Mini App from the fragment).

**Mutations:** 57/57 caught on assertions (CP27.1 22, .1b 7, .2 9, .3 4, .4 9, .5 6), `docs/CP27_MUTATIONS.json`. First runs found 6 weak
tests or mutants (recorded in the run): each was fixed and re-run; none was counted as caught before it failed on an assertion.

**Gate, end of night:**
- Full suite without the CP24 browser matrix: **7,367 passed, 1 failed**: `test_env_example_documents_every_setting` (SHARE_WIZARD_IN_BOT
  missing from `.env.example`), fixed in 52bba4f and re-run (8/8). The full suite was not run again after that one-line fix.
- CP24 matrix (480) + studio browser runs (4) + infrastructure (8): **492 passed**.
- Lint, format, strict mypy (194 files), shadow sweeps (shop + platform, default wizard off; slim dispatcher in tests) clean.
- Secrets scan of the whole `main..HEAD` diff against the real `.env` values: 0 hits.

**Decisions made alone (how to reverse):** see `docs/CP27_STATUS.md` "Decisions" (picker categories, photos after creation, upload CSRF
in the query string, 3 plan rows, pin kept on edit, delete confirm screen, Mini App nonce, Telegram Web iframe unsupported, wizard pinned ON
in tests, wishes router kept in slim mode, bot "mine" → studio link). Each line says where to change it.

**Open:**
1. **CP25 (not touched tonight):** `tests/test_order_pings.py::test_the_claim_is_committed_before_telegram_is_called`, the loaded
   failure means NO send happened (empty list), not an invisible claim. Reproduced exactly by a due time 1 s ahead of the host clock; the
   fixture uses the Postgres clock (`now()`) while the tick uses the host clock. Fix proposed in CP27_STATUS.md; it passed in tonight's
   loaded run. To be recorded in docs/CP25_STATUS.md on codex/cp25-reliability.
2. **CP25:** `DEV_UNLIMITED_PAGES` (commit 56309f1) is not in `.env.example` there, so `test_env_example_documents_every_setting` will
   fail on that branch; add one line when CP25 resumes.
3. Telegram Web (web.telegram.org) cannot frame the studio; the Telegram apps can.
4. A phone or Mini App test needs an HTTPS origin (domain/VPS or an approved tunnel).
5. One browser run started at 1.39 GiB free RAM (rule: 1.5 GiB); every later heavy job checked first.
