# CP25 status — daytime pass, 2026-10-14

## CURRENT RESUME POINT — read this before chronological history

**LATEST STOP: 2026-10-14T05:58:23Z.** Owner-authorized measurement command
completed infrastructure/imports/private seed, then stopped ONCE at actual
2756.38MiB, below3072MiB. No capacity child or profile started. Preserve
.cp22-stage/cp25/evening-20261014-d113f94c; admission.json and startup/ contain
timestamped actual RAM/top5/source hashes. Public startup evidence:
capacity/cp25-startup-evening-20261014.json. No automatic retry, waiting loop
or heartbeat. BEFORE/AFTER10/25/50/100/500/1000 all remain **not run: RAM**.
No proven tick attribution or activated batch fix. Next owner-required step:
free RAM WITH Docker/WSL running (minimum3072MiB; preferably~4GiB).
Then the same one command below creates a new certified run directory.
Reference f8 remains clean, other processes/Compose edits/backup preserved.
Local tooling commit8da8498; current runtime102/102 + harness12/12.
Full sweeps/headless/full gate/secrets/push remain pending; never merge.

Owner authorized all remaining work on 2026-10-14. Actual free RAM initially
5310.04MiB, then5476.48MiB. The5-minute heartbeat remains **PAUSED**;
original RAM watcher has finished. No RAM waiting/retry loop. Infrastructure
must be running BEFORE the3072MiB admission for capacity/full gate.
Cold Docker startup was required: actual pre-start5530.55MiB, observed during
startup2938.15MiB (vmmemWSL working set1863.51MiB), after startup1956.72MiB.
The difference3573.83MiB includes concurrent system activity; it is not a
certified Docker-only allocation. Other processes/settings remain untouched.
First new fake engine test was stopped before assertions because Docker was
off; it had no test result. Re-run only this new assertion after infra readiness.
Old commands/history below are superseded by this resume point.

2026-10-14 owner-authorized pass: final default-config strict mypy uncovered
the legacy harness engine-meter signature losing task=True. New fake RED
assertion failed on unexpected task keyword; fixed wrapper forwards the
actual production flag (no pool defaults injected). Frozen f8 keeps its
reviewed narrow adapter; current wrapper no longer requires AST replacement.
GREEN1, new assertion mutant caught: runtime102/102 plus harness12/12.
Eight changed tooling source files strict mypy green, peak157.66MiB;
new fake test peak243.33MiB. No capacity run yet. Private test DB
gulbot_cp25_test, Redis broker6/results7/FSM15/test8 used for checks.

Daytime1a–1f: static reminder/client review with file:line is in
CP25_TICK_CLIENT_DESIGN.md, explicitly **hypothesis, not proven**. Experimental
task_bot_batch is implemented but NOT wired to any worker/poller; fake tests
prove fresh clients across two asyncio.run calls, token identity, one close,
exception cleanup and owner-loop guards. Activation/real two-loop HTTP proof
must wait for actual25-shop profile attribution. Shadow source-location cache
is implemented and tiny-unit-tested; every filter/probe remains evaluated,
cache discarded per invocation. No full sweep speed/time claim is made.
Web/cache/compression final checks and the2 pending compression mutants pass.
DEPLOY's4/8/24GB guide/threshold structure uses TBD: pending measured run.

Touched-file lint/format green (28 files); strict mypy green on web/cache,
compression, pools, tick cache, catalogue model/index and preparation tools.
24 unique focused assertions/parameter cases pass across staged daytime jobs,
not a full suite. Maximum measured focused process RSS250.30MiB; type-check
maximum166.82MiB. Single observed prechecks/refusals recorded below. The new
mutation run stopped at608.15MiB before its next guard, kept13 catches, then
after independent type/lint work ran only17 unexecuted names. NEW30/30,
accumulated runtime101/101 plus retained harness12/12. No old harness proof
was rerun. Source bytes restored; proofs checkpoint after each guard now.

Warm-only startup evidence is in capacity/cp25-startup-warm-20261014.json:

|Step|Free before/after MiB|Evidence limits|
|---|---|---|
|Docker/WSL|2169.04 /2159.43|Already running; no cold boot|
|Postgres|2182.63 /2165.29|Already running, no recreate/pull|
|Redis|2166.52 /2157.36|Already running, no recreate/pull|
|Venv imports|2142.86 /2212.04|Child peak202.16MiB; exited afterward|
|Private reference DB seed|2196.29 /2107.45|Seed-only2, no Bot API/task load; peak229.64MiB|

Top5 process working sets recorded at EVERY boundary; final were vmmemWSL,
Chrome, two ChatGPT processes and Claude. No other process/folder was changed.
The warm whole-step net free decline61.59MiB does NOT establish a cold-start
cost. Prior3261.95->1947.29 decline1314.66MiB occurred BEFORE harness launch;
historical process snapshots were absent, so its cause remains unattributed.
No retrospective executed-tree certification is invented for warm imports;
seed-only JSON has actual cleanf8/schemaa24 provenance. Future startup
snapshots now include runtime commit/status/src+harness hashes.

**ONE measurement command** from this repo after infrastructure RAM admission:

```powershell
.\.venv\Scripts\python.exe -u -m scripts.cp25_load.evening
```

Use an interactive terminal/PTY. It starts Docker Desktop with bounded90s
timeout, prepares existing Postgres/Redis without recreate/build/pull, logs
RAM/top5 before/after imports/private seed, THEN checks actual3072MiB. It does
not renew the old wait. It completes any still-unproven NEW guards only,
BEFORE10/25/50/100/500/1000 on cleanf8, then diagnostic25. Each scale admits
once; refused/aborted rows are not retried. Real result files retain commit,
full porcelain, src/+scripts/cp25_load SHA, actual DB revision and adapter SHA.
Separate before DBs gulbot_cp25_before_load/test; Redis9/10/12/11;
after gulbot_cp25_load/test, Redis6/7/15/8; prefix-scoped cleanup/owned leases.

At **PROFILE REVIEW REQUIRED**, no heavy child is alive. The agent inspects
the actual tick-profile.json, documents attribution, tests/activates the
candidate ONLY if cause confirmed and real two-loop I/O/mutations pass, then
writes PROFILE_REVIEWED.json containing status=reviewed, nonempty attribution,
profile_sha256 and after_tree_sha256 matching current executed-tree provenance.
Only then Enter continues AFTER with identical scales/adapter. Missing/stale
evidence refuses AFTER. One command does not mean skipping this evidence gate.

Small admission: until a fresh valid same-scale measured peak exists,3072MiB;
then conservative sum of bot/worker/stub/coordinator + container peaks1024MiB
margin for10/25/50. Not inferred from2 shops or old pressure capacity rows.
100+ always3072MiB; runtime512 unchanged. Command ends after measurements,
without full gate/push/merge. Fresh run directory preserves last refused ledger.

Remaining (run only when actual admission passes): valid before/after tables, actual25 attribution,
candidate activation/real HTTP proof, both full sweeps/time comparison,
headless matrix/full gate/secrets scan, loaded query verification, real Caddy
proxy rehearsal and measured capacity/webhook decision. Historical pressure
rows remain NOT a baseline. Local commits only; unrelated Compose edits/backup
and D:/Coding projects/gulbot-designs preserved.

---

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

## Historical pressure runs — NOT a baseline

10/25/50-shop runs all measured under memory pressure, NOT a baseline, once and completed with 4 replies, one reminder
and one order ping per shop, every target reconciled and zero uploads.
See CHECKPOINTS.md and docs/capacity/cp25-before-{10,25,50}.json for all process
CPU/RAM, query counts/times, pool connections and Redis ops, plus withdrawn historical extrapolations that must not support capacity conclusions. Reply p50/p95/p99 ms:

| Shops | Kind | p50 | p95 | p99 | Reminder tick s |
|---|---|---|---|---|---|
| 10 | measured under memory pressure, NOT a baseline | 1638.658 | 3414.314 | 3513.391 | 9.7122 |
| 25 | measured under memory pressure, NOT a baseline | 1898.265 | 3235.328 | 3408.544 | 27.6413 |
| 50 | measured under memory pressure, NOT a baseline | 4490.434 | 12605.364 | 13463.527 | 54.0587 |

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

Historical1000-shop extrapolation3872MiB is withdrawn because its source runs were under memory pressure. New capacity/extrapolation waits for valid pre-change measurements; do not use the old slope.

## Exact next low-RAM step

