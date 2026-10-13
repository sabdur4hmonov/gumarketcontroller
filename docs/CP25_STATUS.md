# CP25 status — low-RAM pass, 2026-10-13

Branch: `codex/cp25-reliability`. Local commits authorized; **no push/merge until
full gate, both shadow sweeps and configured-secret scan with enough RAM**.
Never access `D:/Coding projects/gulbot-designs`. Preserve unrelated Compose
loopback edits and backup. Private DBs gulbot_cp25_load / gulbot_cp25_test;
Redis broker6/results7/test8/FSM15, prefix-scoped cleanup and DB advisory lease.

CP24 is complete at 0d5072a: 7706 gate tests, 32/32 mutations, shadows0,
secrets scan, merge/push/cleanup and local single migration head a24d9e7b2c10.
Not rerun. The prior 36 harness checks, 7/7 proofs and two 2-shop runs were
also retained without rerunning. New small-scale admission: 8 tests and three
assertion mutations. Night runner: 3 tests and two assertion mutations.
Accumulated harness guard proof is 12/12; source bytes restored.

## Small baseline complete, before hot-path changes

10/25/50-shop runs all measured once and completed with 4 replies, one reminder
and one order ping per shop, every target reconciled and zero uploads.
See CHECKPOINTS.md and docs/capacity/cp25-before-{10,25,50}.json for all process
CPU/RAM, query counts/times, pool connections and Redis ops, plus clearly
marked extrapolations. Reply p50/p95/p99 ms:

| Shops | Kind | p50 | p95 | p99 | Reminder tick s |
|---|---|---|---|---|---|
| 10 | measured | 1638.658 | 3414.314 | 3513.391 | 9.7122 |
| 25 | measured | 1898.265 | 3235.328 | 3408.544 | 27.6413 |
| 50 | measured | 4490.434 | 12605.364 | 13463.527 | 54.0587 |

50 was the largest approved small scale; minimum sampled free RAM 599.65 MiB.
Operator startup headroom was 1300/1800/2000 MiB respectively, checked in real
time before each job. The runtime floor remains **512 MiB**, ordinary startup
1024 MiB; >=100 scales now additionally require **3072 MiB before seeding**.
No guard was weakened, no precheck retried in a loop, no model downloaded.

## Tonight queue

The original 100 attempt aborted at 509 MiB and is not a capacity result.
Actual 100/500/1000 before/after runs, full gate (including both shadow sweeps),
Playwright matrix and final secrets scan wait for >=3 GiB actual free RAM.

One command from the main repo:

```powershell
.\.venv\Scripts\python.exe -m scripts.cp25_load.tonight
```

Before ref is frozen at f8f73b8405322ec99cb1e06305fc9f7330f31df0 in CP25_BEFORE_REF.txt.
Runner archives that immutable commit into an ignored private snapshot and
sets PYTHONPATH to its src so editable installation cannot substitute hot fixes.
Private .env copy is removed in finally. It runs before100/500/1000, then
current after100/500/1000, collection, full gate and secrets, sequentially.
Every job checks 3072 MiB and stops at 512 MiB; any failed precheck/job is
recorded here and stops the queue without retry. No automatic push/merge.
Collection count must match fresh JUnit with no failures/errors/skips.

Extrapolated four-process RSS at1000 is 3872 MiB before OS/DB/VMM/web/STT;
3 GiB free alone may not suffice. If actual1000 refuses/aborts, record that
limit and retain the explicitly extrapolated estimate; do not call it measured.

## Exact next low-RAM step

Baseline frozen at f8f73b8. C1 image/spelling offloads and a 100ms loop-lag
guard are implemented; 43 touched/direct-neighbour tests passed, C1 mutations
6/6 assertion catches, strict typing passed for 8 touched files. A process-owned
two-thread executor carries only byte/text/Pillow work; AsyncSession stays on
the loop. Existing CP23 rendering now also uses that bounded pool.

Next: per-shop factory/poll fault isolation and small fault harness, then
watchdog/backoff/deadlines/reply pacing. Web cold Jinja/static file I/O awaits
the cache/web phase; bot factory SSL work awaits polling phase. The async
inventory lists 635 async definitions in167 files; this is an inventory, not
a claim that every one was independently runtime-proven. Audit read notes exist under
.cp22-stage/cp25/ASYNC_AUDIT.md. Polling faults/watchdog/timeouts/reply pacing,
EXPLAIN/index/pool/cache/logging work and shadow metadata speedup follow in
that order. Heavy proofs stay queued. No heavy proof, full gate, shadow sweep or Playwright matrix ran in this pass;
no push/merge. C1 loaded whole-suite interaction waits for RAM.

## C2 completed (small-scale proof)

17 focused poller tests plus one new one-shot crash test passed. Three new
assertion mutations caught, accumulated runtime report9/9 (C1 six + C2 three).
Per-shop unexpected factory errors are isolated; TLS construction runs in
the bounded executor with a20s startup deadline. No token/error text logged.

