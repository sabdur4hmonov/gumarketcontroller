# CP25 capacity harness

CP24 is merged at `0d5072a`. This harness is integrated into the working tree
but is not yet committed or capacity evidence. Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.cp25_load.capacity --scales 2 --output .cp22-stage/cp25/runs/smoke
```

The 2-shop smoke must pass before any 100/500/1000 run. Both diagnostic smokes
passed on 2026-10-13 when RAM recovered after initial refusals. A later
100-shop attempt reached all 100 pollers, then aborted at 509 MiB free RAM.
No fleet baseline exists yet. Retry 100 with at least 3 GiB available, then
use its observed peak to budget larger scales.

The intended measured workload uses the production per-shop pollers, update
middleware/handlers, announcement confirmation and public reminder/order task
bodies against a localhost-only fake Telegram API. It seeds three existing
customers, one ready announcement preview, one due reminder and one due order
ping per shop in a comment-marked scratch database. Customers send three
/start waves ten seconds apart; each owner publishes one prepared preview.
Image generation and STT throughput are excluded and require separate budgets.

Normal scales are 100/500/1000; 2 shops is only an end-to-end sanity run.
The fake API adds 5 ms per RPC, honours client long-poll timeouts and does not
model WAN, Telegram infrastructure or real TLS handshake latency. Process
counters include role startup/shutdown after Python module imports; peak RSS
includes imports. The coordinator and Postgres/Redis are measured separately;
container maxima are samples with actual timestamps and a five-second pause
between calls, not kernel peak RSS. Docker stats calls have a 15-second timeout.
Public task bodies execute on
fresh asyncio.run loops with heartbeats. Direct task invocation excludes
Celery broker/prefork scheduling overhead. These boundaries must accompany
any baseline table or extrapolated server guide.

Private resources: gulbot_cp25_load (ownership COMMENT required before reset),
gulbot_cp25_test for repo tests; Redis broker6/results7/test8/FSM15. Hold the
admin-database advisory lease for the whole scratch run. Clean only the run's
cp25-load:<nonce> FSM prefix; never clear somebody else's Redis namespace.
Synthetic encrypted credentials and localhost endpoint/token guards prevent
real Telegram traffic. Sample JPEG bytes are an original solid-colour fixture.

Startup requires at least 1024 MiB available. A 512 MiB floor is checked during
readiness, poll warmup, wave pauses and result collection. A low-memory or
incomplete run is a failure, not a result. After observed small-scale peaks,
check enough additional headroom before a larger scale instead of assuming
1024 MiB suffices for every fleet size.

Reply flood and poll flood are separate scenarios. A poll-only failure still
allows every shop's outgoing reminder/order sends; other token/network/send
faults exclude the bad shop from healthy deliveries. Validate outbox counts
before publishing result.json and independently reconcile actual delivery
pairs and duplicates. Finishing only the customer replies is insufficient.

Before a baseline: finish the updated mutation proof and review the fault
scenarios at scale. The real Postgres lease and cancellation release tests,
actual 2-shop execution/cleanup and resource-window reporting pass.
All 36 focused tests pass; strict typing and Ruff pass. The final complete
seven-guard sweep passed on assertions after initial RAM-aborted attempts.
No production performance fixes or measured baseline currently exist.