Pre-change source ref frozen at f8f73b8; this does not validate the pressure measurements. C1 image/spelling offloads and a 100ms loop-lag
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
zero uploads. The historical comparison to10-shop3414ms is withdrawn for capacity conclusions: both workload timing and machine pressure need a valid controlled rerun.
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
D2 final lint/type precheck refused below768MiB; no retry.
Shadow tiny RED precheck refused below768MiB; no retry. Test/design prepared; implementation waits for RAM.


## Latest steering: invalidate pressure timings and remeasure before any remaining fixes

All10/25/50 rows are **measured under memory pressure, NOT a baseline**. Do not
use their CPU/RAM slopes, extrapolations, latency or tick timings for capacity.
Recorded historical HEAD was0d5072a with harness additions later committed as
f8f73b8405322ec99cb1e06305fc9f7330f31df0. Raw artifacts already exist in that
commit, and git diff0d5072a..f8f73b8 -- src migrations is empty; first production
performance commit8291a3d, catalogue/pool/cache309bfc0 later. Runtime SHA/blob
hash provenance was not captured, so a clean exact executed-tree claim would
be unsupported. Fresh before uses the immutable immediate pre-changef8f73b8.

Historical harness scale-start log free RAM:10=2191,25=2697,50=1948MiB;
minimum sampled739.20/1116.62/599.65MiB respectively.525MiB was a later denied
focused-job precheck. Swap was not measured, so no claim of proven swapping.
Nonetheless every historical capacity row is invalidated as requested.

Current verification:1628MiB actual free RAM (<3072); no measurement run started.
Next prepare an isolated detached pre-change checkout, separate before DB/test
DB and Redis indexes, record source/dependency provenance per run, and profile
real public reminder task. Keep main working tree and designer folder intact.
All new measurements including10/25/50 now require3072MiB free at precheck.
Order: fresh pre-change10/25/50 -> profile and compare pressure observations ->
real100/500/1000 before then current after -> remaining focused web checks,
shadow implementation, full gate and secrets. No push until full gate green.

Harness issue found before after-table: measured_engine only accepts database,
but D1 task engine now passes task=True. Fix only the measurement wrapper to
forward keyword options; otherwise the after harness would fail or mask pool
settings. Before source task engine has no such option. Profile must separate
RPC5ms, production bot/TLS construction, DB time, registry closure and limiter
wait; no attribution of ~1s/shop without that evidence.

Isolated detached checkout prepared at D:/Coding projects/gulbot-cp25-before,
HEAD=f8f73b8405322ec99cb1e06305fc9f7330f31df0, initially clean. Preparation
RAM1992MiB, not a benchmark. No private .env copied, no main tree stash/reset.
Before resources: gulbot_cp25_before_load / gulbot_cp25_before_test,
Redis broker9/results10/FSM12/test11. After remains own6/7/15/8 resources.
Databases are not created/seeded until a run is admitted.

Prepared measurement-only adapter scripts/cp25_load/reference_measure.py:
records actual commit, production file/tree SHA256, dirty state, dependency
versions, adapter SHA, resource names and actual precheck RAM per scale.
Imports must resolve into the chosen source checkout. Production sources are
unchanged in the reference worktree. Narrow harness adaptations forward engine
keyword options and route owned DB/FSM namespace cleanup; no pool override.
Optional diagnostic task cProfile plus bot_for/close/limiter wall spans is
separate from unprofiled measurements. This new adapter is prepared, not yet
executed/validated; runtime/guard verification is a measurement prerequisite.

Fresh small before command (only after actual3072MiB precheck permits):

```powershell
.\.venv\Scripts\python.exe scripts\cp25_load\reference_measure.py --source 'D:\Coding projects\gulbot-cp25-before' --phase before --scales 10,25,50 --output .cp22-stage/cp25/reference-small-before-v1
```

Separate diagnostic10-shop profile uses the same command with --scales10,
--profile and a new output .cp22-stage/cp25/reference-profile-before-v1.
It is excluded from baseline tables. Raw pressure observations are retained;
100/500/1000 extrapolations withdrawn. Valid fresh tables/profiles pending RAM.
The tonight runner must be wired to the same isolated adapter/resources and
stop after measurements; remaining checks/gate follow in the requested order.

Tonight is now wired to the isolated reference adapter: default command runs
before100/500/1000 then after100/500/1000 and stops; --gate-only runs collection,
full gate/both sweeps/secrets after the remaining work, without repeating
already passed measurements. No private .env copy. New adapter/runner changes
still require focused prerequisite verification before executing measurements.
All old12 harness mutation proofs are retained; no new proof is claimed.
Read-only preparation check3058MiB free, still below3072, no run started.

Current measurements table:

| Scale | Before code | Before status | After code | After status |
|---|---|---|---|---|
|10/25/50|f8f73b8405322ec99cb1e06305fc9f7330f31df0 clean reference|not measured; waiting for >=3072MiB|current branch + per-run production SHA256|not measured|
|100/500/1000|same clean reference|not measured|current branch + per-run production SHA256|not measured|

No new extrapolation or capacity claim is supported yet. Old pressure numeric
observations remain in CHECKPOINTS but every row is explicitly invalidated.

## Authorized overnight continuation (2026-10-13)

Bounded RAM watcher is live: .cp22-stage/cp25/overnight-20261013/ram-state.json,
actual worker PID34024 (venv launcher29904). Started18:01:02 UTC; six-hour
deadline00:01:02 UTC2026-10-14. Reads every300s with sleep; requires TWO
consecutive readings >=3072MiB. Initial2833.41, then3160.79 (streak1), then
2208.65 (reset0). No heavy queue has started. New RAM-clock tests2/2 passed.
Native heartbeat cp25-overnight-ram-and-capacity is ACTIVE, attached to this
chat every5 minutes; pause on expiration/completion/terminal owner-required
failure. It must never start another job while an owned benchmark/test lives.

New provenance guards RED3 assertions, GREEN4/4. Every result now includes
commit, full git status --porcelain, SHA256 of src/ and scripts/cp25_load/,
adapter SHA and patched harness bytecode hashes; dependencies/resources/actual
DB revision included. No private .env copied. Runtime startup remains1024MiB
for2-shop tooling validation; all capacity scales stay3072 (the optional small
scale peak+1GiB rule is not enabled). Runtime floor512 unchanged.

First BEFORE2 diagnostic (startup2675MiB) exposed a cwd bug: Python imports
were f8 but Alembic ran main migrations. It is INVALID, not a baseline/tooling
pass. Corrected adapter enters source cwd and checks actual alembic_version
against the measured checkout before any roles run. Corrected BEFORE2 run
(startup2710MiB; minimum1759.19) passed8/8 replies,2 reminders/order pings,
zero uploads. All8 role/result JSON files have certificates and actual
schemaa24d9e7b2c10, sourcef8f73b8. Profiles contain engine/connect/query,
bot_for/limiter/transport/closure spans and cProfile. No25-shop attribution
claim made from this diagnostic. Corrected outputvalidate-before-2-fixed.

AFTER2 tooling run completed: startup2062MiB, minimum1119.26MiB,
8/8 replies,2 reminders/order pings,zero uploads, actual schemaa25f2c7d9e10.
Outputvalidate-after-2; owned session40867 ended normally. All8 JSON files
certified. TOOLING_VALIDATED.json records both new2-shop validations.
The earlier36 tests/12 retained proofs, CP24 gates and pressure runs have
not been repeated.
2026-10-13T17:50:27.8683182Z — new tooling RED precheck 1718.66 MiB
2026-10-13T17:56:51.7113266Z — tooling GREEN precheck 2330.94 MiB
2026-10-13T18:00:35.1765470Z — sparse RAM-wait focused precheck 2796.46 MiB

2026-10-13T18:01:02.783413+00:00 — overnight RAM 2833.41MiB, consecutive >=3072 readings 0/2.
2026-10-13T18:03:28.4327382Z — new BEFORE2 diagnostic validation precheck 2674.77 MiB; gate1024

2026-10-13T18:03:28.994458+00:00 — before 2: precheck actual free RAM 2647.05MiB.

2026-10-13T18:03:45.316900+00:00 — before-2: actual free RAM before scale 2436.59MiB; source f8f73b8405322ec99cb1e06305fc9f7330f31df0.

2026-10-13T18:04:40.956723+00:00 — before-2: run completed; minimum sampled free RAM 1766.45MiB; validity not yet assessed.