| One failed shop in10 | Healthy replies | Healthy p95/p99 ms | Expected reminder/order sends |
|---|---|---|---|
| unauthorized | 36/36 | 1385.724/1412.597 | 9/9 |
| flood | 36/36 | 1707.235/1725.047 | 9/9 |
| network | 36/36 | 1532.860/1557.832 | 9/9 |
| crash | 36/36 | 1352.976/1358.800 | 10/10 |

All four actual fault runs passed once with per-target reconciliation and
zero uploads. Healthy p95 remained below the original10-shop baseline3414ms
in these observations; laptop variability is not a universal latency guarantee.
Crash is one-shot task cancellation, replies for that shop excluded, worker
sends still required for all10. Source JSON under docs/capacity/cp25-fault-*.json.
Next low-RAM item: watchdog/backoff/admin record and handler/API deadline/pacing
guards. Full-scale isolation and loaded full-suite interaction wait for tonight.

## C3 in progress

25s handler deadline encloses DB middleware; cancellation rolls back. Per-bot/chat reply pacing and max3 Telegram429 attempts with10s retry-wait budget; global28 messages/s, groups20/min; media counts included. Poll progress watches getMe/getUpdates, crash/stall90s/three failed polls -> backoff1/2/4/... capped60s; supervisor checks every5s. A single batch upsert persists shop runtime state independently of10-minute health snapshots, admin shop view shows p95/errors/timeouts and existing alerts flag poller failures.

New additive revision a25e1d6c8b90 aftera24 creates shop_runtime_states. Fresh probe upgrade/downgrade/upgrade passed; 18 poller/admin neighbours and6 reliability guards pass, strict mypy6 touched files pass. New C3 mutations are running (do not rerun earlier proof); migration not yet applied to dev DB. C3 not committed yet. Exact next: finish new mutation subset, schema guard proof, verify dev current=head, local C3 commit, then low-RAM EXPLAIN/cache/shadow-cache implementation. No100/500/1000, full gate, shadow or Playwright job started.

## C3 complete locally (heavy interaction proof queued)

New guards:6 reliability tests,2 watchdog tests, runtime/admin test and fresh
additive migration roundtrip;18 focused poller/admin-neighbour run passed.
C3 assertion mutations14/14; accumulated runtime23/23 plus harness12/12.
Source restored byte-exact; Ruff and strict mypy7 touched files passed.
Local dev current=head=a25e1d6c8b90. Admin view exposes persisted per-shop
p95/errors/timeouts; poller failures enter existing alerts without replacing
token/channel/group health. Cancellation rolls back before deadline returns.
Reply limits are per-session/process with Telegram429 recovery; cross-process
collision is recovered via429, not represented as a global Redis quota.

Next: PhaseD read-only EXPLAIN on the owned small fixture, additive indexes if
plans justify them, configurable pools/connect timeouts, photo/static caching
and Caddy compression; then shadow source-location cache. Only focused files
and new mutation cases. Full100/500/1000 and loaded gate remain queued.

## D1 data efficiency prepared (local commit pending)

Three new pool/cache tests and the cursor-index test failed first on assertions.
After implementation,35 focused data/index/attachment/DB-lifetime neighbours
passed. Two plan-admission tests passed. Ten new assertion mutations passed;
runtime report33/33 plus harness12/12. Six touched source files passed strict
mypy; final Ruff check follows formatting.

Actual EXPLAIN ANALYZE captured on the owned10-shop fixture, including1000
temporary product rows rolled back after each plan capture. Cursor selection
went from0.468ms with a1000-row scan/sort to0.057ms using the new partial
tenant/cursor index; choice from0.479ms to0.070ms. These are small synthetic
measurements, not fleet capacity. Raw plans under docs/capacity/.

Additive revision a25f2c7d9e10 aftera25e1d6c8b90 adds only the sellable catalogue
cursor index concurrently. Fresh probe upgrade/downgrade repeated twice passed.
Owned load DB is at the new head; dev remains at the preceding revision.
Worker task pools default1/no overflow; long-lived bot/web remain5+10,
configurable. Pool wait5s and connect10s; statement30s unchanged. Catalogue
choices, including None, cached per(shop,preference) within one bounded tick;
captions/buttons remain customer-specific and checkout revalidates products.

The next two new EXPLAIN admission mutations were not executed because automatic
approval review hit its usage limit (not an unsafe-action finding). On resume,
the memory/status check was approved and measured1645MiB free. Exact next:
run only those two new mutations, final touched-file lint, D1 local commit;
then web/cache/compression, remaining runtime observations and shadow speedup.
No prior harness gate/proof rerun, no heavy job, no push or merge.

D1 completion: the two plan-admission mutations and worker tick-binding guard
also caught assertions (new13/13; accumulated runtime36/36+harness12/12).
Real worker callback integration passed once; separate ticks refresh choices.
Final lint found three long lines, now fixed; six source files strict mypy passed.
Before/after catalogue plans use scan/sort versus reverse index scan, and all
temporary inserted rows were rolled back. Tonight's command remains unchanged.
Next after D1 local commit: photo/static validators and bounded template I/O;
Caddy gzip and precompressed Brotli path; source-metadata-only shadow speedup.

