# Gulbot

Telegram reminder + ordering bot for a flower shop in Uzbekistan. Customers save
recurring personal dates; the bot reminds them ahead of each one, suggests
bouquets from the shop's Telegram channel, takes the order, and hands it to the
shop's group chat.

Standalone project. It shares no code, database, or container with anything else
on this machine.

## Pinned environment decisions

| Decision | Value | Why |
|---|---|---|
| Repo root | `C:\dev\gulbot` | No spaces in the path; not inside a Telegram download folder |
| Python | 3.11 | 3.14 is the machine default but wheel coverage for Celery/asyncpg is unproven there |
| Postgres | host port **5433** | 5432 is taken by an unrelated project |
| Redis | host port **6380** | 6379 is taken by an unrelated project |
| Compose project | `gulbot` | Namespaces containers, network, and volumes |
| Timezone | `zoneinfo("Asia/Tashkent")` | Never a hardcoded `+5` |

**Not using WSL2.** Docker Desktop runs on the WSL2 backend, but the only distro
present is `docker-desktop` (Docker's internal utility VM), not a distro to
develop in. The bind-mount slowness that would justify moving into WSL2 does not
apply here anyway: Postgres and Redis use *named volumes*, and the app and test
suite run on the Windows host against `localhost`. The repo is never bind-mounted
into a container. Keep it that way.

## Redis logical databases

`0` Celery broker · `1` Celery results · `2` aiogram FSM · `15` tests.
Separated so a broker purge can never wipe live FSM state.

## Getting started

```
.\make.ps1 install   # 3.11 venv + dependencies
.\make.ps1 up        # Postgres + Redis, waits for healthy
.\make.ps1 check     # lint + typecheck + tests -- the gate
```

`make` is not installed on the Windows dev box, so `make.ps1` mirrors the
`Makefile`. The Makefile is canonical; keep both in sync.

## The `check` target

`check` is the build gate: `lint -> typecheck -> shadow -> test`. It stops at the
first failure and exits 1. It must stay green on every commit.

## The handler-shadowing sweep

Handler shadowing is a **registration-order** bug: aiogram dispatches to the
first handler whose filters pass, so a handler registered earlier can make a
later one unreachable. Ordering exists only at registration time, which is why
`make shadow` walks the **live dispatcher** after every router is included. A
static scan of the source cannot see registration order and would not catch it.

The sweep probes every `(state, trigger)` pair the bot can receive -- every
button label in every language, plus free text and `/start`, in every declared
FSM state and at state `None` -- and evaluates the real filter chain of every
registered handler in order. It reports:

* `DUPLICATE` -- two or more non-fallback handlers match the same probe.
* `FALLBACK_FIRST` -- a handler flagged `fallback` matches before a real one,
  i.e. a catch-all is swallowing input meant for a flow.

A fallback matching *after* the real handler is correct and is not reported.

It probes both `message` and `callback_query`: message triggers come from the
i18n catalog, callback triggers from each `CallbackData` factory's `samples()`.
Adding a button or an inline factory therefore extends the gate automatically --
there is no list to keep in sync.

Two rules keep it meaningful:

1. Every text-waiting handler carries a state gate (`StateFilter(None)` counts).
2. Intentional catch-alls declare `flags={"catch_all": True}`. That covers the
   global unknown-text fallback AND any state that waits for free text, since
   such a state accepts anything by design. A catch-all may be shadowed, and may
   precede another catch-all; it may not precede a *specific* handler.

Routers are built by factory functions, not module-level singletons: an aiogram
`Router` can only be attached to one `Dispatcher`, so a singleton makes a second
dispatcher -- in tests, or in the sweep -- impossible to build.

## Tests

Tests run against real Postgres, never sqlite: this project depends on
`FOR UPDATE SKIP LOCKED`, `ON CONFLICT`, and `pg_trgm`, and a fake would prove
nothing. Each test runs inside a transaction that is always rolled back, so the
suite needs no reset between runs. `tests/test_harness_isolation.py` fails if
that rollback ever breaks.

Tests marked `infra` need `.\make.ps1 up` first.

## Celery on Windows (decided at CP5)

Celery's default **prefork pool does not work on Windows**. The VPS runs prefork;
locally the worker needs `--pool=solo` or `--pool=threads`.

This matters for CP6's concurrency test. The test proves that two workers racing
the same due notification row produce exactly one send. A solo pool across **two
separate worker processes** still races correctly and the test is meaningful. A
solo pool inside **one process** does not race at all, and the test would pass
vacuously while proving nothing. CP5 must document the exact local invocation,
and CP6's race test must assert it is running against more than one process.

## For the shop: how to post to the catalogue channel

Written for whoever runs the shop, not for a developer. It belongs in a
shop-facing help doc once one exists; it is here because that is the only place
it currently can be.

**Promote the bot to channel admin BEFORE posting anything you expect indexed.**
A post made earlier generates no update at all. Telegram never backfills and the
Bot API cannot read channel history, so an earlier post is gone for good --
repost it.

**Every post needs a photo and at least one hashtag.** A post with no photo, or
a photo with no hashtag, is ignored on purpose: an announcement is not a
catalogue entry. `#150000` does not count as a hashtag -- a tag of digits alone
is read as a price or a phone number, never a flower.

**ONE POST PER BOUQUET. Never mix flower types in a single album.**

This is the rule that matters most, because breaking it fails silently.

  - Several photos of the SAME bouquet -- different angles, different light --
    posted together as one album with one caption: correct. They become ONE
    product, which is exactly right.
  - DIFFERENT bouquets posted together as one album under one caption: wrong.
    They also become one product, because an album is one caption and one
    price, and the catalogue has no way to tell that the third photo was a
    different flower. The other bouquets simply never enter the catalogue, with
    no error anywhere.

So: one album per distinct bouquet, its own caption, its own hashtags. Roses and
tulips never share a post.

**Write the price with a currency or price word** -- `450 000 so'm`, or
`Narxi: 450 000`. A bare number is taken as a probable price and shown with less
confidence; a number next to a phone number is ignored entirely. A post with no
price is still shown, captioned "narx operator tomonidan tasdiqlanadi".

**If your word for a flower is not the customer's word, add an alias row.**
Customers choose a favourite from a fixed list -- `atirgul`, `tyulpan`, `lola` --
and that list does not change. If you tag your roses `#gulkinder` or `#roza`, a
row in `hashtag_aliases` mapping your word to `atirgul` is what makes those
customers see your roses first. Without it nothing breaks: they still get a
reminder and still get a bouquet, just the newest one rather than their
favourite.

There is no admin screen for this yet -- it is a `psql` insert, or ask whoever
runs the deployment. Deliberately deferred rather than forgotten.

**Editing a post works.** Change the caption and the price, name and hashtags
are re-read. Removing every hashtag from a live post hides it from customers
rather than deleting it.

## Running the worker locally

```
celery -A gulbot.worker.app worker --pool=solo --loglevel=info
celery -A gulbot.worker.app beat --loglevel=info
```

`--pool=solo` because prefork does not work on Windows (see above). Beat runs
the send tick every minute and the materializer nightly at 03:00 Tashkent.

A solo pool in ONE process cannot race with itself, which is why
`tests/test_concurrency.py` starts two separate worker PROCESSES and asserts
their PIDs differ.

**The worker is not optional once the channel indexer is live.** Beat's two jobs
are periodic, but CP8 adds an event-driven one: `gulbot.finalize_album`, sent by
the bot process a few seconds after an album arrives. With no worker running, an
album's row is still created and merged correctly -- nothing is lost -- but it
stays provisional (`finalized_at IS NULL`), so it has no price, no tags, and
CP9's search will not find it. Single photo posts do not depend on the worker:
they are finalized inline by the handler.

If a finalize task CRASHES, the album's Redis lock is held for 300s and the row
stays provisional; a later photo or an edit settles it, nothing else will. See
"A stale-provisional sweep" in docs/CHECKPOINTS.md.

**Promote the bot to channel admin BEFORE posting anything you expect indexed.**
A post made earlier generates no update, Telegram never backfills, and the Bot
API cannot read channel history, so it is gone. To check what Telegram is
actually delivering, stop `bot.run` and long-poll `getUpdates` yourself -- two
concurrent pollers get a 409.