2026-10-13T18:06:02.785558+00:00 — overnight RAM 3160.79MiB, consecutive >=3072 readings 1/2.
2026-10-13T18:07:59.8913088Z — corrected BEFORE2 validation precheck 2710.03 MiB; previous diagnostic invalid due schema-source mismatch, code corrected

2026-10-13T18:08:00.599305+00:00 — before 2: precheck actual free RAM 2663.12MiB.

2026-10-13T18:08:10.402175+00:00 — before-2: actual free RAM before scale 2432.20MiB; source f8f73b8405322ec99cb1e06305fc9f7330f31df0.

2026-10-13T18:09:12.856985+00:00 — before-2: run completed; minimum sampled free RAM 1759.19MiB; validity not yet assessed.

2026-10-13T18:11:02.788407+00:00 — overnight RAM 2208.65MiB, consecutive >=3072 readings 0/2.
2026-10-13T18:12:52.6695851Z — new AFTER2 tooling precheck 2062.44 MiB; gate1024

2026-10-13T18:12:53.224191+00:00 — after 2: precheck actual free RAM 2040.84MiB.

2026-10-13T18:13:02.883406+00:00 — after-2: actual free RAM before scale 1822.91MiB; source c0dad37a0db0f6bd22a00a0dc576fa3e19e76de4.

2026-10-13T18:13:58.977435+00:00 — after-2: run completed; minimum sampled free RAM 1119.26MiB; validity not yet assessed.

2026-10-13T18:16:02.792863+00:00 — overnight RAM 2210.85MiB, consecutive >=3072 readings 0/2.
2026-10-13T18:18:33.2984382Z — queue prerequisite test precheck 2019.6 MiB

2026-10-13T18:21:02.797976+00:00 — overnight RAM 2016.99MiB, consecutive >=3072 readings 0/2.

2026-10-13T18:26:02.800614+00:00 — overnight RAM 1286.57MiB, consecutive >=3072 readings 0/2.

2026-10-13T18:26:51.8869791Z — new schema/delivery guard RED precheck 1380.56 MiB

2026-10-13T18:27:18.1039517Z — new delivery guard RED precheck 1298.2 MiB

2026-10-13T18:27:51.0984599Z — new tooling lint precheck 1496.5 MiB

2026-10-13T18:28:49.5842244Z — new tooling type precheck 1472.41 MiB


<!-- CP25 CERTIFIED TABLES START -->

### CP25 certified overnight measurements

Harness limits: **5 ms artificial delay per Bot API RPC; 0.1 customer
messages/s/shop** (three customer updates plus one owner announcement).
Reminder and order tasks run sequentially in **100-shop batches**, each
with a fresh asyncio loop. Broker and prefork scheduling are excluded.
Tick totals describe a single-process upper bound, not a production
Celery fleet figure. These runs cannot certify 4/8/24 GB fleet capacity.
Startup guard: 3072 MiB at every scale; two consecutive five-minute
readings before queue admission. Runtime floor remains 512 MiB.
Results with sampled free RAM below 1024 MiB are excluded as pressure
runs. No unmeasured row is extrapolated. RSS/shop is amortized measured
process RSS including fixed overhead, not an incremental memory slope.

Before source: clean `f8f73b8405322ec99cb1e06305fc9f7330f31df0`.

**BEFORE**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|queued; RAM gate pending|—|—|—|—|—|—|
|25|queued; RAM gate pending|—|—|—|—|—|—|
|50|queued; RAM gate pending|—|—|—|—|—|—|
|100|queued; RAM gate pending|—|—|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

**AFTER**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|queued; RAM gate pending|—|—|—|—|—|—|
|25|queued; RAM gate pending|—|—|—|—|—|—|
|50|queued; RAM gate pending|—|—|—|—|—|—|
|100|queued; RAM gate pending|—|—|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

Full certificates/raw measurements: `docs/capacity/cp25-clean-*.json`.

<!-- CP25 CERTIFIED TABLES END -->

2026-10-13T18:31:02.803427+00:00 — overnight RAM 1796.25MiB, consecutive >=3072 readings 0/2.

2026-10-13T18:31:14.7567788Z — tooling lint verification precheck 1730.74 MiB

2026-10-13T18:31:18.9924610Z — corrected namespace tooling type precheck 1687.52 MiB

2026-10-13T18:32:57.5608654Z — new tooling GREEN precheck 1710.71 MiB

2026-10-13T18:33:05.7992726Z — corrected tooling format/lint precheck 2324.06 MiB

2026-10-13T18:35:32.1330278Z — stage prerequisite RED precheck 2576.52 MiB

2026-10-13T18:36:02.807473+00:00 — overnight RAM 1455.48MiB, consecutive >=3072 readings 0/2.

2026-10-13T18:36:13.1353989Z — new tooling final focused precheck 1387.8 MiB

2026-10-13T18:36:27.3312660Z — tooling final lint precheck 2371.36 MiB

2026-10-13T18:37:07.6790302Z — corrected measurement tooling type precheck 2437.11 MiB

2026-10-13T18:37:30.3638682Z — NEW overnight guard mutations precheck 2562.62 MiB

2026-10-13T18:37:31.177575+00:00 — Mutation overnight bounded deadline: actual free RAM 2531.02MiB before focused test.

2026-10-13T18:37:33.823122+00:00 — Mutation overnight clipped sleep: actual free RAM 2529.84MiB before focused test.

2026-10-13T18:37:36.507714+00:00 — Mutation queue ready state: actual free RAM 2523.53MiB before focused test.

2026-10-13T18:37:39.531045+00:00 — Mutation queue two readings: actual free RAM 2481.77MiB before focused test.

2026-10-13T18:37:42.353219+00:00 — Mutation queue tooling prerequisite: actual free RAM 2492.80MiB before focused test.

2026-10-13T18:37:44.992599+00:00 — Mutation queue profile review prerequisite: actual free RAM 2495.04MiB before focused test.

2026-10-13T18:37:48.549372+00:00 — Mutation overnight ram floor: actual free RAM 2276.35MiB before focused test.

2026-10-13T18:37:52.112037+00:00 — Mutation overnight consecutive readings: actual free RAM 1707.14MiB before focused test.

2026-10-13T18:37:54.983796+00:00 — Mutation overnight low reading reset: actual free RAM 1399.32MiB before focused test.

2026-10-13T18:37:59.289526+00:00 — Mutation overnight sparse sleep: actual free RAM 1417.61MiB before focused test.

2026-10-13T18:38:02.628868+00:00 — Mutation reference clean checkout: actual free RAM 2269.97MiB before focused test.

2026-10-13T18:38:05.371388+00:00 — Mutation reference full status: actual free RAM 2441.52MiB before focused test.

2026-10-13T18:38:08.404325+00:00 — Mutation reference harness hashing: actual free RAM 2400.58MiB before focused test.

2026-10-13T18:38:11.361977+00:00 — Mutation reference actual schema: actual free RAM 2444.54MiB before focused test.

2026-10-13T18:38:14.026988+00:00 — Mutation reference single head: actual free RAM 2445.54MiB before focused test.

2026-10-13T18:38:16.826365+00:00 — Mutation reference dict certificate: actual free RAM 2426.66MiB before focused test.

2026-10-13T18:38:19.957172+00:00 — Mutation reference list certificate: actual free RAM 2451.31MiB before focused test.

2026-10-13T18:38:22.832321+00:00 — Mutation reference redis isolation: actual free RAM 2479.41MiB before focused test.

2026-10-13T18:38:25.505548+00:00 — Mutation queue scale ram floor: actual free RAM 2474.24MiB before focused test.

2026-10-13T18:38:28.699576+00:00 — Mutation queue profile order: actual free RAM 2420.79MiB before focused test.

2026-10-13T18:38:31.568121+00:00 — Mutation queue source verification: actual free RAM 2447.15MiB before focused test.

2026-10-13T18:38:34.323484+00:00 — Mutation queue database verification: actual free RAM 2447.77MiB before focused test.

2026-10-13T18:38:37.018948+00:00 — Mutation queue reminder delivery: actual free RAM 2417.21MiB before focused test.

2026-10-13T18:38:39.924650+00:00 — Mutation queue order delivery: actual free RAM 2424.27MiB before focused test.

2026-10-13T18:38:42.750303+00:00 — Mutation queue file id reuse: actual free RAM 2446.88MiB before focused test.

2026-10-13T18:40:39.5057636Z — final overnight tooling lint precheck 2724.79 MiB

2026-10-13T18:41:02.811790+00:00 — overnight RAM 2892.3MiB, consecutive >=3072 readings 0/2.

