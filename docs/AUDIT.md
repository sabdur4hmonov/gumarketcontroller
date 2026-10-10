# Pre-deployment audit, September 2026

Six passes, plus a sweep of every callback, run before the 1 October 2026
pilot. The rules were:

- **Evidence, not argument.** Every finding needed a failing test or a live
  reproduction.
- **Every fix mutation-proved.** A mutation counted as caught only when a test
  failed on an assertion.
- **The full check gate** (lint, typecheck, shadow, tests) before each commit.

Commits run from `ca99d4c` to the one that adds this file. Each commit message
holds that pass's detail.

**Read section 3 before the pilot.** It lists what was found and deliberately
not fixed, so none of it gets lost.

## 1. The numbers

| | Count |
|---|---|
| Defects found | **21** |
| Fixed | **20** |
| Found and deliberately not fixed | **1** defect, plus **4** accepted limitations (section 3) |
| Defects the audit's own fixes introduced, caught later in the audit | **3** (all fixed; counted in the 21) |
| Areas checked and found clean, each with a test or live evidence | **19** (section 4) |

## 2. Every fix, in one place

### Pass 1: known blind-spot families (`ca99d4c`, `2da2f01`)

1. **Order confirm/reject claim was not durable.** A card edit that failed after
   the customer was messaged rolled back the status and the claim, so a second
   tap sent a second "your order is confirmed". Fixed with three commits, one per
   phase: decision, then claim, then resolution.
2. **A failed reminder was lost silently.** A FAILED row was never selected
   again, never retried, never dead-lettered, and never counted by the health
   check. Fixed:
   - `SENDABLE_STATES = (PENDING, FAILED)`;
   - a generic failure defers by `RETRY_BACKOFF` and releases its claim;
   - `MAX_SEND_ATTEMPTS` now applies to every failure;
   - the health check counts FAILED reminders.

### Pass 2: races (`2c0f36c`)

3. **The daily order cap was never enforced at submit.** Only the date picker
   checked it, several questions earlier. Fixed with `claim_delivery_slot`: a
   transaction-scoped advisory lock on (shop, day), then the count. Proven with
   two real dispatchers on two engines.
4. **The order button outlived a withdrawn bouquet.** It now goes through
   `load_product` and its `sellable()` predicate.

### Pass 3: data integrity under churn (`c3abfa0`)

5. **Removing a person or date did not stop a reminder already due.** It was
   pruned only at 03:00. `deactivate_recipient` and `deactivate_occasion` now
   discard pending reminders immediately.
6. **`block_customer` cancelled only PENDING rows.** *Introduced by fix 2.* It
   now cancels every sendable state.
7. **`RECONCILABLE_STATES` was still PENDING-only.** *Introduced by fix 2.* It
   is now defined as `SENDABLE_STATES`.

### Pass 4: hostile input (`d74b6d1`)

8. **The per-shop-per-day lock was held across Telegram calls,** for up to 60 s
   each. It is now released before any Telegram call.
9. **Crafted date and hour callbacks booked past dates, dates past the booking
   horizon, and closed hours.** Both handlers now re-derive the valid set from
   the same functions that built the keyboard.
10. **A rejection stamp could push a photo caption over Telegram's 1024 visible
    characters.** The live buttons stayed on the card. When the stamp doesn't
    fit, the buttons are now removed and the outcome is posted as a reply.

### Callback sweep, all 29 `CallbackData` factories (`e4b0296`)

11. **`OrderStartCB.recipient_id` could attach another customer's person to an
    order.** It is now looked up through the customer-scoped `get_recipient`.

### Pass 5: operational failure modes (`9b96c35` measured, `1cddadf` fixed)

12. **A Telegram outage made one tick last up to 100 minutes.** Fixed three ways:
    - the request timeout is 15 s (was 60);
    - a circuit breaker ends a tick after 3 consecutive network failures;
    - unattempted rows are handed back untouched.

    Proven against a real silent TCP server.
13. **A hung statement had no bound.** `statement_timeout` is now 30 s.
    `idle_in_transaction_session_timeout` is deliberately left unset.
14. **Tasks had no time limits and ticks no expiry.** Every task now has soft
    and hard limits, and the periodic ticks expire. Proven live on Linux
    prefork, and live against a real broker.
15. **Container logs grew without bound.** Postgres and Redis now rotate at
    10 MB × 3 files. This needs a container recreate: `docs/DEPLOY.md` step 2.
16. **mypy was failing at HEAD.** *Introduced by the pass 3 commit;* those
    passes did not run the typecheck. Fixed, and every commit since went
    through the full gate.

### Pass 6: configuration and secrets (`4e43080`, and the final commit)

17. **pytest printed the real bot token.** It appears in `Settings`' repr on any
    failing assertion that touches a `Settings` object. `bot_token` and
    `postgres_password` are now `SecretStr`.
18. **`.gitignore` covered only `.env` exactly.** It now ignores `.env.*`,
    except `!.env.example`.
19. **Production could silently run on dev config.** A forgotten variable fell
    back to a stale `.env`, then to dev defaults. A production process now
    refuses to start (`ProductionConfigError`) unless:
    - `BOT_TOKEN`, `POSTGRES_HOST`, `POSTGRES_DB` and `POSTGRES_PASSWORD` are
      real, non-empty environment variables;
    - the password is not the dev default.

    The check is in `get_settings()`, which every process goes through. Proven
    with real processes: the bot, the Celery worker, beat, alembic and the seed
    CLI all refuse on dev-shaped config, and a production-shaped config gets
    past the guard. **The single most important fix in the audit.**
