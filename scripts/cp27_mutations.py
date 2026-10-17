"""CP27.1 mutation proof: break each new guard on purpose; its test must fail.

Each mutant changes one anchor in one file, runs the named tests, and restores
every byte in `finally`. "Caught" means pytest exited 1 on an assertion (or a
pytest.raises that did not raise), not on a crash. Results go to
docs/CP27_MUTATIONS.json. Needs its own test database (POSTGRES_TEST_DB set to
something other than gulbot_test); never runs the full gate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "CP27_MUTATIONS.json"
WEB = "tests/test_studio_web.py::"
AUTH = "tests/test_studio_auth.py::"
VENUES = "tests/test_share_page_venues.py::"
PICKER = "tests/test_studio_picker.py::"
KINDS = "tests/test_studio_kinds.py::"
PAGES = "tests/test_studio_pages.py::"
MINI = "tests/test_studio_webapp.py::"
WEBAPP = "src/gulbot/services/studio_webapp.py"
SLIM = "tests/test_share_pages_slim.py::"
SLIM_ROUTER = "src/gulbot/bot/routers/share_pages_slim.py"
TOKENS = "tests/test_studio_tokens.py::"
STUDIO_WEB = "src/gulbot/web/studio.py"
STUDIO = "src/gulbot/services/studio.py"
SHARE = "src/gulbot/services/share_pages.py"


@dataclass(frozen=True)
class Mutant:
    name: str
    file: str
    old: str
    new: str
    test: str


class MutationResult(TypedDict):
    guard: str
    file: str
    test: str
    assertion_caught: bool
    exit_code: int


def mutants() -> list[Mutant]:
    return [
        Mutant(
            "every /studio route behind the gate",
            "src/gulbot/web/app.py",
            "shop_panel.shop_gate, studio.studio_gate]",
            "shop_panel.shop_gate]",
            WEB + "test_every_studio_route_refuses_a_request_without_a_session",
        ),
        Mutant(
            "CSRF on every POST",
            STUDIO,
            "return submitted is not None and hmac.compare_digest(creator.csrf, submitted)",
            "return True",
            WEB + "test_every_post_needs_the_sessions_csrf_token",
        ),
        Mutant(
            "a GET never spends the link",
            STUDIO_WEB,
            '    return _html(render.render("studio/enter.html", {"token": token}))',
            "    async with request.app[KEY_STUDIO_SESSIONS]() as session:\n"
            "        await studio.consume_link(session, token)\n"
            "        await session.commit()\n"
            '    return _html(render.render("studio/enter.html", {"token": token}))',
            WEB + "test_opening_the_link_does_not_spend_it",
        ),
        Mutant(
            "single use (compare-and-swap)",
            STUDIO,
            "                StudioLink.used_at.is_(None),\n",
            "",
            AUTH + "test_a_link_works_once_and_opens_a_session_for_its_customer",
        ),
        Mutant(
            "link TTL",
            STUDIO,
            "                StudioLink.expires_at > now,\n",
            "",
            AUTH + "test_a_link_expires_after_fifteen_minutes",
        ),
        Mutant(
            "hash-only storage",
            STUDIO,
            "            token_hash=hash_token(raw),\n            bot_username=bot_username,",
            "            token_hash=raw[:64],\n            bot_username=bot_username,",
            AUTH + "test_a_link_is_stored_as_its_hash_only",
        ),
        Mutant(
            "link rate limit",
            STUDIO,
            "    if int(recent or 0) >= LINK_RATE_LIMIT:",
            "    if False:",
            AUTH + "test_links_are_rate_limited_per_customer",
        ),
        Mutant(
            "entitlement re-checked on every request",
            STUDIO,
            "    shop_id, customer_id = int(row.shop_id), int(row.customer_id)\n"
            "    if not await entitled(session, shop_id=shop_id, customer_id=customer_id):\n"
            "        return None\n",
            "    shop_id, customer_id = int(row.shop_id), int(row.customer_id)\n",
            WEB + "test_pausing_the_shop_closes_the_studio_on_the_next_request",
        ),
        Mutant(
            "entitlement: a paused shop",
            STUDIO,
            "            Shop.status != ShopStatus.PAUSED.value,\n",
            "",
            AUTH + "test_entitlement_is_rechecked_at_spending_and_on_every_request",
        ),
        Mutant(
            "revocation at logout",
            STUDIO,
            "                StudioSession.revoked_at.is_(None),\n",
            "",
            WEB + "test_logout_ends_the_session",
        ),
        Mutant(
            "cookie Secure on https",
            STUDIO_WEB,
            "        secure=request.app[KEY_SETTINGS].secure,",
            "        secure=False,",
            WEB + "test_the_cookie_is_httponly_lax_scoped_and_secure_on_https",
        ),
        Mutant(
            "studio login rate limit",
            STUDIO_WEB,
            '    limit(request, "studio_login")\n    token = request.match_info["token"]',
            '    token = request.match_info["token"]',
            WEB + "test_the_login_is_rate_limited",
        ),
        Mutant(
            "a creator sees only their own pages",
            STUDIO_WEB,
            "        page = await share_pages.get_own_page(\n"
            "            session, shop_id=creator.shop_id, customer_id=creator.customer_id,"
            " page_id=int(raw)\n        )",
            "        page = await session.get(SharePage, int(raw))",
            WEB + "test_a_creator_sees_only_their_own_pages",
        ),
        Mutant(
            "premium wall on create",
            SHARE,
            "        await premium.require(session, shop_id=shop_id, customer_id=customer_id)\n"
            "    checked = await checked_draft(",
            "        pass\n    checked = await checked_draft(",
            WEB + "test_premium_designs_are_locked_with_the_cp18_wording",
        ),
        Mutant(
            "the preview saves nothing",
            STUDIO_WEB,
            "            await savepoint.rollback()\n            await session.rollback()",
            "            await savepoint.commit()\n            await session.commit()",
            WEB + "test_the_preview_shows_the_creators_data_and_saves_nothing",
        ),
        Mutant(
            "studio CSP (form-action self, studio only)",
            "src/gulbot/web/app.py",
            "        or studio.is_studio_path(request.path)\n",
            "",
            WEB + "test_studio_pages_may_post_to_themselves_and_public_pages_may_not",
        ),
        Mutant(
            "map links: allowed hosts only",
            SHARE,
            "        or host not in MAP_HOSTS\n",
            "",
            VENUES + "test_anything_else_is_refused",
        ),
        Mutant(
            "map links: https only",
            SHARE,
            '        parts.scheme.lower() != "https"\n        or host',
            "        host",
            VENUES + "test_anything_else_is_refused",
        ),
        Mutant(
            "places scrubbed with a deleted page",
            SHARE,
            "    await session.execute(delete(SharePageVenue)"
            ".where(SharePageVenue.page_id == page_id))\n",
            "",
            VENUES + "test_places_go_with_the_page_on_delete_and_on_expiry",
        ),
        Mutant(
            "at most five places",
            SHARE,
            "    if len(venues) > VENUES_MAX:",
            "    if False:",
            VENUES + "test_places_the_form_could_not_produce_are_refused",
        ),
        Mutant(
            "the public page lists the places",
            "src/gulbot/web/app.py",
            "                render.venue_lines("
            "await share_pages.venues_of(session, page_id=p.id), p.lang)",
            "                []",
            VENUES + "test_the_public_page_lists_the_places",
        ),
        Mutant(
            "the bot sends the studio link",
            "src/gulbot/bot/routers/share_pages.py",
            '    if callback_data.action == "studio":\n'
            "        await _send_studio_link(target, session, customer, lang, callback.bot)\n"
            "        return\n",
            "",
            "tests/test_studio_bot.py::test_the_button_sends_a_one_time_link_for_this_customer",
        ),
        # --- CP27.1b: the design picker on its own screen ---------------------------
        Mutant(
            "1b: a locked design cannot be chosen",
            STUDIO_WEB,
            '                if card is None or card["locked"]:',
            "                if card is None:",
            PICKER + "test_a_locked_design_can_be_looked_at_but_not_chosen",
        ),
        Mutant(
            "1b: an unknown design cannot be chosen",
            STUDIO_WEB,
            '                if card is None or card["locked"]:',
            '                if card is not None and card["locked"]:',
            PICKER + "test_an_unknown_design_or_filter_is_refused",
        ),
        Mutant(
            "1b: the category filter",
            STUDIO_WEB,
            '        if (cat == "all" or cat in studio_designs.DESIGN_CATEGORIES[d["key"]])',
            "        if True",
            PICKER + "test_the_picker_keeps_what_was_typed_and_filters",
        ),
        Mutant(
            "1b: the free/premium filter",
            STUDIO_WEB,
            '        and (tier == "all" or (tier == "premium") == d["premium"])',
            "        and True",
            PICKER + "test_the_picker_keeps_what_was_typed_and_filters",
        ),
        Mutant(
            "1b: the picker carries what was typed",
            "src/gulbot/web/templates/studio/picker.html",
            "  {{ hidden_state(v.state, v.csrf) }}\n",
            '  <input type="hidden" name="csrf" value="{{ v.csrf }}">\n',
            PICKER + "test_the_picker_keeps_what_was_typed_and_filters",
        ),
        Mutant(
            "1b: every design has a category",
            "src/gulbot/web/studio_designs.py",
            '    "moviy": frozenset({_TOY, _BOSH}),\n',
            "",
            PICKER + "test_every_design_has_a_category",
        ),
        Mutant(
            "1b: the form carries one design card",
            "src/gulbot/web/templates/studio/form.html",
            "    {%- set d = v.chosen %}",
            "    {%- set d = v.chosen %}{% for x in ['atlas', 'oltin'] %}"
            '<i data-design="{{ x }}"></i>{% endfor %}',
            PICKER + "test_the_form_shows_one_chosen_design_not_forty",
        ),
        # --- CP27.2: Ha/Yo'q, Uzrnoma, photos, music -----------------------------------
        Mutant(
            "2: music is premium on create",
            SHARE,
            "    if premium.is_premium_template(draft.template) or draft.music is not None:",
            "    if premium.is_premium_template(draft.template):",
            KINDS + "test_music_is_premium_and_nothing_is_made_without_the_gift",
        ),
        Mutant(
            "2: only our own tracks (shared rules)",
            SHARE,
            "    if draft.music is not None and draft.music not in MUSIC_TRACKS:",
            "    if False:",
            KINDS + "test_the_shared_rules_refuse_a_track_that_is_not_ours",
        ),
        Mutant(
            "2: upload size from Content-Length, before reading",
            STUDIO_WEB,
            "        if length is None or length > UPLOAD_MAX_BYTES:",
            "        if False:",
            KINDS + "test_an_oversize_upload_is_refused_before_it_is_read",
        ),
        Mutant(
            "2: the upload read stops at the cap",
            STUDIO_WEB,
            "            if total > share_page_photos.MAX_INPUT_BYTES:",
            "            if False:",
            KINDS + "test_an_oversize_upload_is_refused_before_it_is_read",
        ),
        Mutant(
            "2: an upload needs the session's CSRF token",
            STUDIO_WEB,
            '        if request.method != "GET" and not studio.csrf_ok(',
            '        if request.method != "GET" and _route_key(request) not in UPLOAD_ROUTES '
            "and not studio.csrf_ok(",
            KINDS + "test_an_upload_needs_the_sessions_token_and_its_own_page",
        ),
        Mutant(
            "2: clearing photos only on one's own page",
            STUDIO_WEB,
            "        if not cleared:",
            "        if False:",
            KINDS + "test_an_upload_needs_the_sessions_token_and_its_own_page",
        ),
        Mutant(
            "2: a date plan needs a place and a time",
            "src/gulbot/web/studio_form.py",
            "    if bool(places) != bool(slots):",
            "    if False:",
            KINDS + "test_a_custom_question_and_its_mistakes",
        ),
        Mutant(
            "2: an unknown kind falls back to the invitation",
            "src/gulbot/web/studio_form.py",
            "    return FormState(kind=kind if kind in KINDS else PageKind.INVITE.value)",
            "    return FormState(kind=kind)",
            KINDS + "test_the_tabs_switch_the_form",
        ),
        Mutant(
            "2: a photo is premium (shared service)",
            "src/gulbot/services/share_page_photos.py",
            "    await premium.require(session, shop_id=shop_id, customer_id=customer_id)",
            "    pass",
            KINDS + "test_a_photo_is_premium",
        ),
        # --- CP27.3: "Mening taklifnomalarim" --------------------------------------------
        Mutant(
            "3: a page id is only ever this creator's own page",
            STUDIO_WEB,
            "    page = await share_pages.get_own_page(\n"
            "        session, shop_id=creator.shop_id, customer_id=creator.customer_id,"
            " page_id=page_id\n"
            "    )\n"
            "    if page is None:\n"
            "        raise web.HTTPNotFound()\n"
            "    return page\n",
            "    page = await session.get(SharePage, page_id)\n"
            "    if page is None:\n"
            "        raise web.HTTPNotFound()\n"
            "    return page\n",
            PAGES + "test_another_creators_page_is_404_everywhere",
        ),
        Mutant(
            "3: delete asks once",
            STUDIO_WEB,
            '        if form.get("confirm") != "1":',
            "        if False:",
            PAGES + "test_delete_asks_once_then_scrubs",
        ),
        Mutant(
            "3: an edit keeps a pin the new link does not name",
            SHARE,
            "    if point is not None:\n"
            '        values["location_lat"], values["location_lon"] = point',
            '    values["location_lat"], values["location_lon"] = point or (None, None)',
            PAGES + "test_set_venues_keeps_a_pin_the_new_link_does_not_name",
        ),
        Mutant(
            "3: an edit to a premium part needs the gift (shared service)",
            SHARE,
            "    if not await premium.unlocked("
            "session, shop_id=shop_id, customer_id=customer_id):\n"
            '        raise EditRefused("premium")',
            "    return None",
            PAGES + "test_an_edit_to_a_premium_design_needs_the_gift",
        ),
        # --- CP27.4: the Telegram Mini App -----------------------------------------------
        Mutant(
            "4: launch data must carry this bot's signature",
            WEBAPP,
            "    if not check_webapp_signature(token, init_data):",
            "    if False:",
            MINI + "test_bad_launch_data_is_refused",
        ),
        Mutant(
            "4: launch data older than an hour is refused",
            WEBAPP,
            "    if not (now - WEBAPP_MAX_AGE <= auth_date <= now + CLOCK_SKEW):",
            "    if not (auth_date <= now + CLOCK_SKEW):",
            MINI + "test_bad_launch_data_is_refused[stale]",
        ),
        Mutant(
            "4: launch data from the future is refused",
            WEBAPP,
            "    if not (now - WEBAPP_MAX_AGE <= auth_date <= now + CLOCK_SKEW):",
            "    if not (now - WEBAPP_MAX_AGE <= auth_date):",
            MINI + "test_bad_launch_data_is_refused[future]",
        ),
        Mutant(
            "4: launch data opens one session (replay nonce)",
            WEBAPP,
            '                    data_hash=hashlib.sha256(fields["hash"].encode()).hexdigest(),',
            "                    data_hash=hashlib.sha256(repr(object()).encode()).hexdigest(),",
            MINI + "test_launch_data_opens_one_session_only",
        ),
        Mutant(
            "4: the key is THIS shop's bot token",
            WEBAPP,
            "    credential = (await load_bot_credentials("
            "session, shop_ids=[shop_id])).get(shop_id)",
            "    credential = max(\n"
            "        (await load_bot_credentials(session)).values(), key=lambda c: c.shop_id\n"
            "    )",
            MINI
            + "test_bad_launch_data_is_refused[other_shops_bot] "
            + MINI
            + "test_valid_launch_data_opens_the_same_session",
        ),
        Mutant(
            "4: the legacy shop uses the process token",
            WEBAPP,
            "        return get_settings().bot_token.get_secret_value() or None",
            "        return None",
            MINI + "test_the_legacy_shop_is_checked_with_the_process_token",
        ),
        Mutant(
            "4: the POST needs JSON and X-Requested-With",
            STUDIO_WEB,
            '        request.headers.get("X-Requested-With") != "gulbot"\n'
            '        or request.content_type != "application/json"\n',
            "        False\n",
            MINI + "test_the_post_needs_json_and_the_header",
        ),
        Mutant(
            "4: the page carries only a well-formed bot name",
            STUDIO_WEB,
            '        "bot": bot if BOT_USERNAME_RE.match(bot) else "",',
            '        "bot": bot,',
            MINI + "test_the_page_loads_only_our_own_script",
        ),
        Mutant(
            "4: the Mini App button only on https",
            "src/gulbot/bot/routers/share_pages.py",
            '    if not base.startswith("https://"):',
            "    if False:",
            MINI + "test_the_bot_offers_the_mini_app_only_on_https",
        ),
        # --- CP27.5: the slim bot ---------------------------------------------------------
        Mutant(
            "5: the wizard is off by default",
            "src/gulbot/config.py",
            "    share_wizard_in_bot: bool = False",
            "    share_wizard_in_bot: bool = True",
            SLIM + "test_the_wizard_is_off_by_default",
        ),
        Mutant(
            "5: off means the one-button menu",
            "src/gulbot/bot/routers/__init__.py",
            "    if not config.share_wizard_in_bot():",
            "    if False:",
            SLIM + "test_the_menu_is_one_button",
        ),
        Mutant(
            "5: an old wizard button answers with the studio",
            SLIM_ROUTER,
            "    router.callback_query.register("
            "to_the_studio, F.data.startswith(WIZARD_PREFIXES))\n",
            "",
            SLIM + "test_an_old_wizard_button_sends_a_studio_link",
        ),
        Mutant(
            "5: a conversation left mid-wizard is cleared",
            SLIM_ROUTER,
            "    router.message.register(\n"
            "        left_mid_wizard,\n"
            "        StateFilter(YesNoPage, InvitePage, ApologyPage, EditPage),\n"
            '        flags={"catch_all": True},\n'
            "    )\n",
            "",
            SLIM + "test_a_conversation_left_mid_wizard_is_cleared",
        ),
        Mutant(
            "5: every wizard button factory is listed",
            SLIM_ROUTER,
            "    SealCB,\n    MusicCB,\n",
            "    SealCB,\n",
            SLIM + "test_every_old_wizard_button_is_covered",
        ),
        Mutant(
            "5: the wishes notification router stays",
            "src/gulbot/bot/routers/__init__.py",
            "        return (build_share_pages_slim_router(), build_share_page_wishes_router())",
            "        return (build_share_pages_slim_router(),)",
            SLIM + "test_the_slim_dispatcher_passes_the_shadow_sweep",
        ),
        # --- CP27 fix A1: no token in a URL -------------------------------------------------
        Mutant(
            "A1: a token in a studio URL is refused unread",
            STUDIO_WEB,
            '    if "csrf" in request.query:',
            "    if False:",
            TOKENS + "test_an_upload_without_its_body_token_is_refused",
        ),
        Mutant(
            "A1: the upload's token comes from its body",
            STUDIO_WEB,
            "        return await _upload_csrf(request)",
            '        return request.query.get("csrf")',
            TOKENS + "test_the_upload_carries_its_token_in_the_body",
        ),
        Mutant(
            "A1: the upload form's URL carries no token",
            "src/gulbot/web/templates/studio/done.html",
            'action="/studio/page/{{ v.page_id }}/photo" class="upload">',
            'action="/studio/page/{{ v.page_id }}/photo?csrf={{ v.csrf }}" class="upload">',
            TOKENS + "test_no_url_redirect_or_log_line_carries_a_token",
        ),
        Mutant(
            "A1: a non-multipart upload is refused, not a crash",
            STUDIO_WEB,
            # Both defences go together: either alone already refuses.
            '    if request.content_type != "multipart/form-data":\n'
            "        return None\n"
            "    try:\n"
            "        reader = await request.multipart()\n"
            "        part = await reader.next()\n"
            "    except (ValueError, AssertionError, KeyError):\n"
            "        return None  # not a multipart body this server can read\n",
            "    reader = await request.multipart()\n    part = await reader.next()\n",
            WEB + "test_every_post_needs_the_sessions_csrf_token",
        ),
        # --- CP27 fix A2: studio-only mode needs https --------------------------------------
        Mutant(
            "A2: over http the bot keeps the wizard",
            "src/gulbot/config.py",
            "    return settings.share_wizard_in_bot or not _pages_are_https(settings)",
            "    return settings.share_wizard_in_bot",
            SLIM + "test_the_wizard_stays_unless_the_pages_are_https",
        ),
        Mutant(
            "A2: production refuses studio-only mode without https",
            "src/gulbot/config.py",
            "    if not settings.share_wizard_in_bot and not _pages_are_https(settings):",
            "    if False:",
            SLIM + "test_production_refuses_studio_only_mode_without_https",
        ),
    ]


def main() -> None:
    from gulbot.config import get_settings

    os.chdir(ROOT)
    if get_settings().postgres_test_db == "gulbot_test":
        raise SystemExit("CP27 mutation proof requires its own test database.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", help="Recheck named guards")
    args = parser.parse_args()
    selected = [m for m in mutants() if not args.only or m.name in args.only]
    results: list[MutationResult] = []
    for mutant in selected:
        file = ROOT / mutant.file
        original = file.read_bytes()
        source = file.read_text(encoding="utf-8")
        if source.count(mutant.old) != 1:
            raise SystemExit(f"Mutant anchor missing or ambiguous: {mutant.name}")
        try:
            file.write_text(source.replace(mutant.old, mutant.new, 1), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    *mutant.test.split(),
                    "-x",
                    "--tb=short",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"},
            )
            output = completed.stdout + completed.stderr
            caught = completed.returncode == 1 and bool(
                re.search(r"E\s+(?:assert|AssertionError)|DID NOT RAISE", output)
            )
            results.append(
                {
                    "guard": mutant.name,
                    "file": mutant.file,
                    "test": mutant.test,
                    "assertion_caught": caught,
                    "exit_code": completed.returncode,
                }
            )
            print(f"{mutant.name}: {'caught' if caught else 'NOT PROVEN'}", flush=True)
            if not caught:
                print(output[-2500:])
        finally:
            file.write_bytes(original)
        if file.read_bytes() != original:
            raise SystemExit("Mutation restore failed.")
    if args.only and REPORT.exists():
        # A partial run updates its own guards and keeps every other recorded result.
        kept = [
            r
            for r in json.loads(REPORT.read_text(encoding="utf-8"))["results"]
            if r["guard"] not in {m.name for m in selected}
        ]
        results = kept + results
    REPORT.write_text(
        json.dumps(
            {
                "caught": sum(r["assertion_caught"] for r in results),
                "total": len(results),
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    if not all(r["assertion_caught"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