2026-10-13T18:43:22.9785768Z — certify completed prerequisites precheck 2751.63 MiB

## Overnight handoff — tooling ready, capacity still waiting for RAM

Both NEW2-shop diagnostic runs have completed (not capacity baseline rows).
BEFORE startup2710MiB/min1759.19, clean f8/schemaa24d9e7b2c10;
AFTER startup2062MiB/min1119.26, current c0dad37 + recorded dirty tree,
schemaa25f2c7d9e10. Every role/result JSON has the runtime certificate.
Corrected schema-source guard, real reminder/order delivery guard and queue
admission guards were checked RED then GREEN. Focused new tooling11/11;
new guards25/25 assertion-caught, accumulated runtime71/71 + retained
harness12/12. Only NEW proofs ran. Measurement tooling lint/type passed.
TOOLING_VALIDATED.json and GUARDS_VALIDATED.json are durable stage markers.

The RAM-only watcher PID34024 still owns its original six-hour window
18:01:02UTC Oct13 through00:01:02UTC Oct14 (05:01:02 Tashkent). Do not
restart it. The active native heartbeat cp25-overnight-ram-and-capacity
continues THIS chat every5minutes; it stays quiet on unchanged waiting/jobs.
No benchmark/test process remains active at this handoff. Latest RAM readings
are in ram-state.json and timestamped notes above; no TWO consecutive highs
have occurred. Keep all capacity-scale prechecks3072MiB (no small-scale
exception enabled), runtime512MiB; no retry of a refused/aborted row.

Exact next command, ONLY after ram-state phase ready and actual scale RAM gate:

```powershell
.\.venv\Scripts\python.exe -u -m scripts.cp25_load.overnight_queue --stage before
```

Driver sequentially runs10/25/50/100/500/1000 on clean f8, then diagnostic25.
It owns measurement.lock and before-ledger.json/childPID; never launch another
job while those owned PIDs live, never automatically restart an attempted
stage. Each completed/refused row updates CHECKPOINTS and appends a STATUS
snapshot without rewriting the concurrent RAM log. Public certified result
files go to docs/capacity/cp25-clean-*.json. Before profile_review phase hands
back to the heartbeat to inspect tick-profile.json, copy profile evidence,
document actual attribution, and test/mutation-prove any demonstrated
same-task batch-client fix before creating PROFILE_REVIEWED.json. Then run:

```powershell
.\.venv\Scripts\python.exe -u -m scripts.cp25_load.overnight_queue --stage after
```

Same scales/adapter, independently certified current source. After its
focused_checks phase finish web/cache/compression checks, pending2 compression
mutants, source-location-only shadow speed-up, remaining focused/lint/type,
fresh migration roundtrips/tenancy/full gate/both sweeps/Playwright and secrets.
Full gate only with actual3072MiB. Push branch ONLY green gate+scan; NO merge.
If initial six-hour wait expires, mark unrun rows not run: RAM, report once,
and pause heartbeat. If actual profile25 is refused, record attribution
waiting for RAM; do not invent a finding/fix or retry it automatically.

Harness limits stay next to tables: fake5ms/RPC, customer0.1msg/s/shop,
sequential100-shop reminder/order batches/fresh loops, no broker/prefork.
Single-process tick bounds do not certify a production Celery fleet or
4/8/24GB server capacity. No silent extrapolation. Actual25-shop attribution
and a client fix remain unperformed; no source hot-path change made this turn.
No push/merge. Preserve unrelated Compose edits/backup and designer directory.

2026-10-13T18:46:02.814881+00:00 — overnight RAM 2360.21MiB, consecutive >=3072 readings 0/2.

2026-10-13T18:51:02.819912+00:00 — overnight RAM 2342.28MiB, consecutive >=3072 readings 0/2.

2026-10-13T18:56:02.865630+00:00 — overnight RAM 2967.57MiB, consecutive >=3072 readings 0/2.

2026-10-13T19:01:02.871414+00:00 — overnight RAM 3108.35MiB, consecutive >=3072 readings 1/2.

2026-10-13T19:06:02.874432+00:00 — overnight RAM 2015.87MiB, consecutive >=3072 readings 0/2.

2026-10-13T19:11:02.881569+00:00 — overnight RAM 495.2MiB, consecutive >=3072 readings 0/2.

2026-10-13T19:16:02.890034+00:00 — overnight RAM 2117.66MiB, consecutive >=3072 readings 0/2.

2026-10-13T19:21:02.897226+00:00 — overnight RAM 2615.19MiB, consecutive >=3072 readings 0/2.

2026-10-13T19:26:02.903667+00:00 — overnight RAM 1505.24MiB, consecutive >=3072 readings 0/2.

2026-10-13T19:31:02.909656+00:00 — overnight RAM 1859.31MiB, consecutive >=3072 readings 0/2.

2026-10-13T19:36:02.914272+00:00 — overnight RAM 2225.43MiB, consecutive >=3072 readings 0/2.

2026-10-13T19:41:02.919010+00:00 — overnight RAM 2248.36MiB, consecutive >=3072 readings 0/2.

2026-10-13T19:46:02.924027+00:00 — overnight RAM 1866.11MiB, consecutive >=3072 readings 0/2.

2026-10-13T19:51:02.986262+00:00 — overnight RAM 2103.19MiB, consecutive >=3072 readings 0/2.

2026-10-13T19:56:03.039360+00:00 — overnight RAM 1969.44MiB, consecutive >=3072 readings 0/2.

2026-10-13T20:01:03.065899+00:00 — overnight RAM 2123.78MiB, consecutive >=3072 readings 0/2.

2026-10-13T20:06:03.109266+00:00 — overnight RAM 2204.38MiB, consecutive >=3072 readings 0/2.

2026-10-13T20:11:03.114439+00:00 — overnight RAM 2171.89MiB, consecutive >=3072 readings 0/2.

2026-10-13T20:16:03.118699+00:00 — overnight RAM 2049.38MiB, consecutive >=3072 readings 0/2.

2026-10-13T20:21:03.122797+00:00 — overnight RAM 2159.26MiB, consecutive >=3072 readings 0/2.

2026-10-13T20:26:03.127600+00:00 — overnight RAM 2102.85MiB, consecutive >=3072 readings 0/2.

2026-10-13T20:31:03.130213+00:00 — overnight RAM 2057.28MiB, consecutive >=3072 readings 0/2.

2026-10-13T20:36:03.141346+00:00 — overnight RAM 2146.29MiB, consecutive >=3072 readings 0/2.

2026-10-13T20:41:03.146314+00:00 — overnight RAM 2043.27MiB, consecutive >=3072 readings 0/2.

2026-10-13T20:46:03.197852+00:00 — overnight RAM 2017.91MiB, consecutive >=3072 readings 0/2.

2026-10-13T20:51:03.238882+00:00 — overnight RAM 2135.6MiB, consecutive >=3072 readings 0/2.

2026-10-13T20:56:03.244914+00:00 — overnight RAM 1934.05MiB, consecutive >=3072 readings 0/2.

2026-10-13T21:01:03.301479+00:00 — overnight RAM 1752.99MiB, consecutive >=3072 readings 0/2.

2026-10-13T21:06:03.320085+00:00 — overnight RAM 1936.19MiB, consecutive >=3072 readings 0/2.

2026-10-13T21:11:03.324506+00:00 — overnight RAM 1860.94MiB, consecutive >=3072 readings 0/2.

2026-10-13T21:16:03.328434+00:00 — overnight RAM 1876.38MiB, consecutive >=3072 readings 0/2.

2026-10-13T21:21:03.333342+00:00 — overnight RAM 1974.67MiB, consecutive >=3072 readings 0/2.

2026-10-13T21:26:03.336175+00:00 — overnight RAM 1751.52MiB, consecutive >=3072 readings 0/2.

2026-10-13T21:31:03.363731+00:00 — overnight RAM 1761.84MiB, consecutive >=3072 readings 0/2.

2026-10-13T21:36:03.368559+00:00 — overnight RAM 1930.5MiB, consecutive >=3072 readings 0/2.

2026-10-13T21:41:03.416194+00:00 — overnight RAM 1861.98MiB, consecutive >=3072 readings 0/2.

2026-10-13T21:46:03.457494+00:00 — overnight RAM 1952.8MiB, consecutive >=3072 readings 0/2.

2026-10-13T21:51:03.459802+00:00 — overnight RAM 2040.47MiB, consecutive >=3072 readings 0/2.

