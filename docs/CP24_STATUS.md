# CP24 isolated design phase

CP24 is implemented as a preview catalog on `cp24-designs` in
`D:\Coding projects\gulbot-cp24`, based on CP22.2 (`62571a3`). CP23 is still
working in the main checkout according to the owner's latest message.
Persistent creation and the database constraint remain the original 20 names.
There is no CP24 migration, main merge, or full-suite run in this phase.

## Research and original artwork

The [CP24 research section](DESIGN_BRIEF_INVITES.md) records public Uzbek
invitation services, Russian builders, Pinterest, Behance, Dribbble and a
YouTube tutorial's public metadata. Login/robots-blocked Instagram and TikTok
were skipped; source accessibility limitations are stated explicitly.

The research suggested distinct entry/reveal treatments, personal letters,
photo-led pages, rich event sections and more non-wedding colour directions.
All twenty compositions and SVG motifs are original. Existing local OFL
fonts and their adjacent licence files are reused. There are no remote assets.

The [evidence table](CP24_EVIDENCE.md) lists all twenty names, the planned
12 premium / 8 free decision and per-design cold page weights. The decision
lives in `services/premium.py:CP24_PREMIUM_TEMPLATES`, awaiting activation
under CP18's existing per-shop confirmed-order gift rule. Earlier free
styles and granted gifts retain their rules.

[Open the visual index](cp24-designs.html): 60 full-page screenshots (every
new design across Taklifnoma, Ha/Yo'q and Uzrnoma) plus 20 envelope views,
all at 360 CSS px. Gallery fixtures are authored SVG flowers, not real photos.
The byte ledger measures 240 normal visits (20 x 3 kinds x 4 languages),
with HTML, CSS, JS and fonts included; gallery payloads are separate and
explicit. The budget is 180 KiB chrome / 110 KiB fonts.

## Focused verification

- 2,354 focused web/share-page/CP18 gift/JavaScript checks passed. This includes
  480 real HTTP cases (40 designs x 3 kinds x 4 languages), 1,600 event-type
  render cases and existing web/feature regression checks. No skips.
- 480 headless Chrome cases passed at 360 px with worst-case field lengths,
  unbroken shop names, five wide seal initials and a full programme. Assertions
  inspect actual content boxes, strict CSP, escaping, local assets, images,
  tap-only music, reveal and page budgets. This is 2,834 focused checks in total;
  pilot reruns and mutation executions are not counted again.
- Scoped Ruff and mypy checks are recorded separately from the future full gate.
- [Assertion mutation proof](CP24_MUTATIONS.json) records deliberately broken
  guards, including lost designs, fonts, gift selection, escaping/CSP,
  gallery privacy, text wrapping, seal size, contrast and interaction behavior.
  Each source file is restored byte-for-byte after its mutant.

Browser checks use existing installed Chrome via Playwright. No browser, font
or model download was performed. Free memory was checked before browser work;
contexts run serially and are closed after each visit.

## Test isolation

Only this worktree's virtual environment and ignored `.env` are used:
`POSTGRES_TEST_DB=gulbot_cp24_test`; Redis broker 9, results 10, test/FSM 11.
Those Redis indices were empty when selected. No main token or environment
file was copied. The historical migration test with a fixed shared probe DB
was excluded; the future CP24 migration probe will be `gulbot_cp24_probe`.

## Remaining integration after CP23

1. Fetch and rebase `cp24-designs` onto main containing CP23.
2. Add exactly one additive CHECK-widening migration on that head. Activate
   the new names in persistent creation, picker and existing premium policy.
3. Round-trip that migration on a fresh `gulbot_cp24_probe`, assert the actual
   PostgreSQL CHECK admits all forty names, and mutation-prove those guards.
4. Once the other session has finished, run the full repository gate and
   secrets scan. Push only `cp24-designs`. Merge only when no session is
   working in the repository. The focused results above are not a full gate.

No change in this phase writes to the main checkout, changes its environment,
or starts/stops its services. CP24 evidence tools do not send Telegram messages.

The owner's parallel-session instruction explicitly defers the normal
`CONTRIBUTING.md` full-gate-before-commit rule for this design-only branch
snapshot. Passing focused checks does not authorise integration or release.
The seal guard measures the text's actual range before reveal hides the seal,
including its corners inside the circular wax border; post-reveal page bounds
alone cannot prove monogram fit.

Assertion proof: **28/28 distinct mutants caught**. The JSON explicitly records
accumulated per-guard results and the last rechecked guard; pilot/failed or
interrupted attempts are not counted as successful proof. The seal guard was
strengthened after its first mutant survived, then the maximum-length seal
font was reduced to 12 px after that guard exposed actual crowding in Anor.
Both the fixed case and its deliberate regression were rechecked.

The brief also retains six further original bright concept candidates for a
later collection, clearly separate from the twenty implemented CP24 styles.

Final evidence: all 80 PNGs are 360 px wide and all index links resolve.
Cold chrome ranges from **122.3 to 162.9 KiB** per design
(maximum over the twelve normal kind/language samples); fonts peak at
**103.0 KiB**. All 240 normal visits passed their assertions.

The finished mobile matrix passed **480 tests in 645.93 s**. The focused
render/service/JS selection passed **2,354 tests in 78.35 s**. Ruff passed
on eleven changed Python files; scoped mypy passed on seven source/tool files.
These are final-source checks; the full gate remains deferred.

Review branch: [cp24-designs](https://github.com/sabdur4hmonov/gumarketcontroller/tree/cp24-designs).
No PR or main merge is part of this phase. The latest fetch still shows
CP22.2 at `origin/main`; CP23 activation remains pending. A localhost-only
review server serves this worktree's `docs` at
`http://127.0.0.1:8774/cp24-designs.html` (helper PID in ignored
`.cp24-stage/preview.pid`). It is separate from the existing CP22 preview.