## D2 web/cache in progress

D1 committed locally as309bfc0; no push. New web3 guards failed first on
assertions (unversioned immutable cache, missing photo ETag, cold file I/O on
loop). Templates now prepare dicts on the loop and render in the bounded CPU
pool; auth/admin/shop/public render paths converted. Static immutable applies
only to the exact current hash; other URLs revalidate. Photo ETag is checked
only after live-page/tenancy/moderation checks, private max-age0 must-revalidate.

First focused web run:72 passed,2 failed. One real issue: FileResponse changes
404 status during prepare, now final security/cache headers re-applied there.
One new fixture error: hidden page needs hidden_by+hidden_reason, corrected;
not counted as mutation evidence. Corrected web/compression/shop tests running.
Small Brotli1.2 codec installed (369kB wheel), no models or large downloads.
Static CSS/JS/SVG sidecar builder bounded1MiB/input, no customer photos; stock
Caddy gzip/zstd with upstream negotiated .br forwarding. Actual free RAM before
this job1023MiB; no heavy jobs run. New web/compression guard mutations next.

D2 progress: corrected web/compression/shop tests35/35 passed; two extra
compression guard tests and affected admin/login/static neighbours5/5 passed.
Ten web/cache/compression assertion mutations10/10 caught (runtime46/46,
harness12/12); source restored. Resolved-root and temporary-symlink mutations
are still pending. The final lint/type job refused at718MiB before execution;
recorded once, no retry loop. D2 remains uncommitted pending that check.
Move next to the shadow cache design and tiny focused proof; no full sweep.
Other runtime follow-ups: platform deadline/TLS constructor, stale persisted
runtime heartbeat, shared supervisor cadence in the after harness, bounded
parallel registry closure. Loaded pending-reminder plans still await RAM.

## Current resume point: memory refusal, no retry loop

Actual next independent job (tiny shadow RED test) also refused, at525MiB free.
No new job started after that. Existing512MiB runtime floor and >=100-shop
3072MiB startup floor are unchanged. No application/process stopped.

Shadow design is docs/CP25_SHADOW_SPEEDUP.md. The unexecuted tiny regression
is staged under ignored .cp22-stage/cp25/test_cp25_shadow_cache.py, outside
pytest collection until its RED run can be executed. No shadow implementation
or production sweep is claimed complete. D2 remains uncommitted with35+5
focused passing runs and10 assertion mutations; final lint/type and two extra
compression mutations waiting for RAM. D1 local commit309bfc0 is complete.

Exact next focused commands once the precheck permits (not a retry loop):

```powershell
$env:POSTGRES_TEST_DB='gulbot_cp25_test'; $env:REDIS_DB_BROKER='6'; $env:REDIS_DB_RESULTS='7'; $env:REDIS_DB_FSM='15'; $env:REDIS_DB_TEST='8'
# First check actual free RAM; focused jobs need768MiB. Stop/record if refused.
.\.venv\Scripts\python.exe -m scripts.cp25_load.mutations --report docs/CP25_RUNTIME_MUTATIONS.json --only 'static builder ignores resolved root' 'static builder writes temporary symlink'
.\.venv\Scripts\python.exe -m ruff check --fix src/gulbot/web scripts/compress_static.py scripts/cp25_load/mutations.py tests/test_cp25_web_cache.py tests/test_cp25_compression.py
.\.venv\Scripts\python.exe -m ruff format src/gulbot/web/app.py src/gulbot/web/render.py src/gulbot/web/admin.py src/gulbot/web/admin_screens.py src/gulbot/web/shop_panel.py scripts/compress_static.py scripts/cp25_load/mutations.py tests/test_cp25_web_cache.py tests/test_cp25_compression.py
.\.venv\Scripts\python.exe -m mypy src/gulbot/web/app.py src/gulbot/web/render.py src/gulbot/web/admin.py src/gulbot/web/admin_screens.py src/gulbot/web/shop_panel.py scripts/compress_static.py
# Each command is a separate job: re-check actual RAM before each.
# Then D2 local commit; prepare/run shadow tiny RED, implement local metadata
# cache, focused GREEN and new mutations. Remaining runtime items above follow.
```

Tonight heavy queue remains one line from the repo, checking3072MiB before each
job,512MiB while running, frozen f8f73b8 baseline, no automatic push/merge:

```powershell
.\.venv\Scripts\python.exe -m scripts.cp25_load.tonight
```

Finish the listed focused checks/source fixes before expecting its full gate
to go green. Actual100/500/1000, loaded pending-query plans, full gate/both
production sweeps, Playwright matrix, final configured-secret scan and
4/8/24GB capacity/webhook decision remain waiting. No heavy run/push/merge.
`nD2 final lint/type precheck refused below768MiB; no retry.
`nShadow tiny RED precheck refused below768MiB; no retry. Test/design prepared; implementation waits for RAM.
