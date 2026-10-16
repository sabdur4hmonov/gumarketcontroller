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