20. **An HTML error page from Telegram or a proxy crashed the tick.** The page
    raised `ClientDecodeError`, which bypassed the circuit breaker and left
    claims stuck for 15 minutes. It is now counted as unreachable.

Mutations caught, per fix:

| Fix | Caught |
|---|---|
| Pass 1 | 3/3 and 5/5 |
| Pass 2 | 5/5 |
| Pass 3 | 6/6 |
| Pass 4 | 6/6 |
| Callback sweep | 5/5 |
| Pass 5 | 15/15 |
| Pass 6 secrets | 4/4 |
| Guard and decode | 14/14 (every check removed on its own, plus the `get_settings` call) |

## 3. Found and deliberately NOT fixed

Nothing here is forgotten. Each is a decision, with where it is recorded.

| # | What | Why not now | Needed before | Recorded in |
|---|---|---|---|---|
| A | **Order-card permission is by chat, not by person.** Any member of the shop's group can confirm or reject any order. **Closed at CP19:** a per-shop staff list, managed with `/staff` on the platform bot; a shop without one keeps the old rule. | Correct while the group is exactly the staff. An allowlist needs an owner-facing way to manage it. | The day a shop adds a courier, supplier or relative to the group | `CHECKPOINTS.md`, *What CP19 guarantees* |
| B | **No external dead-man's switch for beat** (the one defect not fixed). If beat dies, nothing says so. The health check is itself a beat task, and it alerts through Telegram. | A deployment decision: which monitor, what interval, who gets paged. | **A real production launch beyond the pilot.** Not the pilot itself: `DEPLOY.md` step 5 gives a manual daily check. | `CHECKPOINTS.md`; `DEPLOY.md` step 5 |
| C | **The health check shares the worker's queue** with the ticks. | Real infrastructure for a benefit that bites only at volume. The breaker and time limits already bound what it waits behind. | Volume beyond the pilot; revisit with B | `CHECKPOINTS.md`, *Deliberately not built* |
| D | **One late duplicate reminder** when the database is lost after Telegram accepted a message. | CP6's deliberate trade: to the database, a lost connection looks exactly like a dead worker, and a dead worker must never drop a reminder silently. | Not planned | `test_audit_db_loss.py`, CP6 in `CHECKPOINTS.md` |
| E | **The production guard is armed only by `ENVIRONMENT=production`.** A process that never sets it runs as "local", on dev defaults, by design. | The code has no other signal that it is in production. | **The pilot deploy.** Operational: `DEPLOY.md` step 0 has each process confirm it reads `production`, and the bot logs its environment at startup. | `DEPLOY.md` step 0 |

Pre-existing deferrals outside the audit's scope are still in `CHECKPOINTS.md`:
the stale-provisional album sweep, the dead-letter review surface, the shop
settings admin flow, and homoglyph detection.

## 4. Checked and found clean

1. No module-level loop-bound clients. AST sweep, mutation-proved against five
   historical shapes. *(pass 1)*
2. No edited stamped migrations: all 15 have exactly one commit each.
   *(pass 1)*
3. All 15 migrations apply, downgrade and re-apply on a fresh database.
   *(pass 1)*
4. Two concurrent rejections store one reason. *(pass 2)*
5. Keyset pagination survives deletion of the cursor row and of rows ahead of
   it. *(pass 2)*
6. Order snapshots are independent under concurrency and a later reprice.
   *(pass 2)*
7. Album debounce crossed with a hashtag-stripping edit, in both orderings.
   *(pass 2)*
8. Reminders and order outcomes share `message_log` without suppressing each
   other. *(pass 2)*
9. A withdrawn product, soft or hard deleted, leaves orders and shop cards
   intact. *(pass 3)*
10. A customer blocking the bot does not silence the shop's order pings.
    *(pass 3)*
11. A rename after materialisation shows in the reminder. *(pass 3)*
12. No SQL built by string formatting. *(pass 4)*
13. Every customer-typed field on the group card is escaped. *(pass 4)*
14. Typed phones are normalised within the column size. *(pass 4)*
15. A customer cannot drive an order from their own DM, because of the chat
    check. *(pass 4)*
16. The other 28 callback factories are each safe for a stated,
    mutation-proved reason. *(callback sweep)*
17. Database loss after a send loses nothing and resends nothing early.
    *(pass 5)*
18. Git history has no token-shaped string in any of 47 commits, the reflog,
    the stash or unreachable objects, and `.env` was never committed.
    *(pass 6)*
19. At DEBUG, the real token, a unique password marker and the DSN appear in
    none of 552 log lines and 15 tracebacks, across 16 failure paths.
    *(pass 6)*

## 5. Standing rules this audit added to CONTRIBUTING

- A fix that changes what a state **value** means triggers a grep for every
  place that value is filtered, compared or counted. Fixes 6 and 7 are why.
- Verify the live database is at migration head yourself; don't trust a
  report of "applied".
- Isolated reruns don't rule out a concurrency bug; loaded full-suite runs do.
- A mutation counts only when a test **fails on an assertion**. An error in
  setup proves nothing: pass 6's first sweep reported a false catch that way.
- Run the whole gate (lint, typecheck, shadow, tests) before every commit. Fix
  16 is why.
