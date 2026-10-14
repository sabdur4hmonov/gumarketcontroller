# CP25 reminder/client review — hypothesis, not proven

Reviewed current CP25 sources on2026-10-14; baseline source remains clean
f8f73b8405322ec99cb1e06305fc9f7330f31df0. Line references below describe the
current tree. No daytime capacity/profile run establishes the historical
~1 second/shop attribution. Memory-pressure timings are NOT a baseline.

|Step|Source reference|Observed code structure; no timing attribution|
|---|---|---|
|New loop|src/gulbot/worker/tasks.py:174|Public task calls asyncio.run for its task body.|
|Task engine|src/gulbot/db/session.py:81|One engine per task; pool bounded; disposed in finally. Not one engine per shop.|
|Heartbeat engine|src/gulbot/services/shop_health.py:224|Heartbeat wrapper records with its own loop/engine; profile must separate this overhead.|
|Limiter|src/gulbot/worker/tasks.py:63|One RateLimiter per reminder task; buckets keyed by shop and chat.|
|Credentials|src/gulbot/worker/tasks.py:68; src/gulbot/bot/registry.py:181|Load encrypted credentials once per task.|
|Bot/session creation|src/gulbot/bot/registry.py:140; src/gulbot/bot/factory.py:75|Lazy bot per distinct token; each factory call creates AiohttpSession plus ReplyPolicy.|
|TLS initialization|.venv/Lib/site-packages/aiogram/client/session/aiohttp.py:86|Installed SDK initializes an SSL context/cert store in each AiohttpSession constructor.|
|HTTP creation|.venv/Lib/site-packages/aiogram/client/session/aiohttp.py:116|ClientSession/connector are opened lazily in the running task loop.|
|Serial sending|src/gulbot/sending/dispatcher.py:570|Each claimed group awaits ledger work, limiter, attachment and transport before the next; commit at635.|
|Pacing|src/gulbot/sending/rate_limit.py:115|Only a depleted shop/chat bucket causes sleep; distinct shops' first sends do not share one global bucket.|
|Serial closure|src/gulbot/bot/registry.py:153|Iterates bots and awaits each session.close sequentially.|
|SDK close|.venv/Lib/site-packages/aiogram/client/session/aiohttp.py:137|An opened SDK HTTP session waits0.25s after close; potentially linear with distinct tokens.|
|Harness batch|scripts/cp25_load/load_roles.py:166|Public reminder/order task bodies run sequential100-shop slices, each with fresh loops; fake RPC delay5ms, not1s.|

Hypothesis: repeated SSL/cert initialization, sequential SDK closure and serial
per-group transactions/attachment work contribute to the slope. Static code
proves their existence, not their measured shares. Tonight's diagnostic25
profile must compare TLS/bot creation, closure, engine/connect/query, limiter
scheduled waits and transport spans; coroutine cumulative times overlap and
must not be added indiscriminately. Broker/prefork scheduling is excluded.

## Candidate design; no activation before attribution

`src/gulbot/bot/batch_client.py` is an isolated candidate, not imported or used
by worker tasks. One task context creates one HTTP session and ReplyPolicy,
then builds a separate Bot wrapper per token using BotRegistry's existing
credential resolution. Bot IDs, per-bot/chat pacing and file_id tenancy remain
distinct. The context closes its session exactly once, including exceptions;
closed batches and access from another loop are rejected. No module-level
async client, cached session, reused engine or concurrent AsyncSession work.

Do not change the polling registry: each shop poller retains independent fault
handling. Sharing one bounded connector inside one worker batch is different
from sharing a Bot identity. Keep the15s API timeout, HTML defaults and per-bot
ReplyPolicy keys. DB engines already belong to the task and are not cached.

Fake two-asyncio.run tests verify lifetime, token identity, same-session reuse,
single closure and exception cleanup now. After the actual profile confirms a
material client cost, add a SYNCHRONOUS real-local-Bot-API test exercising I/O
on two closed loops and mutation-prove it, then wire only worker batch paths.
Until that review, the candidate must not affect AFTER measurements.