2026-10-13T21:56:03.490112+00:00 — overnight RAM 1883.56MiB, consecutive >=3072 readings 0/2.

2026-10-13T22:01:03.494865+00:00 — overnight RAM 1829.17MiB, consecutive >=3072 readings 0/2.

2026-10-13T22:06:03.499654+00:00 — overnight RAM 1914.8MiB, consecutive >=3072 readings 0/2.

2026-10-13T22:11:03.502877+00:00 — overnight RAM 1883.33MiB, consecutive >=3072 readings 0/2.

2026-10-13T22:16:03.509114+00:00 — overnight RAM 1856.86MiB, consecutive >=3072 readings 0/2.

2026-10-13T22:21:03.544609+00:00 — overnight RAM 1920.61MiB, consecutive >=3072 readings 0/2.

2026-10-13T22:26:03.546901+00:00 — overnight RAM 1885.98MiB, consecutive >=3072 readings 0/2.

2026-10-13T22:31:03.551408+00:00 — overnight RAM 1865.79MiB, consecutive >=3072 readings 0/2.

2026-10-13T22:36:03.600854+00:00 — overnight RAM 2073.76MiB, consecutive >=3072 readings 0/2.

2026-10-13T22:41:03.603551+00:00 — overnight RAM 2044.16MiB, consecutive >=3072 readings 0/2.

2026-10-13T22:46:03.606119+00:00 — overnight RAM 3302.91MiB, consecutive >=3072 readings 1/2.

2026-10-13T22:51:03.609305+00:00 — overnight RAM 3261.95MiB, consecutive >=3072 readings 2/2.

2026-10-13T22:51:03.643697+00:00 — bounded RAM wait ready; no guard lowered.

2026-10-14T00:20:46.1679654Z — bounded gate passed; actual BEFORE queue admission RAM 1947.29 MiB

2026-10-14T00:21:25.396304+00:00 — before-10: actual free RAM 2047.59MiB, required3072.


2026-10-14T00:21:25.426521+00:00
<!-- CP25 CERTIFIED TABLES START -->

### CP25 certified overnight measurements

Harness limits: **5 ms artificial delay per Bot API RPC; 0.1 customer
messages/s/shop** (three customer updates plus one owner announcement).
Reminder and order tasks run sequentially in **100-shop batches**, each
with a fresh asyncio loop. Broker and prefork scheduling are excluded.
Tick totals describe a single-process upper bound, not a production
Celery fleet figure. These runs cannot certify 4/8/24 GB fleet capacity.
Startup guard: 3072 MiB at every scale; two consecutive five-minute
readings before queue admission. Runtime floor remains 512 MiB.
Results with sampled free RAM below 1024 MiB are excluded as pressure
runs. No unmeasured row is extrapolated. RSS/shop is amortized measured
process RSS including fixed overhead, not an incremental memory slope.

Before source: clean `f8f73b8405322ec99cb1e06305fc9f7330f31df0`.

**BEFORE**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|not run: RAM (precheck <3072MiB)|—|2047.59375 / —|—|—|—|—|
|25|queued; RAM gate pending|—|—|—|—|—|—|
|50|queued; RAM gate pending|—|—|—|—|—|—|
|100|queued; RAM gate pending|—|—|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

**AFTER**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|queued; RAM gate pending|—|—|—|—|—|—|
|25|queued; RAM gate pending|—|—|—|—|—|—|
|50|queued; RAM gate pending|—|—|—|—|—|—|
|100|queued; RAM gate pending|—|—|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

Full certificates/raw measurements: `docs/capacity/cp25-clean-*.json`.

<!-- CP25 CERTIFIED TABLES END -->

2026-10-14T00:21:25.426521+00:00 — before-25: actual free RAM 2045.14MiB, required3072.


2026-10-14T00:21:25.466731+00:00
<!-- CP25 CERTIFIED TABLES START -->

### CP25 certified overnight measurements

Harness limits: **5 ms artificial delay per Bot API RPC; 0.1 customer
messages/s/shop** (three customer updates plus one owner announcement).
Reminder and order tasks run sequentially in **100-shop batches**, each
with a fresh asyncio loop. Broker and prefork scheduling are excluded.
Tick totals describe a single-process upper bound, not a production
Celery fleet figure. These runs cannot certify 4/8/24 GB fleet capacity.
Startup guard: 3072 MiB at every scale; two consecutive five-minute
readings before queue admission. Runtime floor remains 512 MiB.
Results with sampled free RAM below 1024 MiB are excluded as pressure
runs. No unmeasured row is extrapolated. RSS/shop is amortized measured
process RSS including fixed overhead, not an incremental memory slope.

Before source: clean `f8f73b8405322ec99cb1e06305fc9f7330f31df0`.

**BEFORE**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|not run: RAM (precheck <3072MiB)|—|2047.59375 / —|—|—|—|—|
|25|not run: RAM (precheck <3072MiB)|—|2045.140625 / —|—|—|—|—|
|50|queued; RAM gate pending|—|—|—|—|—|—|
|100|queued; RAM gate pending|—|—|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

**AFTER**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|queued; RAM gate pending|—|—|—|—|—|—|
|25|queued; RAM gate pending|—|—|—|—|—|—|
|50|queued; RAM gate pending|—|—|—|—|—|—|
|100|queued; RAM gate pending|—|—|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

Full certificates/raw measurements: `docs/capacity/cp25-clean-*.json`.

<!-- CP25 CERTIFIED TABLES END -->

2026-10-14T00:21:25.466731+00:00 — before-50: actual free RAM 2044.31MiB, required3072.


2026-10-14T00:21:25.509859+00:00
<!-- CP25 CERTIFIED TABLES START -->

### CP25 certified overnight measurements

Harness limits: **5 ms artificial delay per Bot API RPC; 0.1 customer
messages/s/shop** (three customer updates plus one owner announcement).
Reminder and order tasks run sequentially in **100-shop batches**, each
with a fresh asyncio loop. Broker and prefork scheduling are excluded.
Tick totals describe a single-process upper bound, not a production
Celery fleet figure. These runs cannot certify 4/8/24 GB fleet capacity.
Startup guard: 3072 MiB at every scale; two consecutive five-minute
readings before queue admission. Runtime floor remains 512 MiB.
Results with sampled free RAM below 1024 MiB are excluded as pressure
runs. No unmeasured row is extrapolated. RSS/shop is amortized measured
process RSS including fixed overhead, not an incremental memory slope.

Before source: clean `f8f73b8405322ec99cb1e06305fc9f7330f31df0`.

**BEFORE**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|not run: RAM (precheck <3072MiB)|—|2047.59375 / —|—|—|—|—|
|25|not run: RAM (precheck <3072MiB)|—|2045.140625 / —|—|—|—|—|
|50|not run: RAM (precheck <3072MiB)|—|2044.30859375 / —|—|—|—|—|
|100|queued; RAM gate pending|—|—|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

**AFTER**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|queued; RAM gate pending|—|—|—|—|—|—|
|25|queued; RAM gate pending|—|—|—|—|—|—|
|50|queued; RAM gate pending|—|—|—|—|—|—|
|100|queued; RAM gate pending|—|—|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

Full certificates/raw measurements: `docs/capacity/cp25-clean-*.json`.

<!-- CP25 CERTIFIED TABLES END -->

2026-10-14T00:21:25.511065+00:00 — before-100: actual free RAM 2043.80MiB, required3072.


2026-10-14T00:21:25.560139+00:00
<!-- CP25 CERTIFIED TABLES START -->

### CP25 certified overnight measurements

Harness limits: **5 ms artificial delay per Bot API RPC; 0.1 customer
messages/s/shop** (three customer updates plus one owner announcement).
Reminder and order tasks run sequentially in **100-shop batches**, each
with a fresh asyncio loop. Broker and prefork scheduling are excluded.
Tick totals describe a single-process upper bound, not a production
Celery fleet figure. These runs cannot certify 4/8/24 GB fleet capacity.
Startup guard: 3072 MiB at every scale; two consecutive five-minute
readings before queue admission. Runtime floor remains 512 MiB.
Results with sampled free RAM below 1024 MiB are excluded as pressure
runs. No unmeasured row is extrapolated. RSS/shop is amortized measured
process RSS including fixed overhead, not an incremental memory slope.

Before source: clean `f8f73b8405322ec99cb1e06305fc9f7330f31df0`.

