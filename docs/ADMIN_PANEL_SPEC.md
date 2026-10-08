# Gulbot — Platform Admin Panel Spec

*Version: 2026-10-05 · Audience: developer · Language: English*

## 1. Goals and scope

The platform owner (single role for MVP: **Owner**) needs ONE web panel to see and control every shop on the platform. Each shop has its own Telegram bot (own token), its own channel, and its own admin group, all built on the same codebase/scheme.

**Goals**
1. Know at a glance which shops are healthy, broken, or idle.
2. See whether the product works for each shop (reminders → orders).
3. Be alerted to platform-wide failures without reading logs.
4. Moderate public pages (invitation / Ha-Yo'q / Uzrnoma) and guest wishes.
5. Take a small set of safe actions (pause/resume, mark paid, gift-rule toggle).

**Non-goals (MVP):** shop-owner self-service login, automated billing, editing customer data, impersonating shops.

**What the current codebase already provides** (checked read-only against `src/gulbot/models`, `sending/health.py`, `docs/DEPLOY.md`)
- `shops`: `name`, `channel_id`, `group_chat_id`, `owner_telegram_ids`, `bot_token_encrypted` (Fernet, key only in env), `bot_telegram_id`, `uses_process_bot_token`, `timezone`, `owner_phone`, order-ping offsets (default 3 h and 1 h), `reminder_offsets` (default -7/-1/0 days), `daily_order_cap`, peak thresholds.
- `scheduled_notifications` (reminders) with states `pending / sent / failed / expired / cancelled / dead_letter`; `order_reminders` (pings to the shop group) with their own states; `MAX_SEND_ATTEMPTS = 5`, then `dead_letter`.
- `orders` with confirm/reject (reject carries a reason); `customers` with phone and `phone_verified`.
- `share_pages` (`kind`, `template`, `lang`, `token`, `view_count`, `cta_click_count`, `expires_at`, `deleted_at`, `answered_at`), `share_page_rsvps` (with `guest_name`), `share_page_photos` (**stored as bytes in Postgres**), `share_page_referrals` (shop, page, customer — a customer who arrived via a page's "order flowers" button).
- Per-shop health logic (`read_health`, `read_daily_totals`): overdue reminders/pings (> 15 min), parked (dead-letter) counts; alerts go to the shop's own group with a 1 h Redis cooldown. A scheduled `scrub_expired_pages` job (03:30) exists.
- Catalog: `products` indexed from channel posts (with `finalized_at`; `created_at`/`updated_at` via the mixin).

**Gaps — what the panel needs that does NOT exist yet** (this is the real work for the developer)
1. **No shop lifecycle status.** There is no `onboarding / active / paused` field. Add `shops.status` and make **every send path and the bot's order handler honour `paused`** (reminder tick, order pings, new orders, page CTA). A panel-only flag that the workers ignore is worse than none.
2. **No subscription fields.** Add `subscription_status`, `paid_until`, plus a small `subscription_payments` ledger (date, amount UZS, method, note, admin).
3. **No bot-health snapshot.** Nothing stores "token valid / channel connected / group connected". Add a scheduled job writing `shop_health_snapshots` (calls `getMe`, `getChatMember` for the bot in channel and group). Do not call Telegram live from the page request.
4. **No "last indexed post" column.** Derive as `max(products.created_at, updated_at)` per shop, or store `shops.last_indexed_at`.
5. **No order source.** `orders` has no `source`. Either add `orders.source` / `source_page_id` (set when the order flow starts from a page's deep link), or derive attribution: an order counts as "from a page" if its customer has a `share_page_referrals` row for that shop before `orders.created_at` (and within N days); "from a reminder" if a `scheduled_notifications` row was `sent` to that customer within N days before the order. Adding a column is far more reliable; derivation is an acceptable MVP stopgap and must be labelled "approximate" on screen.
6. **No page hide flag.** `deleted_at` already means "deleted/expired" — add a separate `share_pages.hidden_at / hidden_by / hidden_reason` so a moderation hide is reversible and distinct from deletion. The public renderer must check it on every request.
7. **No guest wishes.** `share_page_rsvps` has `guest_name` only. The invitation "guest wishes" feature has no table yet; moderation of wishes (S6) is blocked until it exists. Add `share_page_wishes` with `hidden_at` from the start.
8. **No per-page-type "Uzrnoma" split visible in the panel** beyond `share_pages.kind` — confirm the enum covers Ha/Yo'q, Uzrnoma, Taklifnoma.
9. **No dead-man's switch** (documented gap, `docs/DEPLOY.md` §5). The existing health check is itself a Celery beat task alerting via Telegram, so if beat or the worker dies nothing alerts. The panel's "stalled ticks" alert must therefore be computed by something **independent of the worker** (the web process comparing `job_runs.finished_at` to now on each page load, plus an external uptime ping on a `/healthz`-style endpoint that checks the freshness of those heartbeats).
10. **Dead-letter review surface does not exist** (listed under "Deliberately not built" in `docs/CHECKPOINTS.md`); S5 is the first one.
11. **Pages hold secrets in their URL.** The page server deliberately writes **no access log** and every page's address is its secret (`token`). The panel must **never display or log full page URLs/tokens** by default — show an internal page id; an "open public link" action is a deliberate, audited click.

## 2. Privacy and audit principles (apply to every screen)

1. **Counts by default.** Show aggregates; drill-down to individual customers is a deliberate action.
2. **Mask phone numbers** everywhere: `+998 90 *** ** 12` (first 6 and last 2 digits at most). Names are shown as first name + initial. No full unmask in MVP; if later added, require a typed reason and log it.
3. **Never display secrets.** Bot tokens are never rendered, not even masked beyond "valid / invalid / last checked". No token in logs, URLs, or API responses to the browser.
4. **Audit log for every admin action** (§8): who, when, which shop/object, action, before → after, optional reason, IP. Append-only; no UI to edit or delete entries.
5. **Read access to customer-level data is also logged** (drill-down views), at least in later phases.
6. Authentication: single owner account with strong password + TOTP 2FA, short session, HTTPS only, rate-limited login. Admin panel served on its own path/subdomain, separate from public pages.

## 3. Navigation

`Overview · Shops · Alerts · Pages · Actions/Audit log · Settings`

## 4. Screens

### S1. Overview dashboard — **MVP**
Landing page. One-glance health.
- Tiles: shops by status (onboarding / active / paused), shops with problems (count, red), open alerts (count), orders today / last 7 days, reminders sent today / failed today.
- "Needs attention" list: top 10 shops by problem severity (token invalid, bot silent, no admin group, subscription overdue) with link to the shop.
- Sparkline: orders per day, last 30 days (platform-wide).

### S2. Shops list — **MVP**
Table, one row per shop; sortable, filterable by status/health/subscription; text search by shop name.

| Column | Meaning |
|---|---|
| Shop name, bot @username | Link to S3 |
| Status | `onboarding` / `active` / `paused` |
| Bot health | green / yellow / red from the last health check (see below) |
| Token valid | yes / no + last checked time (Telegram `getMe` result; never show token) |
| Channel connected | yes / no (bot is admin in channel and can read posts) |
| Admin group connected | yes / no (bot is member and can send) |
| Last indexed post | timestamp of newest indexed channel post; highlight if > N days (configurable, default 14) |
| Bouquets indexed | count |
| Subscription | `trial` / `paid` / `overdue` / `none`, paid-until date (manual for now) |
| Customers / Orders (30d) | quick counts |
| Created | date |

**Bot health definition** (proposal): red = token invalid, or bot blocked/removed from admin group, or webhook/polling failing; yellow = no successful outbound send for 24h while reminders were due, or last indexed post stale; green otherwise. Health check runs on a schedule (e.g. every 10 min) and stores the result — the panel must not call Telegram live on page load.

Row actions: Pause/Resume, Mark paid (see S7). **Add shop** form for onboarding is **later** (MVP: shops created via script/DB; panel only lists them).

### S3. Shop detail — **MVP**
Header: name, status badge, health badge, subscription badge, action buttons (Pause/Resume, Mark paid, gift-rule toggle).

Tabs:
1. **Overview** — connection checklist (token valid, channel connected, admin group connected, last indexed post, last reminder run, last order), plain-language reason if red.
2. **Metrics** (S4).
3. **Config** (read-only in MVP) — channel/group ids, language, timezone, reminder lead times, gift rule state. Edit is **later**.
4. **Activity** — this shop's audit entries and recent alerts.

### S4. Per-shop metrics — **MVP** (basic) / **Later** (charts, cohorts)
Date range picker (7d / 30d / 90d / custom); all numbers have a "vs previous period" delta.
- **Customers:** total, new in period, active (interacted in period). Count only.
- **Saved dates:** total, new in period, upcoming in next 30 days.
- **Reminders:** scheduled, sent, failed, dead-lettered; failure rate; breakdown of failure reasons (user blocked bot, chat not found, rate limit, other).
- **Orders:** placed, confirmed, rejected, pending, expired/no response; confirm rate; median time-to-first-response by shop staff; top rejection reasons (grouped).
- **Order source attribution** (important for the sales story): orders from **reminder**, from **invitation page**, from **Ha/Yo'q page**, from **Uzrnoma page**, from **direct/organic** (customer opened the bot himself). Needs a `source` + `source_ref` stored on the order at creation (deep-link payload from the page's "order flowers" button, or last reminder id within a time window).
- **Conversion funnel (later):** reminder sent → opened → bouquet viewed → order placed → confirmed.
- **Revenue (later):** sum of confirmed orders where price was known; clearly labelled "unpriced orders excluded".

### S5. Platform alerts — **MVP**
Chronological list + counts per type. Each alert: type, severity, shop (or "platform"), first seen, last seen, occurrences, status (`open` / `acknowledged` / `resolved`), link to the related object.

Alert types:
1. **Dead-lettered sends** — messages that exhausted retries (reminders, order notifications, admin-group messages). Show count per shop and reason; action: view list, "retry" (**later**), "acknowledge".
2. **Stalled ticks** — beat/worker tick (reminder scan, channel indexing, daily summary) not completed within expected interval ×2. Show last successful run per job; platform-wide, not per shop. Also show Celery queue depth and oldest queued task age.
3. **Shop bot stopped working** — token invalid/revoked, bot removed from channel or admin group, repeated 401/403/400 "chat not found" from Telegram, no admin-group message delivered while orders exist.
4. **Orders unanswered** — order pending in admin group beyond threshold (e.g. 30 min during working hours) — useful for owner to nudge the shop.
5. **Indexing stale** — no new indexed posts for N days on an active shop (**later**).
6. **Subscription overdue** (**later**, manual date compare).
7. **Rate-limit pressure / error spikes** (**later**).

Alerts are generated by a periodic job writing to an `alerts` table (dedupe by type+shop+key). Optional: push to the owner's own Telegram chat via a platform ops bot for red alerts (**later**, but cheap and very high value).

### S6. Pages: invitations, Ha/Yo'q, Uzrnoma — **MVP** (counts + hide) / **Later** (everything else)
Pages are public and user-generated, so moderation is required from launch.

**Summary strip:** total pages by type (Taklifnoma / Ha-Yo'q / Uzrnoma), created in period, total views, unique views, RSVPs, guest wishes, "order flowers" button clicks, orders attributed. Filter by shop and type.

**Pages table:** type, shop (branding owner), created, creator (masked, customer id link), design (1–20 for Taklifnoma), views, RSVPs, wishes count, status (`visible` / `hidden`), reports count (if a "report" link exists on public pages — recommended, **later**).

**Page detail:**
- Preview (rendered read-only, in sandboxed iframe or screenshot), public URL, text fields as submitted.
- Stats: views by day, button clicks, RSVP yes/no counts.
- **Guest wishes list** (Taklifnoma): wish text, guest name as entered, time, status; **Hide** per wish.
- **Photo gallery items:** thumbnails, **Hide** per photo.
- **Actions:** **Hide page** (public URL then shows a neutral "page unavailable" screen), **Unhide**, **Hide wish/photo**. Each requires a reason (dropdown + free text) and is audit-logged. Hidden ≠ deleted; permanent deletion is **later** and needs a second confirmation.
- Keyword flag (**later**): auto-flag wishes/pages containing configured abusive words for review queue.

**Views and clicks already exist** as `share_pages.view_count` and `cta_click_count` (running totals). MVP shows those. Per-day views, unique views and bot filtering (ignore Telegram link-preview crawlers) are **later** and would need an event table with hashed visitor ids only, given that the page server intentionally keeps no access log.

**Photos live in Postgres** (`share_page_photos.data`). Serve thumbnails to the panel through an authenticated endpoint, never via a public URL, and mind the size when budgeting backups (see `04-infratuzilma-rejasi.md`).

**Expiry:** pages have `expires_at` and a nightly scrub job. The list needs an "expired / scrubbed" state, and moderation must still work on pages that are live but about to expire; an already-scrubbed page has no content to moderate.

### S7. Actions — **MVP**
Available from S2 row menu and S3 header. Each opens a confirmation dialog stating the effect; each is audit-logged.

1. **Pause shop's bot** — sets shop status `paused`. Effects to define precisely: stop sending reminders; stop accepting new orders; bot replies with a polite "temporarily unavailable" message; public pages for the shop stay up but hide/disable the "order flowers" button (or show shop-unavailable). Already-pending orders remain visible in the admin group. Optional reason field.
2. **Resume shop's bot** — reverse; scheduled reminders that were missed while paused must **not** all fire at once: skip missed ones older than a configurable window (default: 24 h) and log how many were skipped.
3. **Mark subscription paid** — inputs: paid-until date (default +30 days from today or from previous paid-until), amount in UZS, payment method (cash / card transfer / other), note. Shows previous and new state. Subscription is **manual** for now: no auto-pause on expiry in MVP; "overdue" is just a badge. Later: optional auto-pause after grace period.
4. **Premium-unlock-after-order gift rule: on/off per shop** — a per-shop boolean (`gift_premium_after_order`). When on, a customer who has an order **confirmed** by the shop gets one premium invitation design unlocked as a gift. The panel shows the state, the count of unlocks granted in the period, and lets the owner flip it. Define: toggling affects future orders only; already-granted unlocks stay.
5. **Edit shop status manually** (e.g. onboarding → active) — **MVP** minimal: a status dropdown with confirmation.
6. **Re-run health check now** for a shop — **MVP** (rate-limited, 1/min/shop).
7. Later: re-issue/rotate token (secure input form), retry dead letters, force re-index channel, send test message to admin group, edit config, delete shop (soft delete).

### S8. Audit log — **MVP**
Table of every admin action: timestamp, admin user, action type, target (shop / page / wish), before → after (JSON diff, human-readable), reason, IP. Filter by shop, action type, date. Export CSV (**later**). No edit/delete in UI, DB role used by app has no UPDATE/DELETE on this table.

### S9. Settings — **Later**
Alert thresholds (indexing stale days, unanswered-order minutes), health-check interval, owner Telegram chat for alerts, admin user management and additional roles (e.g. read-only "Support"), data-retention periods.

## 5. MVP vs Later summary

| Screen | Phase | MVP scope |
|---|---|---|
| S1 Overview | **MVP** | Status tiles, needs-attention list |
| S2 Shops list | **MVP** | All columns; no "add shop" form |
| S3 Shop detail | **MVP** | Overview + Activity tabs; Config read-only |
| S4 Per-shop metrics | **MVP** basic / **Later** | Counts + order source attribution in MVP; funnel, revenue, charts later |
| S5 Alerts | **MVP** | Types 1–4; acknowledge/resolve; owner Telegram push later |
| S6 Pages & moderation | **MVP** (counts, hide page/wish) | Gallery moderation, auto-flagging, report links, hard delete later |
| S7 Actions | **MVP** | Pause/resume, mark paid, gift-rule toggle, status edit, health re-check |
| S8 Audit log | **MVP** | Full |
| S9 Settings | **Later** | — |
| Shop self-service panel, billing automation | **Later** | — |

## 6. Data and implementation notes

- **Pre-aggregate.** Compute metrics via a periodic job into a `shop_daily_stats` table (shop_id, date, counts…); the panel reads aggregates, never scans raw tables on page load. Keep raw rows for drill-down.
- **Health snapshots.** `shop_health` (shop_id, checked_at, token_valid, channel_ok, group_ok, details JSON) written by a Celery beat job; panel shows latest.
- **Job heartbeat.** Each periodic job writes `job_runs` (name, started, finished, status); stalled-tick alert is computed from this.
- **Order attribution.** Add `orders.source` (`reminder` / `invitation` / `ha_yoq` / `uzrnoma` / `direct`) and `source_ref`; set from the deep-link `start` payload.
- **Page events.** `page_views`, `page_clicks` (hashed visitor id, page id, day), `page_wishes`, `rsvps`; plus `hidden_at`, `hidden_by`, `hidden_reason` on pages/wishes/photos.
- **Moderation is soft.** Public renderer must check `hidden_at` on every request (and cache must be purged on hide).
- **Pause flag enforcement** must live in the bot/Celery code paths (reminder sender, order handler), not only in the panel.
- **Stack suggestion** (not prescriptive): server-rendered admin (FastAPI/Django admin-style) behind the same Caddy, separate hostname `admin.<domain>`, or restricted by IP/VPN; no JS framework needed for MVP.
- **Timezone:** show all times in Asia/Tashkent (UTC+5), store UTC.

## 7. Open questions for the product owner

1. What exactly counts as "bot health" red vs yellow — accept the proposal in S2?
2. When a shop is paused, should public pages keep working, with the "order flowers" button disabled?
3. Should the gift rule unlock **one** premium design per customer or per order?
4. Do you want a "report this page" link on public pages from day one?
5. Retention: how long to keep page views, wishes, and audit logs?
