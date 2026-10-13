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