**BEFORE**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|not run: RAM (precheck <3072MiB)|—|2047.59375 / —|—|—|—|—|
|25|not run: RAM (precheck <3072MiB)|—|2045.140625 / —|—|—|—|—|
|50|not run: RAM (precheck <3072MiB)|—|2044.30859375 / —|—|—|—|—|
|100|not run: RAM (precheck <3072MiB)|—|2043.8046875 / —|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

**AFTER**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|queued; RAM gate pending|—|—|—|—|—|—|
|25|queued; RAM gate pending|—|—|—|—|—|—|
|50|queued; RAM gate pending|—|—|—|—|—|—|
|100|queued; RAM gate pending|—|—|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

Full certificates/raw measurements: `docs/capacity/cp25-clean-*.json`.

<!-- CP25 CERTIFIED TABLES END -->

2026-10-14T00:21:25.560139+00:00 — before-500: actual free RAM 2041.76MiB, required3072.


2026-10-14T00:21:25.589523+00:00
<!-- CP25 CERTIFIED TABLES START -->

### CP25 certified overnight measurements

Harness limits: **5 ms artificial delay per Bot API RPC; 0.1 customer
messages/s/shop** (three customer updates plus one owner announcement).
Reminder and order tasks run sequentially in **100-shop batches**, each
with a fresh asyncio loop. Broker and prefork scheduling are excluded.
Tick totals describe a single-process upper bound, not a production
Celery fleet figure. These runs cannot certify 4/8/24 GB fleet capacity.
Startup guard: 3072 MiB at every scale; two consecutive five-minute
readings before queue admission. Runtime floor remains 512 MiB.
Results with sampled free RAM below 1024 MiB are excluded as pressure
runs. No unmeasured row is extrapolated. RSS/shop is amortized measured
process RSS including fixed overhead, not an incremental memory slope.

Before source: clean `f8f73b8405322ec99cb1e06305fc9f7330f31df0`.

**BEFORE**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|not run: RAM (precheck <3072MiB)|—|2047.59375 / —|—|—|—|—|
|25|not run: RAM (precheck <3072MiB)|—|2045.140625 / —|—|—|—|—|
|50|not run: RAM (precheck <3072MiB)|—|2044.30859375 / —|—|—|—|—|
|100|not run: RAM (precheck <3072MiB)|—|2043.8046875 / —|—|—|—|—|
|500|not run: RAM (precheck <3072MiB)|—|2041.7578125 / —|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

**AFTER**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|queued; RAM gate pending|—|—|—|—|—|—|
|25|queued; RAM gate pending|—|—|—|—|—|—|
|50|queued; RAM gate pending|—|—|—|—|—|—|
|100|queued; RAM gate pending|—|—|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

Full certificates/raw measurements: `docs/capacity/cp25-clean-*.json`.

<!-- CP25 CERTIFIED TABLES END -->

2026-10-14T00:21:25.589523+00:00 — before-1000: actual free RAM 2040.80MiB, required3072.


2026-10-14T00:21:25.616466+00:00
<!-- CP25 CERTIFIED TABLES START -->

### CP25 certified overnight measurements

Harness limits: **5 ms artificial delay per Bot API RPC; 0.1 customer
messages/s/shop** (three customer updates plus one owner announcement).
Reminder and order tasks run sequentially in **100-shop batches**, each
with a fresh asyncio loop. Broker and prefork scheduling are excluded.
Tick totals describe a single-process upper bound, not a production
Celery fleet figure. These runs cannot certify 4/8/24 GB fleet capacity.
Startup guard: 3072 MiB at every scale; two consecutive five-minute
readings before queue admission. Runtime floor remains 512 MiB.
Results with sampled free RAM below 1024 MiB are excluded as pressure
runs. No unmeasured row is extrapolated. RSS/shop is amortized measured
process RSS including fixed overhead, not an incremental memory slope.

Before source: clean `f8f73b8405322ec99cb1e06305fc9f7330f31df0`.

**BEFORE**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|not run: RAM (precheck <3072MiB)|—|2047.59375 / —|—|—|—|—|
|25|not run: RAM (precheck <3072MiB)|—|2045.140625 / —|—|—|—|—|
|50|not run: RAM (precheck <3072MiB)|—|2044.30859375 / —|—|—|—|—|
|100|not run: RAM (precheck <3072MiB)|—|2043.8046875 / —|—|—|—|—|
|500|not run: RAM (precheck <3072MiB)|—|2041.7578125 / —|—|—|—|—|
|1000|not run: RAM (precheck <3072MiB)|—|2040.80078125 / —|—|—|—|—|

**AFTER**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|queued; RAM gate pending|—|—|—|—|—|—|
|25|queued; RAM gate pending|—|—|—|—|—|—|
|50|queued; RAM gate pending|—|—|—|—|—|—|
|100|queued; RAM gate pending|—|—|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

Full certificates/raw measurements: `docs/capacity/cp25-clean-*.json`.

<!-- CP25 CERTIFIED TABLES END -->

2026-10-14T00:21:25.617469+00:00 — before-25-profile: actual free RAM 2038.83MiB, required3072.


2026-10-14T00:21:25.652542+00:00
<!-- CP25 CERTIFIED TABLES START -->

### CP25 certified overnight measurements

Harness limits: **5 ms artificial delay per Bot API RPC; 0.1 customer
messages/s/shop** (three customer updates plus one owner announcement).
Reminder and order tasks run sequentially in **100-shop batches**, each
with a fresh asyncio loop. Broker and prefork scheduling are excluded.
Tick totals describe a single-process upper bound, not a production
Celery fleet figure. These runs cannot certify 4/8/24 GB fleet capacity.
Startup guard: 3072 MiB at every scale; two consecutive five-minute
readings before queue admission. Runtime floor remains 512 MiB.
Results with sampled free RAM below 1024 MiB are excluded as pressure
runs. No unmeasured row is extrapolated. RSS/shop is amortized measured
process RSS including fixed overhead, not an incremental memory slope.

Before source: clean `f8f73b8405322ec99cb1e06305fc9f7330f31df0`.

**BEFORE**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|not run: RAM (precheck <3072MiB)|—|2047.59375 / —|—|—|—|—|
|25|not run: RAM (precheck <3072MiB)|—|2045.140625 / —|—|—|—|—|
|50|not run: RAM (precheck <3072MiB)|—|2044.30859375 / —|—|—|—|—|
|100|not run: RAM (precheck <3072MiB)|—|2043.8046875 / —|—|—|—|—|
|500|not run: RAM (precheck <3072MiB)|—|2041.7578125 / —|—|—|—|—|
|1000|not run: RAM (precheck <3072MiB)|—|2040.80078125 / —|—|—|—|—|

**AFTER**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|queued; RAM gate pending|—|—|—|—|—|—|
|25|queued; RAM gate pending|—|—|—|—|—|—|
|50|queued; RAM gate pending|—|—|—|—|—|—|
|100|queued; RAM gate pending|—|—|—|—|—|—|
|500|queued; RAM gate pending|—|—|—|—|—|—|
|1000|queued; RAM gate pending|—|—|—|—|—|—|

Full certificates/raw measurements: `docs/capacity/cp25-clean-*.json`.

<!-- CP25 CERTIFIED TABLES END -->

2026-10-14T00:21:25.653542+00:00 — Overnight before stage: profile_review; inspect ledger before continuing.

2026-10-14T00:22:52.8832918Z — documentary closeout actual free RAM 1884.61 MiB; no benchmark/test started


2026-10-14T00:22:53.461644+00:00 — OVERNIGHT STOP (RAM)
<!-- CP25 CERTIFIED TABLES START -->

### CP25 certified overnight measurements

Harness limits: **5 ms artificial delay per Bot API RPC; 0.1 customer
messages/s/shop** (three customer updates plus one owner announcement).
Reminder and order tasks run sequentially in **100-shop batches**, each
with a fresh asyncio loop. Broker and prefork scheduling are excluded.
Tick totals describe a single-process upper bound, not a production
Celery fleet figure. These runs cannot certify 4/8/24 GB fleet capacity.
Startup guard: 3072 MiB at every scale; two consecutive five-minute
readings before queue admission. Runtime floor remains 512 MiB.
Results with sampled free RAM below 1024 MiB are excluded as pressure
runs. No unmeasured row is extrapolated. RSS/shop is amortized measured
process RSS including fixed overhead, not an incremental memory slope.

Before source: clean `f8f73b8405322ec99cb1e06305fc9f7330f31df0`.

