# CP25 reminder tick attribution

Measured diagnostic25 on clean f8f73b8405322ec99cb1e06305fc9f7330f31df0.
Admission6454.32MiB, minimum sampled free5524.09MiB. Diagnostic cProfile is
excluded from the unprofiled capacity table. Certified raw evidence:
capacity/cp25-clean-before-25-tick-profile.json.

|Independent wall span|Reminder seconds|Order seconds|
|---|---:|---:|
|Whole public task including heartbeats|13.7863|13.6189|
|25 Bot/session constructions|5.3679|4.9784|
|Registry closure, one call closing25 SDK sessions sequentially|6.5139|6.5112|
|DB engine construction,3 calls|0.0484|0.0022|
|DB connection setup,3 calls|0.2657|0.2467|
|SQL query wall time,132/104 queries|0.3811|0.3217|
|Telegram transport,25 calls|0.4612|0.3392|
|Limiter scheduled wait|0|not used|

The separate construction and end-of-task closure stages account for86.2%
of reminder wall time. cProfile identifies25 SSLContext.load_verify_locations
calls taking5.3472s; the order task's25 calls take4.9610s. Reminder thread CPU
is6.1875s, order5.625s. GetQueuedCompletionStatus time represents waiting,
not CPU; overlapping coroutine cumulative times are not summed here.

The static hypothesis is confirmed for repeated SSL certificate loading and
sequential SDK closure. The DB/client ownership rule is retained: one HTTP
session is created for a worker batch, Bot identities and per-bot/chat pacing
stay separate, and the existing task finally closes that session once on the
owning loop. Pure SSL construction is offloaded; actual connections open on
that task's loop. Each new task gets a fresh session and engine. Polling
clients remain independent. Custom registries and legacy zero-argument
factory injection retain their existing explicit client ownership.

The real two-asyncio.run worker guards exercise actual localhost HTTP through
the normal production factory, both reminder/order paths and error cleanup.
No improvement percentage is claimed until unprofiled AFTER measurements.

BEFORE1000 is a FAILED/stalled attempt, not RAM and not a valid latency row:
3701/4000 expected successful replies, last success over51minutes old at the
owner-requested faster completion. Its worker completed1000 reminder and1000
order sends (534.494/525.5077s), but those partial role results do not certify
the whole workload or capacity. No completed10/25/50/100/500 scale was rerun.