**BEFORE**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|not run: RAM (precheck <3072MiB)|—|2047.59375 / —|—|—|—|—|
|25|not run: RAM (precheck <3072MiB)|—|2045.140625 / —|—|—|—|—|
|50|not run: RAM (precheck <3072MiB)|—|2044.30859375 / —|—|—|—|—|
|100|not run: RAM (precheck <3072MiB)|—|2043.8046875 / —|—|—|—|—|
|500|not run: RAM (precheck <3072MiB)|—|2041.7578125 / —|—|—|—|—|
|1000|not run: RAM (precheck <3072MiB)|—|2040.80078125 / —|—|—|—|—|

**AFTER**

|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|
|---|---|---|---|---|---|---|---|
|10|not run: RAM (BEFORE profile refused; AFTER not attempted)|—|—|—|—|—|—|
|25|not run: RAM (BEFORE profile refused; AFTER not attempted)|—|—|—|—|—|—|
|50|not run: RAM (BEFORE profile refused; AFTER not attempted)|—|—|—|—|—|—|
|100|not run: RAM (BEFORE profile refused; AFTER not attempted)|—|—|—|—|—|—|
|500|not run: RAM (BEFORE profile refused; AFTER not attempted)|—|—|—|—|—|—|
|1000|not run: RAM (BEFORE profile refused; AFTER not attempted)|—|—|—|—|—|—|

Full certificates/raw measurements: `docs/capacity/cp25-clean-*.json`.


Overnight closeout: bounded RAM gate passed at22:51UTC (3302.91 then3261.95MiB),
but actual admission at00:20UTC Oct14 was1947.29MiB. Scale-specific BEFORE
checks were2047.59/2045.14/2044.31/2043.80/2041.76/2040.80MiB; diagnostic25
precheck2038.83MiB. ALL were refused once. No capacity role was launched.
AFTER was not attempted because required BEFORE/profile work was refused.
No latency/tick/CPU-per-shop comparison or new extrapolation exists; profile
attribution/fix/full gate/secrets/push remain waiting for RAM. No client fix
was made. Two earlier NEW2-shop prerequisite runs remain diagnostics only.
<!-- CP25 CERTIFIED TABLES END -->

Before driver ended normally; no owned benchmark process/lock remains. The original bounded wait is complete and MUST NOT restart. All7 BEFORE checks refused once, no retries. Native heartbeat is being paused: actual25 profile prerequisite refused. Resume requires owner to free RAM and authorize a fresh queue attempt/directory; preserve this ledger and all previous proofs. The old one-shot command refuses its attempted ledger intentionally. No AFTER stage, client fix, full gate, new scan, push or merge was performed.

2026-10-14T00:23 UTC — Native heartbeat cp25-overnight-ram-and-capacity confirmed PAUSED by app. No automatic retry or new six-hour wait. Last documentary precheck1884.61MiB; no owned capacity job remains active.

2026-10-14T00:29:20.6333518Z — daytime initial free RAM 1857.34 MiB; heartbeat remains PAUSED; no capacity run authorized until owner says RAM is free

2026-10-14T00:33:18.525729+00:00 — daytime candidate-red: free 1874.95MiB; single precheck1280MiB.

2026-10-14T00:33:33.640763+00:00 — candidate-red: exit1; peak221.73MiB; after1935.30MiB.

2026-10-14T00:35:08.435419+00:00 — daytime candidate-green: free 2801.20MiB; single precheck1280MiB.

2026-10-14T00:35:19.889743+00:00 — candidate-green: exit0; peak233.85MiB; after2542.83MiB.

2026-10-14T00:36:51.9901922Z — changed-file lint precheck 2703.29 MiB; daytime only

2026-10-14T00:36:57.597455+00:00 — daytime changed-type: free 2664.70MiB; single precheck1280MiB.

2026-10-14T00:37:00.816036+00:00 — changed-type: exit0; peak166.82MiB; after2498.25MiB.

2026-10-14T00:38:29.323964+00:00 — daytime infra-red: free 2334.65MiB; single precheck1280MiB.

2026-10-14T00:38:32.232971+00:00 — infra-red: exit1; peak98.29MiB; after2235.10MiB.

2026-10-14T00:41:00.879901+00:00 — daytime evening-red: free 909.71MiB; single precheck1280MiB.

2026-10-14T00:43:28.8071888Z — daytime warm startup audit initial precheck 2202.82 MiB (cold boot prohibited now)

2026-10-14T00:43:31.912701+00:00 — Startup docker-wsl: actual precheck 2169.04MiB.

2026-10-14T00:43:36.825833+00:00 — Startup postgres: actual precheck 2182.63MiB.

2026-10-14T00:43:41.175843+00:00 — Startup redis: actual precheck 2166.52MiB.

2026-10-14T00:43:45.009870+00:00 — Startup venv-imports: actual precheck 2142.86MiB.

2026-10-14T00:44:00.808980+00:00 — Startup reference-db-seed: actual precheck 2196.29MiB.

2026-10-14T00:44:01.434824+00:00 — before 10,25,50: precheck actual free RAM 2164.65MiB.

2026-10-14T00:46:15.227368+00:00 — daytime daytime-focused: free 1901.53MiB; single precheck1280MiB.

2026-10-14T00:46:45.648339+00:00 — daytime-focused: exit0; peak250.30MiB; after1292.62MiB.

2026-10-14T00:47:59.112310+00:00 — daytime review-barrier-red: free 1857.67MiB; single precheck1280MiB.

2026-10-14T00:48:04.000760+00:00 — review-barrier-red: exit1; peak89.92MiB; after1727.26MiB.

2026-10-14T00:48:11.389585+00:00 — daytime evening-red-executed: free 1609.90MiB; single precheck1280MiB.

2026-10-14T00:48:15.558804+00:00 — evening-red-executed: exit1; peak89.91MiB; after1776.81MiB.

2026-10-14T02:04:52.5431916Z — new tooling lint/prepared Desktop help precheck 2930.67 MiB

2026-10-14T02:07:00.858004+00:00 — daytime owner-close-red: free 2063.24MiB; single precheck1280MiB.

2026-10-14T02:07:19.436423+00:00 — owner-close-red: exit1; peak241.56MiB; after1112.47MiB.

2026-10-14T02:07:44.7433620Z — final touched-file lint precheck 2399.7 MiB

2026-10-14T02:10:42.380770+00:00 — daytime tooling-client-green: free 1400.26MiB; single precheck1280MiB.

2026-10-14T02:11:16.515271+00:00 — tooling-client-green: exit0; peak235.03MiB; after1319.18MiB.

2026-10-14T02:13:10.054605+00:00 — daytime prepared-tools-type: free 1855.52MiB; single precheck1280MiB.

2026-10-14T02:13:16.848776+00:00 — prepared-tools-type: exit0; peak159.37MiB; after1686.14MiB.

2026-10-14T02:15:33.349970+00:00 — daytime final-prep-focused: free 1506.87MiB; single precheck1280MiB.

2026-10-14T02:15:57.582639+00:00 — final-prep-focused: exit0; peak234.31MiB; after1616.98MiB.

2026-10-14T02:17:24.8558385Z — new guard subset precheck 1257.45 MiB (no old proofs rerun)

Daytime focused budget evidence: completed focused processes peaked98.29/233.85/250.30/235.03MiB; mypy166.82/159.37MiB. Remaining bounded fake/guard jobs use768MiB admission (512MiB reserved job budget +256MiB margin), and remain below1GiB actual peak. This is a focused-test budget only; infrastructure1280 and capacity100+3072 guards are unchanged. Earlier1280MiB focused refusal remains recorded, no heavy run retried.

2026-10-14T02:19:55.7982592Z — bounded NEW assertion guards precheck 2166.36 MiB; estimated512MiB process +256MiB margin

2026-10-14T02:19:57.461060+00:00 — Mutation evening skips infrastructure: actual free RAM 2110.43MiB before focused test.

2026-10-14T02:20:07.464012+00:00 — Mutation evening skips post-infrastructure floor: actual free RAM 1994.32MiB before focused test.

2026-10-14T02:20:13.946307+00:00 — Mutation evening bypasses review barrier: actual free RAM 2085.32MiB before focused test.

2026-10-14T02:20:18.430416+00:00 — Mutation small scale guesses unknown peak: actual free RAM 2136.15MiB before focused test.

2026-10-14T02:20:23.798711+00:00 — Mutation candidate permits closed reuse: actual free RAM 2127.04MiB before focused test.

2026-10-14T02:20:41.648672+00:00 — Mutation candidate loses API timeout: actual free RAM 2111.35MiB before focused test.

2026-10-14T02:21:01.287663+00:00 — Mutation candidate loses token identity: actual free RAM 2023.63MiB before focused test.

2026-10-14T02:21:28.519789+00:00 — Mutation candidate caches client across tasks: actual free RAM 1876.35MiB before focused test.

2026-10-14T02:21:56.475535+00:00 — Mutation candidate omits closure: actual free RAM 1890.23MiB before focused test.

2026-10-14T02:22:16.818708+00:00 — Mutation candidate closes shared client twice: actual free RAM 2059.48MiB before focused test.

2026-10-14T02:22:32.901817+00:00 — Mutation candidate omits exception cleanup: actual free RAM 2078.26MiB before focused test.

2026-10-14T02:22:51.317647+00:00 — Mutation candidate accepts another loop: actual free RAM 1701.70MiB before focused test.

2026-10-14T02:23:24.239895+00:00 — Mutation candidate closes from another loop: actual free RAM 657.02MiB before focused test.

2026-10-14T02:23:58.228850+00:00 — Mutation candidate omits reply pacing: actual free RAM 608.15MiB before focused test.
New mutation selection contained legacy small scale excluded. Prevent its stale anchor from matching with a temporary formatting-only barrier in main load_seed; original bytes saved. All NEW guards finish, then barrier is restored and only NEW assertion catches are persisted. Frozen reference untouched; legacy guard will NOT run.
Mutation job stopped at its640MiB focused precheck, before any legacy guard. Formatting-only exclusion barrier restored byte-exact; load_seed has no Git diff.13 NEW assertion catches preserved; remaining NEW subset waits for RAM. No automatic retry or RAM waiting loop.
Remaining evening command preflight now selects only unproven NEW guard names and explicitly excludes legacy small scale excluded. It completes pending guards after infrastructure/RAM admission, before BEFORE; no old13 catches or old harness proofs are rerun.

2026-10-14T02:37:09.7585501Z — preserve partial proof evidence free RAM 2351.06 MiB; documentary operation only

2026-10-14T02:42:09.7251566Z — final cheap format/lint precheck 2967.61 MiB; reserved512MiB

2026-10-14T02:44:31.071408+00:00 — daytime final-controller-type: free 2977.84MiB; single measured-budget precheck512MiB.

2026-10-14T02:44:33.352149+00:00 — final-controller-type: exit0; peak160.62MiB; after2816.26MiB.

2026-10-14T02:44:37.8084239Z — final changed-file lint/format verification free 2997.24 MiB;512MiB budget

2026-10-14T02:47:01.8281397Z — unrun remaining NEW guard names precheck 3224.93 MiB;768MiB focused budget, one job

2026-10-14T02:47:03.194341+00:00 — Mutation candidate omits reply pacing: actual free RAM 3143.60MiB before focused test.

2026-10-14T02:47:16.472067+00:00 — Mutation candidate loses HTML default: actual free RAM 3076.84MiB before focused test.

2026-10-14T02:47:27.674003+00:00 — Mutation shadow bypasses source cache: actual free RAM 3026.29MiB before focused test.

2026-10-14T02:47:39.529744+00:00 — Mutation shadow skips real filters: actual free RAM 2970.61MiB before focused test.

2026-10-14T02:47:50.634248+00:00 — Mutation shadow cache leaks between sweeps: actual free RAM 2999.17MiB before focused test.

2026-10-14T02:48:01.347506+00:00 — Mutation small peak lowers heavy floor: actual free RAM 2993.55MiB before focused test.

2026-10-14T02:48:04.117679+00:00 — Mutation small peak loses GiB margin: actual free RAM 2954.82MiB before focused test.

2026-10-14T02:48:06.818531+00:00 — Mutation small peak accepts negative value: actual free RAM 2989.05MiB before focused test.

2026-10-14T02:48:09.499677+00:00 — Mutation startup seed accepts large scale: actual free RAM 2972.94MiB before focused test.

2026-10-14T02:48:12.124758+00:00 — Mutation startup bypasses RAM admission: actual free RAM 2967.17MiB before focused test.

2026-10-14T02:48:15.032831+00:00 — Mutation evening bypasses large RAM gate: actual free RAM 2955.29MiB before focused test.

2026-10-14T02:48:17.859202+00:00 — Mutation evening accepts stale profile: actual free RAM 2956.71MiB before focused test.

2026-10-14T02:48:20.472817+00:00 — Mutation evening accepts stale after source: actual free RAM 2966.20MiB before focused test.

2026-10-14T02:48:23.358317+00:00 — Mutation evening accepts pending review: actual free RAM 2928.93MiB before focused test.

2026-10-14T02:48:26.042267+00:00 — Mutation evening omits attribution evidence: actual free RAM 2962.36MiB before focused test.

2026-10-14T02:48:28.846637+00:00 — Mutation static builder ignores resolved root: actual free RAM 2944.55MiB before focused test.

2026-10-14T02:48:40.426885+00:00 — Mutation static builder writes temporary symlink: actual free RAM 2993.07MiB before focused test.

2026-10-14T02:54:00.7466759Z — final metadata formatting precheck 2856.52 MiB;512MiB budget

2026-10-14T02:56:02.325933+00:00 — daytime changed-logging-and-controller: free 2222.69MiB; single measured-budget precheck768MiB.

2026-10-14T02:56:04.771080+00:00 — changed-logging-and-controller: exit0; peak90.31MiB; after2140.45MiB.

2026-10-14T02:56:08.636294+00:00 — daytime final-audit-and-proof-type: free 2239.03MiB; single measured-budget precheck512MiB.

2026-10-14T02:56:10.050440+00:00 — final-audit-and-proof-type: exit0; peak157.88MiB; after2050.48MiB.

2026-10-14T03:00:00.0841969Z — local web commit precheck 2298.53 MiB; no push/full gate

2026-10-14T03:00:04.7501007Z — local shadow cache commit precheck 2272.59 MiB

2026-10-14T03:00:10.0060744Z — local isolated candidate commit precheck 2264.91 MiB

2026-10-14T05:47:53.2928894Z — OWNER authorizes remaining work/all available RAM. Actual free 5310.04 MiB. No assumed RAM; each job keeps its guard. Heartbeat remains PAUSED while active agent works.

2026-10-14T05:51:57.600026+00:00 — daytime tooling-config-final: free 5441.89MiB; single measured-budget precheck512MiB.

2026-10-14T05:52:14.019228+00:00 — tooling-config-final: exit1; peak433.80MiB; after4997.27MiB.

2026-10-14T05:53:06.174836+00:00 — daytime engine-options-red: free 5486.80MiB; single measured-budget precheck768MiB.

2026-10-14T05:55:30.735601+00:00 — daytime engine-options-red-with-infra: free 1925.50MiB; single measured-budget precheck768MiB.

2026-10-14T05:55:41.146177+00:00 — engine-options-red-with-infra: exit1; peak244.17MiB; after1840.60MiB.

2026-10-14T05:56:24.199791+00:00 — daytime engine-options-green: free 1981.43MiB; single measured-budget precheck768MiB.

2026-10-14T05:56:32.401705+00:00 — engine-options-green: exit0; peak243.33MiB; after1827.81MiB.

2026-10-14T05:56:44.910656+00:00 — Mutation engine meter drops task pool option: actual free RAM 2638.85MiB before focused test.

2026-10-14T05:57:10.033111+00:00 — daytime tooling-config-fixed: free 2727.75MiB; single measured-budget precheck512MiB.

2026-10-14T05:57:12.339288+00:00 — tooling-config-fixed: exit0; peak157.66MiB; after2572.50MiB.

2026-10-14T05:57:54.482738+00:00 — Startup docker-wsl-start: actual precheck 2783.83MiB.

2026-10-14T05:57:57.060810+00:00 — Startup docker-wsl: actual precheck 2727.23MiB.

2026-10-14T05:57:59.807502+00:00 — Startup postgres: actual precheck 2759.47MiB.

2026-10-14T05:58:02.992978+00:00 — Startup redis: actual precheck 2755.8MiB.

2026-10-14T05:58:06.215463+00:00 — Startup venv-imports: actual precheck 2707.93MiB.

2026-10-14T05:58:13.692767+00:00 — Startup reference-db-seed: actual precheck 2749.0MiB.

2026-10-14T05:58:14.140420+00:00 — before 10,25,50: precheck actual free RAM 2710.27MiB.

2026-10-14T05:58:23.644498+00:00 — Evening AFTER infrastructure: actual free RAM 2756.38MiB; floor3072.
